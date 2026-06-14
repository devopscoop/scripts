#!/usr/bin/env python3
"""
Update Terraform/OpenTofu module and provider versions to their latest registry versions.

Usage:
  python3 upgrade_opentofu_modules.py [glob_pattern]            # dry run (default): show what would change
  python3 upgrade_opentofu_modules.py --write [glob_pattern]    # apply the changes in place

  glob_pattern defaults to **/*.tf (all .tf files under the current directory).
  Files inside .terraform/ directories are always skipped.

Examples:
  python3 upgrade_opentofu_modules.py                      # preview every change
  python3 upgrade_opentofu_modules.py 'cluster/*.tf'       # preview only the cluster directory
  python3 upgrade_opentofu_modules.py --write 'cluster/*.tf'
  python3 upgrade_opentofu_modules.py --write --skip-scan   # skip the security gate (fast path)

Security scan gate:
  Before an upgrade is reported (dry run) or applied (--write), the *target*
  version is scanned. This is a gate: a module whose target version fails the
  scan is NOT written, even with --write. Use --skip-scan to bypass it.

    - Modules (namespace/name/provider) are downloaded at the target version
      with `tofu get` (falls back to `terraform get`) and scanned with Trivy and
      Checkov, plus a built-in check for dangerous constructs (local-exec /
      remote-exec provisioners, `data "external"`, `data "http"`) that are the
      usual code-execution / exfiltration vectors in module source.
    - Providers (namespace/name) are compiled binaries, so they cannot be
      code-scanned. Instead the registry SHASUMS file for the target version is
      GPG-verified against the publisher's signing key, and the published
      checksum for this platform is confirmed to be in that signed manifest.

  Findings at or above --severity (default CRITICAL) block the upgrade; anything
  below is printed as advisory. Dangerous constructs and provider verification
  failures always block. A missing tool (tofu/trivy/checkov/gpg) fails closed
  (blocks) -- install it or pass --skip-scan.

Notes:
  - Only exact version pins (e.g. "6.6.1") are updated. Lines with a constraint
    operator (~>, >=, <, etc.) are left untouched and reported, since replacing
    them with an exact version would change their semantics.
  - "Latest" means the newest published version, which may be a major-version
    bump with breaking changes. Review the dry-run output before --write.
  - The scan is defense-in-depth, not proof of safety: Trivy/Checkov find
    misconfigurations (not malware), and the provider GPG key is the one the
    registry vouches for. The provider binary's own checksum is still enforced
    by `tofu init` against your committed .terraform.lock.hcl.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

REGISTRY = 'https://registry.terraform.io/v1'

SOURCE_RE = re.compile(r'(\s+source\s*=\s*")([^"]+)(")')
VERSION_RE = re.compile(r'(\s+version\s*=\s*")([^"]+)(")')
# An exact pin: a leading digit (optionally a "v" prefix) and no constraint
# operators or whitespace. Anything else (~>, >=, "1.0, < 2.0", ...) is a constraint.
EXACT_VERSION_RE = re.compile(r'v?\d[\w.\-+]*\Z')

# Cache registry lookups so a module referenced in many files is fetched once.
_version_cache: dict[str, Optional[str]] = {}

# Severity ordering shared by Trivy, Checkov, and the built-in construct check.
SEVERITY_RANK = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}

# Module source patterns that execute code or reach the network. These are the
# realistic malware / exfiltration vectors in HCL, so they always block.
DANGEROUS_CONSTRUCTS = [
    (re.compile(r'provisioner\s+"(local|remote)-exec"'),
     'provisioner "{0}-exec" runs arbitrary shell commands during apply'),
    (re.compile(r'data\s+"external"'),
     'data "external" executes an external program during plan'),
    (re.compile(r'data\s+"http"'),
     'data "http" makes outbound network requests during plan'),
]
# Command-line tools commonly used for exfiltration; reported as advisory since
# they also appear in legitimate scripts and comments.
SUSPICIOUS_CMD_RE = re.compile(r'\b(curl|wget|nc|ncat|Invoke-WebRequest)\b')

# Cache scan verdicts so a module/provider referenced many times is scanned once.
_scan_cache: dict[str, dict] = {}


class ScanError(Exception):
    """A scan could not be completed (missing tool, download/verify failure)."""


def fetch_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={'User-Agent': 'update-tf-versions/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  warning: HTTP {e.code} for {url}", file=sys.stderr)
    except Exception as e:
        print(f"  warning: {e} for {url}", file=sys.stderr)
    return None


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    """Download raw bytes, raising ScanError on failure (used by the scan gate)."""
    req = urllib.request.Request(url, headers={'User-Agent': 'update-tf-versions/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        raise ScanError(f"download failed for {url}: {e}")


def latest_version(source: str) -> Optional[str]:
    # Strip submodule path before registry lookup (e.g. "ns/mod/prov//modules/foo" -> "ns/mod/prov").
    # Submodules share the parent module's version.
    registry_path = source.split('//')[0]
    if registry_path in _version_cache:
        return _version_cache[registry_path]

    parts = registry_path.split('/')
    if len(parts) == 3:
        data = fetch_json(f"{REGISTRY}/modules/{registry_path}")
    elif len(parts) == 2:
        data = fetch_json(f"{REGISTRY}/providers/{registry_path}")
    else:
        data = None

    version = data.get('version') if data else None
    _version_cache[registry_path] = version
    return version


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, capturing output. Raises ScanError if the binary is missing."""
    if shutil.which(cmd[0]) is None:
        raise ScanError(f"'{cmd[0]}' not found on PATH (install it or use --skip-scan)")
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _tofu_bin() -> str:
    for name in ('tofu', 'terraform'):
        if shutil.which(name):
            return name
    raise ScanError("neither 'tofu' nor 'terraform' found on PATH (needed to fetch module source)")


