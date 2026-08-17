# AWS tools

## Install required packages

This repo ships package manifests that install every CLI tool its scripts use (`age`, `aws`, `aws-sso`, `bash`, `checkov`, `curl`, `docker` plus `colima` on macOS, `gh`, `gpg`, `jq`, `python3`, `saml2aws`, `tenv` for `tofu`, `trivy`):

- macOS, using [Homebrew](https://brew.sh/) and the `Brewfile`:

  ```shell
  brew bundle
  ```

- Arch Linux, using the `pkglist.txt`. This requires an AUR helper such as [yay](https://github.com/Jguer/yay) or [paru](https://github.com/Morganamilo/paru), because `aws-sso-cli-bin`, `saml2aws`, and `tenv-bin` are AUR packages. `checkov` (only needed for the opt-in `--scanners trivy,checkov`) isn't packaged for Arch at all — install it with `uv tool install checkov` or `pipx install checkov`:

  ```shell
  grep -vE '^(#|$)' pkglist.txt | yay -S --needed -
  ```

On other operating systems, install the tools listed above manually.

The Python scripts also need libraries that package managers don't provide: `pip install caldav ruamel.yaml`.

## ai_sandbox.sh

Runs [Claude Code](https://claude.com/claude-code) or [OpenCode](https://opencode.ai) inside the [devopscoop workstation image](https://github.com/devopscoop/workstation) as a throwaway sandbox: the agent runs as your own UID/GID, sees only the directory you launch it in (mounted at `/work/<dirname>`) plus a shared sandbox home, and gets no access to `~/.aws`, `~/.kube`, `~/.ssh`, `~/.gnupg`, your real `~/.claude`, or the Docker socket. Run it from a project root:

```bash
./ai_sandbox.sh                  # Claude Code (default)
./ai_sandbox.sh opencode         # OpenCode
./ai_sandbox.sh claude --resume  # extra args pass through to the agent
```

It honors a few environment variables:

| Variable            | Default        | Purpose                                                                                 |
| ------------------- | -------------- | --------------------------------------------------------------------------------------- |
| `IMAGE`             | `ghcr.io/devopscoop/workstation:main-aws` | Image to run; override with a local build or a different CSP variant.         |
| `DOCKER`            | `docker` on macOS, `sudo docker` on Linux | How to invoke Docker; on Linux set `DOCKER=docker` if you run rootless or are in the `docker` group. |
| `SANDBOX_HOME`      | `~/.sandbox-home` | Host directory holding agent state (auth, config, history), mounted as the container HOME. Shared across projects so you log in once; set `SANDBOX_HOME="$PWD/.sandbox-home"` to isolate one project's agent state instead. |
| `ANTHROPIC_API_KEY` | *(unset)*      | If set in your shell, it's forwarded into the container (as an env var, **not** a mounted file) so Claude Code is authenticated without an interactive login. |

Notes:

- **Authentication.** Either export `ANTHROPIC_API_KEY`, or log in interactively the first time — the login is stored under `~/.sandbox-home/` on the host and persists across runs *and* projects. It is deliberately **not** your real `~/.claude` (the sandbox must never touch your laptop's config; on macOS the OAuth token lives in the Keychain anyway).
- **Sharing trade-off.** Every project's sandbox shares `~/.sandbox-home`, so an agent in one project can read state (including credentials) an agent left there from another project. For an untrusted project, run with its own `SANDBOX_HOME`.
- **Network is open** (the agents need it to reach their APIs); only the filesystem is sandboxed.
- The Docker CLI is in the image but the socket is intentionally **not** mounted, so the agent can't reach your host's Docker daemon.
- Running as a non-root UID relies on Claude Code being installed under `/opt/claude` (world-readable) rather than root's home; this is handled in the workstation `Dockerfile`. If you run an older image that installed it under `/root`, `claude` will fail with a permission error — rebuild it.
- On macOS, start the Docker engine first: `colima start`.

### Without the script

The image is pulled automatically on first run (to build it locally instead, see the [workstation repo](https://github.com/devopscoop/workstation)). The script only wraps one `docker run` — the equivalent one-liner, if you'd rather not install it (drop `sudo` on macOS/colima):

```bash
mkdir -p ~/.sandbox-home && sudo docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges \
  -v "$HOME/.sandbox-home:/sandbox-home" \
  -v "$PWD:/work/$(basename "$PWD")" -w "/work/$(basename "$PWD")" \
  -e HOME=/sandbox-home -e USER="$(id -un)" \
  ghcr.io/devopscoop/workstation:main-aws claude
```

Swap `claude` for `opencode` to run the other agent. The `~/.sandbox-home/` directory keeps the agents' auth, config, and history in one place on the host, shared by every project's sandbox — so you log in once, not once per project. It is deliberately **not** your real `~/.claude` (the sandbox must never touch your laptop's config; on macOS the OAuth token lives in the Keychain anyway). The project mounts at `/work/<dirname>` rather than a fixed `/work` so Claude Code keeps trust, history, and `--resume` separate per project.

## saml2aws

Here are two helper scripts for saml2aws.

### saml2aws_configure.sh

Run this script once with your Okta username, password, and Okta Amazon AWS URL like this:

```
SAML2AWS_USERNAME=your_Okta_username SAML2AWS_PASSWORD=your_Okta_password okta_url=your_Okta_amazon_aws_url ./saml2aws_configure.sh
```

This will create a `~/.saml2aws` file with sane defaults and DUO MFA.

### saml2aws_login.sh

Run this script daily to log you into all possible combinations of AWS account and role, and create AWS Profiles for each of them with the naming scheme `${account}_${role}`.

## Deprecated

### aws_configure_all_sso.sh (Deprecated)

> Deprecated: Use [aws-sso-cli](https://github.com/synfinatic/aws-sso-cli) instead.

This configures all of your AWS IAM Identity Center (SSO) account and role combinations, so you don't have to loop through `aws configure sso` dozens of times, or copy-paste a bunch of junk in your ~/.aws/config. Here is example usage:

```
[evans@archlinux ~]$ ./aws_configure_all_sso.sh

ERROR: You must specify your start URL prefix and region like this:

./aws_configure_all_sso.sh start_url_prefix aws_region

Example:

./aws_configure_all_sso.sh mycompany us-west-2

[evans@archlinux ~]$ ./aws_configure_all_sso.sh mycompany us-west-2
Warning: Input is not a terminal (fd=0).
SSO session name: mycompany
SSO start URL [None]: https://mycompany.awsapps.com/start
SSO region [None]: us-west-2
SSO registration scopes [sso:account:]: sso:account:

Completed configuring SSO session: mycompany
Run the following to login and refresh  token for this session:

aws sso login --sso-session mycompany
Attempting to automatically open the SSO authorization page in your default browser.
If the browser does not open or you wish to use a different device to authorize this request, open the following URL:

https://device.sso.us-west-2.amazonaws.com/

Then enter the code:

FQNH-MVQL
Successfully logged into Start URL: https://mycompany.awsapps.com/start
Added mycompany_sandbox_SuperAdmin
Added mycompany_cool-new-product-dev_Admin
Added mycompany_cool-new-product-test_PowerUser
Added mycompany_cool-new-product-prod_ReadOnly
Added mycompany_special_snowflake_client-dev_Admin
Added mycompany_special_snowflake_client-test_PowerUser
Added mycompany_special_snowflake_client-stage_ReadOnly
Added mycompany_special_snowflake_client-prod_ReadOnly
```
