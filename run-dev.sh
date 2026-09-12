#!/usr/bin/env bash
# Runs the claude2-dev container, locked down:
#   - no network, no elevated privileges, read-only container filesystem
#   - sees only this project folder (SELinux-labeled correctly for Enforcing mode)
#   - capped at 1GB memory, 1 CPU, 100 processes
#   - thrown away when you exit (--rm) — always a clean slate next time
#
# If you've added a new dependency to requirements.txt, rebuild first:
#   podman build -t claude2-dev .
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

podman run \
  --rm \
  -it \
  --network=none \
  --read-only \
  --tmpfs /tmp \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=1g --cpus=1 --pids-limit=100 \
  -v "$(pwd)":/home/appuser/app:Z \
  -w /home/appuser/app \
  claude2-dev