def _download_module(registry_path: str, version: str) -> Path:
    """Fetch a registry module's source at an exact version into a temp dir.

    Delegates to `tofu get` so resolution of the registry source, the version
    tag, and any nested modules matches what OpenTofu itself would install.
    Returns the directory to scan; the caller is responsible for cleanup.
    """
    tofu = _tofu_bin()
    tmp = Path(tempfile.mkdtemp(prefix='tfscan-'))
    (tmp / 'main.tf').write_text(
        f'module "scan" {{\n'
        f'  source  = "{registry_path}"\n'
        f'  version = "{version}"\n'
        f'}}\n'
    )
    proc = _run([tofu, 'get'], cwd=str(tmp))
    modules_dir = tmp / '.terraform' / 'modules'
    if proc.returncode != 0 or not modules_dir.is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        detail = (proc.stderr or proc.stdout or '').strip().splitlines()
        raise ScanError(f"`{tofu} get` failed for {registry_path} {version}: "
                        f"{detail[-1] if detail else 'no module downloaded'}")
    return modules_dir


def _at_or_above(severity: Optional[str], threshold: str) -> bool:
    rank = SEVERITY_RANK.get((severity or '').upper(), 0)
    return rank >= SEVERITY_RANK[threshold]


def scan_dangerous_constructs(root: Path) -> dict:
    """Grep module source for code-execution / network constructs."""
    blocking, advisory = [], []
    for tf in root.rglob('*.tf'):
        rel = tf.relative_to(root)
        for n, raw in enumerate(tf.read_text(errors='replace').splitlines(), 1):
            for pat, msg in DANGEROUS_CONSTRUCTS:
                m = pat.search(raw)
                if m:
                    arg = m.group(1) if m.groups() else ''
                    blocking.append(f"{rel}:{n}: {msg.format(arg)}")
            if SUSPICIOUS_CMD_RE.search(raw):
                advisory.append(f"{rel}:{n}: references a network/command tool")
    return {'blocking': blocking, 'advisory': advisory, 'errors': []}


