# Brewfile for scripts
#
# Installs every CLI tool used or referenced by this repo.
# Usage: brew bundle
#
# Python library dependencies are not Homebrew packages and must be installed
# separately: caldav (caldav_delete_dupes.py) and ruamel.yaml (yaml_dedup.py),
# e.g. `pip install caldav ruamel.yaml`.

# age (includes age-keygen) - local keygen/decrypt for the dump-and-encrypt-secrets workflow
brew "age"

# AWS CLI v2 (`aws`) - SSO session/profile configuration (v2-only subcommands)
brew "awscli"

# AWS SSO CLI (`aws-sso`) - recommended replacement for the deprecated
# aws_configure_all_sso.sh script
brew "aws-sso-cli"

# bash - all shell scripts use `#!/usr/bin/env bash`
brew "bash"

# checkov - optional advisory scanner for upgrade_opentofu_modules.py
# (opt-in via --scanners trivy,checkov)
brew "checkov"

# colima - provides the Docker engine (lightweight Linux VM) for ai_sandbox.sh
# on macOS; run `colima start` first. (Alternative: the docker-desktop cask.)
brew "colima"

# curl - monthly_report_linear.sh posts to the Linear GraphQL API
brew "curl"

# Docker CLI - ai_sandbox.sh runs the workstation image with it
brew "docker"

# gh - GitHub CLI, used by github_actions/image-retention-policy.sh
brew "gh"

# gnupg (`gpg`) - verifies provider SHASUMS signatures in upgrade_opentofu_modules.py
brew "gnupg"

# jq - JSON parsing across several scripts
brew "jq"

# python - the .py scripts use `#!/usr/bin/env python3`
brew "python"

# saml2aws - Okta/DUO SAML to AWS credential process
brew "saml2aws"

# tenv - provides `tofu` for upgrade_opentofu_modules.py (which probes for
# tofu, then terraform). Do NOT install opentofu directly.
brew "tenv"

# trivy - advisory misconfiguration scanner in upgrade_opentofu_modules.py's security gate
brew "trivy"
