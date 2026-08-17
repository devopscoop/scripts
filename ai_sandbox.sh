#!/usr/bin/env bash
#
# Run Claude Code or OpenCode inside the devopscoop workstation image
# (https://github.com/devopscoop/workstation) as a throwaway agent sandbox.
# The container:
#
#   * runs as YOUR uid/gid, so files the agent writes are owned by you, not root
#   * mounts ONLY the current directory (as /work/<dirname>) and a shared
#     sandbox home (~/.sandbox-home) for agent state -- nothing else
#   * gets no access to ~/.aws, ~/.kube, ~/.ssh, ~/.gnupg, your real ~/.claude,
#     or any other host dir, and no Docker socket
#
# so the agent has the full DevOps toolset but none of your credentials and can
# only touch the project you launch it in.
#
# Usage:
#   ./ai_sandbox.sh                  # Claude Code (default)
#   ./ai_sandbox.sh opencode         # OpenCode
#   ./ai_sandbox.sh claude --resume  # extra args pass through to the agent
#
# Env knobs:
#   IMAGE              image to run (default: ghcr.io/devopscoop/workstation:main-aws)
#   DOCKER             docker invocation       (default: "docker" on macOS,
#                                               "sudo docker" elsewhere; set to
#                                               "docker" for rootless / docker group)
#   SANDBOX_HOME       host dir holding agent state (default: ~/.sandbox-home).
#                      Shared across projects so you authenticate once; point it
#                      at "$PWD/.sandbox-home" to isolate one project instead
#   ANTHROPIC_API_KEY  if set, forwarded into the container (as an env var, not a
#                      mounted file) so Claude Code is authenticated non-interactively
set -Eeuo pipefail

# First positional arg is the agent to run; the rest pass through to it.
AGENT="${1:-claude}"
shift || true

IMAGE="${IMAGE:-ghcr.io/devopscoop/workstation:main-aws}"
# Default the docker invocation per OS. On macOS (Docker engine via colima) the
# socket is user-owned, and `sudo docker` would actively break -- root's docker
# CLI has no colima context. On Linux the socket is root-owned unless you run
# rootless or are in the docker group, so default to sudo there.
if [[ -z "${DOCKER:-}" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    DOCKER="docker"
  else
    DOCKER="sudo docker"
  fi
fi

# Agent state (auth, config, history) lives in ONE shared host directory,
# mounted as the container HOME, so you authenticate once and every project
# reuses it. It is deliberately NOT your real ~/.claude: the sandbox must never
# see or write your laptop's config (sandbox settings hooks would run on the
# host), and on macOS the OAuth token lives in the Keychain anyway, so mounting
# the real config wouldn't log the container in. Trade-off of sharing: an agent
# in one project can read state another project's agent left here. Created on
# the host so it is owned by you and the non-root container user can write to it.
SANDBOX_HOME="${SANDBOX_HOME:-${HOME}/.sandbox-home}"
mkdir -p "${SANDBOX_HOME}"

# Mount the project under its own name rather than a fixed /work: with a shared
# HOME, Claude Code keys per-project state (trust, history, --resume) on the
# path, and a fixed /work would collapse every project onto one key.
PROJECT="$(basename "${PWD}")"

exec ${DOCKER} run --rm -it \
  --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges \
  -v "${SANDBOX_HOME}:/sandbox-home" \
  -v "${PWD}:/work/${PROJECT}" \
  -w "/work/${PROJECT}" \
  -e HOME=/sandbox-home \
  -e USER="$(id -un)" \
  ${ANTHROPIC_API_KEY:+-e ANTHROPIC_API_KEY} \
  "${IMAGE}" \
  "${AGENT}" "$@"