def run_trivy(root: Path, threshold: str) -> dict:
    proc = _run(['trivy', 'config', '--quiet', '--format', 'json', str(root)])
    if proc.returncode not in (0, 1):  # 1 == findings present with default exit code
        raise ScanError(f"trivy failed: {(proc.stderr or '').strip()[:200]}")
    try:
        data = json.loads(proc.stdout or '{}')
    except json.JSONDecodeError as e:
        raise ScanError(f"could not parse trivy output: {e}")
    blocking, advisory = [], []
    for result in data.get('Results') or []:
        target = result.get('Target', '')
        for mc in result.get('Misconfigurations') or []:
            sev = mc.get('Severity', 'UNKNOWN')
            line = f"[trivy {sev}] {mc.get('ID', '?')} {mc.get('Title', '')} ({target})"
            (blocking if _at_or_above(sev, threshold) else advisory).append(line)
    return {'blocking': blocking, 'advisory': advisory, 'errors': []}


def run_checkov(root: Path, threshold: str) -> dict:
    proc = _run(['checkov', '-d', str(root), '-o', 'json', '--compact', '--quiet'])
    if not (proc.stdout or '').strip():
        raise ScanError(f"checkov produced no output: {(proc.stderr or '').strip()[:200]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ScanError(f"could not parse checkov output: {e}")
    # Checkov emits either a single result object or a list (one per framework).
    reports = data if isinstance(data, list) else [data]
    blocking, advisory = [], []
    for report in reports:
        for chk in (report.get('results') or {}).get('failed_checks') or []:
            sev = chk.get('severity')  # often null in OSS checkov
            where = f"{chk.get('file_path', '')}:{chk.get('resource', '')}"
            line = f"[checkov {sev or 'n/a'}] {chk.get('check_id', '?')} {chk.get('check_name', '')} ({where})"
            # Block only when checkov reports a severity at/above threshold;
            # severity-less findings are advisory to keep the gate usable.
            (blocking if _at_or_above(sev, threshold) else advisory).append(line)
    return {'blocking': blocking, 'advisory': advisory, 'errors': []}


def scan_module(registry_path: str, version: str, scanners: list[str], threshold: str) -> dict:
    blocking, advisory, errors = [], [], []
    src = _download_module(registry_path, version)
    try:
        steps = [('dangerous-constructs', scan_dangerous_constructs)]
        if 'trivy' in scanners:
            steps.append(('trivy', lambda r: run_trivy(r, threshold)))
        if 'checkov' in scanners:
            steps.append(('checkov', lambda r: run_checkov(r, threshold)))
        for name, step in steps:
            print(f"      scanning {registry_path} {version} with {name}...")
            try:
                out = step(src)
                blocking += out['blocking']
                advisory += out['advisory']
            except ScanError as e:
                errors.append(str(e))
    finally:
        shutil.rmtree(src.parent.parent, ignore_errors=True)  # the tempdir root
    return {'blocking': blocking, 'advisory': advisory, 'errors': errors}


def _platform() -> tuple[str, str]:
    os_name = platform.system().lower()
    machine = platform.machine().lower()
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64',
            'arm64': 'arm64', 'i386': '386', 'i686': '386'}.get(machine, machine)
    return os_name, arch


