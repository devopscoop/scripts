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

Notes:
  - Only exact version pins (e.g. "6.6.1") are updated. Lines with a constraint
    operator (~>, >=, <, etc.) are left untouched and reported, since replacing
    them with an exact version would change their semantics.
  - "Latest" means the newest published version, which may be a major-version
    bump with breaking changes. Review the dry-run output before --write.
"""

import argparse
import json
import re
import sys
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


def _strip_strings(line: str) -> str:
    """Remove double-quoted string literals so braces inside them (e.g. "${var.x}")
    don't affect block-depth tracking."""
    return re.sub(r'"[^"]*"', '', line)


def update_file(path: Path, dry_run: bool, stats: dict) -> None:
    """Update each module/provider version to the latest registry version.

    Blocks are tracked by brace depth, so source and version may appear in any
    order within a block, and only the version belonging to the same block as a
    source is updated.
    """
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
        elif new == old:
            print(f"  {src}: {old} (up to date)")
        else:
            lines[vidx] = VERSION_RE.sub(
                lambda m: m.group(1) + new + m.group(3), lines[vidx], count=1
            )
            stats['updates'] += 1
            changed = True
            tag = ' (dry-run)' if dry_run else ''
            print(f"  {src}: {old} -> {new}{tag}")

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
    args = parser.parse_args()
    dry_run = not args.write

    files = sorted(Path('.').glob(args.pattern))
    files = [f for f in files if '.terraform' not in f.parts]
    if not files:
        print(f"No .tf files found matching '{args.pattern}'")
        sys.exit(1)

    stats = {'updates': 0, 'failures': 0}
    for tf in files:
        print(tf)
        update_file(tf, dry_run, stats)

    mode = 'would update' if dry_run else 'updated'
    print(f"\n{stats['updates']} version(s) {mode}.")
    if dry_run and stats['updates']:
        print('Re-run with --write to apply.')
    if stats['failures']:
        print(f"{stats['failures']} registry lookup(s) failed.", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
