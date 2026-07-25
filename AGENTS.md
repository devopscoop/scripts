# AGENTS.md

Instructions for AI coding agents working in this repo. `CLAUDE.md` is a symlink
to this file — edit `AGENTS.md`, and never replace the symlink with a copy.

## What this repo is

A collection of standalone DevOps/ops helper scripts. There is no build system,
no test suite, no linter config, and no shared library: each script is an
independent executable that talks to an external service (AWS, Linear, CalDAV,
the OpenTofu registry, the GitHub API). Nothing here imports anything else here.

Because there is no test harness, "verifying a change" means running the script
against its dry-run/preview path (see below) or, for shell, at minimum
`bash -n <script>.sh`. Reaching for a new tool (shellcheck, pytest, …) is not
free — see [Package manifests](#package-manifests).

## Running the scripts

Every destructive script defaults to a safe mode and needs an explicit opt-in to
act. **Preserve that property when editing.**

| Script | Safe invocation | Acts only when |
| --- | --- | --- |
| `upgrade_opentofu_modules.py [glob]` | dry run by default (`**/*.tf`, skips `.terraform/`) | `--write` |
| `caldav_delete_dupes.py` | prompts, and always writes a timestamped `.ics` backup first | `--yes` |
| `github_actions/image-retention-policy.sh` | `dry_run=true` default | `dry_run=false` |
| `yaml_dedup.py base.yaml override.yaml` | **none — rewrites `override.yaml` in place** | always |

`yaml_dedup.py` is the exception: no dry run, no backup. Copy the file before
testing against it.

Credentials come from flags or environment variables, never from config files in
this repo: `LINEAR_API_KEY` (`monthly_report_linear.sh`), `CALDAV_URL` /
`CALDAV_USERNAME` / `CALDAV_PASSWORD` or `--password-file`
(`caldav_delete_dupes.py`), and `SAML2AWS_USERNAME` / `SAML2AWS_PASSWORD` /
`idp_provider` / `mfa` / `url` (`saml2aws_configure.sh`).

After `upgrade_opentofu_modules.py --write`, lockfiles need
`tofu init -backend=false -upgrade`. The script exits 2 if any upgrade was
blocked by the scan gate or any registry lookup failed.

## Architecture

### upgrade_opentofu_modules.py

The largest script, and the one whose design is easiest to break. Three things
interact:

1. **Block-aware rewriting.** `.tf` files are parsed by tracking brace depth into
   a stack of frames, so `source` and `version` can appear in either order and a
   `version` is only ever paired with the `source` in its own block. Rewrites are
   line-level regex substitutions — the file is never reformatted. Only *exact*
   pins are touched; constraint expressions (`~>`, `>=`, …) are reported and left
   alone, because replacing them would change their semantics.
2. **A fail-closed security gate** on the *target* version, run before an upgrade
   is even reported in a dry run. Modules are downloaded with `tofu get` (falling
   back to `terraform`) and scanned by Trivy, Checkov, and a built-in grep for
   code-execution constructs (`local-exec`/`remote-exec` provisioners,
   `data "external"`, `data "http"`), which always block. Providers are compiled
   binaries and cannot be code-scanned, so instead the registry SHASUMS manifest
   is GPG-verified against the publisher key and this platform's checksum is
   confirmed to be inside the signed manifest. A missing tool or a failed
   download is an *error*, and errors block — that is deliberate. `--skip-scan`
   is the only bypass.
3. **Two caches** (`_version_cache`, `_scan_cache`) keyed by registry path, so a
   module referenced across many files is fetched and scanned once. Keep new
   lookups behind them.

Standard library only — `urllib.request`, not `requests`.

### yaml_dedup.py

Deliberately two-phase: ruamel.yaml loads both files only to compute the set of
dotted key paths whose values are identical in the base file (recursing into
nested maps and dropping parents that become empty), and then a separate
line-level filter deletes those key subtrees from the override file's raw text.

The override file is never round-tripped through a YAML dumper, because that
reflows comments, quoting, and spacing. A previous version lost comments; that
was the bug the rewrite fixed. Any change here must keep comments and formatting
of surviving lines byte-identical.

### github_actions/ — templates for *other* repos

These files are **not** used by this repo. They are copy-paste templates to
install into a consuming repo's `.github/workflows/`.

`image-retention-policy.yml` sets `working-directory: .github/workflows` and runs
`./image-retention-policy.sh`, so **both files must be copied into that same
directory** of the target repo. Its actual `gh api --method DELETE` call is
currently commented out behind a TODO: deleting a version can pull tags you meant
to keep, producing `manifest unknown` on pull. Do not uncomment it without
solving that tag-safety problem first.

`dump-and-encrypt-secrets.yml` is a manually dispatched workflow that dumps the
repo's secrets into an `age`-encrypted artifact for the holder of the private
key. Its usage steps live in the file header.

### .github/workflows/ — this repo's own CI

Only the two Claude Code workflows, and their comments carry the reasoning:

- **`claude-code-review.yml`** runs automatically on every PR in *agent mode*
  (because it passes a `prompt`). In agent mode the `--allowed-tools` allowlist
  is load-bearing, not cosmetic: the inline-comment MCP server is registered only
  if the list contains an `mcp__github_inline_comment__` entry, so trimming it
  makes the job review the code and silently post nothing. The list is scoped to
  read-and-comment; `gh pr merge` and `gh pr create` are absent on purpose. The
  code-review plugin is intentionally not used — it reports via `ReportFindings`,
  which claude-code-action does not consume.
- **`claude.yml`** is tag mode (`@claude` mentions) and builds its own tool list.
  Bash stays disabled, so Claude pushes a branch and hands back a prefilled PR
  link instead of opening the PR itself.

Both pin `--model claude-opus-5 --effort xhigh` so CI does not drift with CLI
defaults, and all actions are pinned to a commit SHA with a trailing `# vN`
comment. Keep both conventions.

## Conventions

- Shell: `#!/usr/bin/env bash`, `set -Eeuo pipefail` on newer scripts, a heredoc
  usage block that exits non-zero when required args or env vars are missing, and
  `while read -r line; do … done < <(cmd)` for streaming command output.
- Python: `#!/usr/bin/env python3`, executable bit set, argparse, type hints, and
  a module docstring that doubles as the usage documentation — that docstring is
  the reference for behavior, so update it alongside flag changes.
- Deprecated scripts stay in the tree: they print a `Deprecated:` line at runtime
  and are listed under README's "Deprecated" heading rather than deleted.
- New script → `chmod +x`, document in README.md, add its tools to both package
  manifests.
- Commit subjects use conventional prefixes (`feat:`, `fix:`, `docs:`, `chore:`,
  `ci:`).
- Use `tofu`, not `terraform`.

## Package manifests

This repo ships a `Brewfile` (macOS: `brew bundle`) and a `pkglist.txt` (Arch
Linux) that install every CLI tool the scripts use. Keep them in sync with the
code:

- When you add a script — or a new external command inside an existing script —
  add the tools it invokes to BOTH files, with a comment noting which script
  uses them.
- When a tool stops being used, remove it from both files.
- Verify package names before adding them: `brew info <formula>` for Homebrew,
  and the official repos/AUR for Arch. Names differ between ecosystems (e.g.
  Homebrew `awscli` is Arch `aws-cli-v2`; Homebrew `gh` is Arch `github-cli`).
  If a package is AUR-only, note that in pkglist.txt's header instructions; if
  it isn't packaged for Arch at all (like checkov), document the pip/uv install
  in the header instead.
- Python library dependencies (like caldav and ruamel.yaml) are not
  package-manager packages — document them in the manifest headers and the
  README's `pip install` line.
- Update the "Install required packages" section in README.md if the tool list
  changes.
- OpenTofu is managed by tenv — never add `opentofu` directly to the manifests.