def verify_provider(registry_path: str, version: str) -> dict:
    """GPG-verify the target version's SHASUMS manifest against the publisher key
    and confirm this platform's checksum is in it. Any failure blocks (fail-closed).
    """
    print(f"      verifying {registry_path} {version} provider signature (GPG SHASUMS)...")
    os_name, arch = _platform()
    meta = fetch_json(
        f"{REGISTRY}/providers/{registry_path}/{version}/download/{os_name}/{arch}")
    if not meta:
        return {'blocking': [], 'advisory': [],
                'errors': [f"could not fetch download metadata for {registry_path} {version} "
                           f"({os_name}/{arch})"]}

    keys = (meta.get('signing_keys') or {}).get('gpg_public_keys') or []
    if not keys:
        return {'blocking': [f"{registry_path} {version}: no GPG signing key published"],
                'advisory': [], 'errors': []}

    gpghome = Path(tempfile.mkdtemp(prefix='tfscan-gpg-'))
    try:
        env = {**os.environ, 'GNUPGHOME': str(gpghome)}
        os.chmod(gpghome, 0o700)
        for key in keys:
            imp = _run(['gpg', '--batch', '--import'], input=key.get('ascii_armor', ''), env=env)
            if imp.returncode != 0:
                return {'blocking': [], 'advisory': [],
                        'errors': [f"failed to import signing key: {(imp.stderr or '').strip()[:200]}"]}

        shasums = fetch_bytes(meta['shasums_url'])
        sig = fetch_bytes(meta['shasums_signature_url'])
        sums_file = gpghome / 'SHASUMS'
        sig_file = gpghome / 'SHASUMS.sig'
        sums_file.write_bytes(shasums)
        sig_file.write_bytes(sig)

        verify = _run(['gpg', '--batch', '--verify', str(sig_file), str(sums_file)], env=env)
        if verify.returncode != 0:
            return {'blocking': [f"{registry_path} {version}: SHASUMS signature did NOT verify "
                                 f"against the published key"],
                    'advisory': [], 'errors': []}

        # The signature is valid; now make sure this platform's artifact checksum
        # is actually covered by the signed manifest.
        filename = meta.get('filename', '')
        want = meta.get('shasum', '')
        listed = {ln.split()[1]: ln.split()[0]
                  for ln in shasums.decode('utf-8', 'replace').splitlines() if len(ln.split()) == 2}
        if listed.get(filename) != want or not want:
            return {'blocking': [f"{registry_path} {version}: checksum for {filename} "
                                 f"is missing from or inconsistent with the signed SHASUMS"],
                    'advisory': [], 'errors': []}

        return {'blocking': [], 'advisory':
                [f"{registry_path} {version}: SHASUMS GPG signature verified ({filename})"],
                'errors': []}
    except ScanError as e:
        return {'blocking': [], 'advisory': [], 'errors': [str(e)]}
    finally:
        shutil.rmtree(gpghome, ignore_errors=True)


def scan_gate(source: str, version: str, opts: argparse.Namespace) -> dict:
    """Scan the target version of a module/provider. Returns a verdict dict with
    'ok' plus 'blocking', 'advisory', and 'errors' lists. Cached per source+version.
    """
    registry_path = source.split('//')[0]
    parts = registry_path.split('/')
    kind = 'module' if len(parts) == 3 else 'provider' if len(parts) == 2 else 'unknown'
    cache_key = f"{kind}:{registry_path}:{version}"
    if cache_key in _scan_cache:
        return _scan_cache[cache_key]

    try:
        if kind == 'module':
            result = scan_module(registry_path, version, opts.scanners, opts.severity)
        elif kind == 'provider':
            result = verify_provider(registry_path, version)
        else:
            result = {'blocking': [], 'advisory': [],
                      'errors': [f"unrecognized source '{source}', cannot scan"]}
    except ScanError as e:
        result = {'blocking': [], 'advisory': [], 'errors': [str(e)]}

    # Fail closed: blocking findings OR any error (missing tool, download fail) gate the upgrade.
    result['ok'] = not result['blocking'] and not result['errors']
    _scan_cache[cache_key] = result
    return result


def _strip_strings(line: str) -> str:
    """Remove double-quoted string literals so braces inside them (e.g. "${var.x}")
    don't affect block-depth tracking."""
    return re.sub(r'"[^"]*"', '', line)


