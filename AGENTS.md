# AGENTS.md

Instructions for AI coding agents working in this repo.

## Package manifests

This repo ships a `Brewfile` (macOS: `brew bundle`) and a `pkglist.txt` (Arch Linux) that install every CLI tool the scripts use. Keep them in sync with the code:

- When you add a script — or a new external command inside an existing script — add the tools it invokes to BOTH files, with a comment noting which script uses them.
- When a tool stops being used, remove it from both files.
- Verify package names before adding them: `brew info <formula>` for Homebrew, and the official repos/AUR for Arch. Names differ between ecosystems (e.g. Homebrew `awscli` is Arch `aws-cli-v2`; Homebrew `gh` is Arch `github-cli`). If a package is AUR-only, note that in pkglist.txt's header instructions; if it isn't packaged for Arch at all (like checkov), document the pip/uv install in the header instead.
- Python library dependencies (like caldav and ruamel.yaml) are not package-manager packages — document them in the manifest headers and the README's `pip install` line.
- Update the "Install required packages" section in README.md if the tool list changes.
- OpenTofu is managed by tenv — never add `opentofu` directly to the manifests.