def update_file(path: Path, opts: argparse.Namespace, stats: dict) -> None:
    """Update each module/provider version to the latest registry version.

    Blocks are tracked by brace depth, so source and version may appear in any
    order within a block, and only the version belonging to the same block as a
    source is updated.
    """
    dry_run = not opts.write
    lines = path.read_text().splitlines(keepends=True)

    # Stack of block frames. A sentinel frame at the bottom catches stray lines.
    stack = [{'source': None, 'version_idx': None}]
    changed = False

    def maybe_update(frame: dict) -> None:
        nonlocal changed
        src = frame['source']
        vidx = frame['version_idx']
        if src is None or vidx is None:
            return

        old = VERSION_RE.match(lines[vidx]).group(2)
        if not EXACT_VERSION_RE.match(old):
            print(f"  {src}: {old} (version constraint, leaving as-is)")
            return

        new = latest_version(src)
        if new is None:
            stats['failures'] += 1
            print(f"  {src}: {old} (registry lookup failed, skipping)")
            return
        if new == old:
            print(f"  {src}: {old} (up to date)")
            return

        # Security gate: scan the target version before reporting/applying it.
        if not opts.skip_scan:
            verdict = scan_gate(src, new, opts)
            for note in verdict['advisory']:
                print(f"      · {note}")
            if not verdict['ok']:
                stats['blocked'] += 1
                print(f"  {src}: {old} -> {new}  BLOCKED by security scan")
                for f in verdict['blocking']:
                    print(f"      ✗ {f}")
                for e in verdict['errors']:
                    print(f"      ! {e}")
                return

        lines[vidx] = VERSION_RE.sub(
            lambda m: m.group(1) + new + m.group(3), lines[vidx], count=1
        )
        stats['updates'] += 1
        changed = True
        tag = ' (dry-run)' if dry_run else ''
        scan_tag = ' (scan skipped)' if opts.skip_scan else ''
        print(f"  {src}: {old} -> {new}{tag}{scan_tag}")

    for i, line in enumerate(lines):
        sm = SOURCE_RE.match(line)
        vm = VERSION_RE.match(line)
        if sm:
            stack[-1]['source'] = sm.group(2)
        elif vm:
            stack[-1]['version_idx'] = i

        stripped = _strip_strings(line)
        for _ in range(stripped.count('{')):
            stack.append({'source': None, 'version_idx': None})
        for _ in range(stripped.count('}')):
            if len(stack) > 1:
                maybe_update(stack.pop())

    # Flush any frames left open by unbalanced braces.
    while len(stack) > 1:
        maybe_update(stack.pop())

    if changed and not dry_run:
        path.write_text(''.join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Update Terraform/OpenTofu module and provider versions to the latest.'
    )
    parser.add_argument(
        'pattern', nargs='?', default='**/*.tf', help='glob of .tf files (default: **/*.tf)'
    )
    parser.add_argument(
        '--write', action='store_true', help='apply changes in place (default: dry run)'
    )
    parser.add_argument(
        '--skip-scan', action='store_true',
        help='bypass the security scan gate (faster, but applies upgrades unscanned)'
    )
    parser.add_argument(
        '--scanners', default='trivy,checkov',
        help='comma-separated module scanners to run (default: trivy,checkov)'
    )
    parser.add_argument(
        '--severity', default='CRITICAL', choices=list(SEVERITY_RANK),
        help='scan findings at or above this severity block the upgrade (default: CRITICAL)'
    )
    args = parser.parse_args()
    args.scanners = [s.strip().lower() for s in args.scanners.split(',') if s.strip()]
    dry_run = not args.write

    files = sorted(Path('.').glob(args.pattern))
    files = [f for f in files if '.terraform' not in f.parts]
    if not files:
        print(f"No .tf files found matching '{args.pattern}'")
        sys.exit(1)

    stats = {'updates': 0, 'failures': 0, 'blocked': 0}
    for tf in files:
        print(tf)
        update_file(tf, args, stats)

    mode = 'would update' if dry_run else 'updated'
    print(f"\n{stats['updates']} version(s) {mode}.")
    if dry_run and stats['updates']:
        print('Re-run with --write to apply.')
    if not dry_run and stats['updates']:
        print('Run "tofu init -backend=false -upgrade" to update the lockfiles.')
    if stats['blocked']:
        print(f"{stats['blocked']} upgrade(s) BLOCKED by the security scan "
              f"(review above, or --skip-scan to override).", file=sys.stderr)
    if stats['failures']:
        print(f"{stats['failures']} registry lookup(s) failed.", file=sys.stderr)
    if stats['failures'] or stats['blocked']:
        sys.exit(2)


if __name__ == '__main__':
    main()
