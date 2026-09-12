#!/usr/bin/env bash
# Runs the Claude Code agent, sandboxed:
#   - no direct internet route at all — its only way out is through the
#     proxy container, which allow-lists a small, specific set of hosts
#     (see proxy/squid.conf)
#   - read-only container filesystem, no capabilities, no privilege escalation
#   - sees only this project folder, plus a separate small volume just for
#     its own login/session so you're not re-authenticating every run
#   - capped at 2GB memory, 2 CPUs, 200 processes
#   - thrown away when you exit (--rm) — always a clean slate next time
#
# The calculator's own dev/test container (run-dev.sh) is untouched by any
# of this — it stays fully offline, on its own, unrelated to this one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

NET=claude2-agent-net
PROXY_IMG=claude2-proxy
PROXY_NAME=claude2-proxy
AGENT_IMG=claude2-agent
CONFIG_VOL=claude2-agent-config

# 1. The private, internal-only network (no route to the real internet).
#    Both the agent and the proxy join this; the agent joins ONLY this.
if ! podman network exists "$NET"; then
    echo "Creating internal network $NET..."
    podman network create --internal "$NET"
fi

# 2. Build the proxy image if it doesn't exist yet.
if ! podman image exists "$PROXY_IMG"; then
    echo "Building proxy image..."
    podman build -t "$PROXY_IMG" ./proxy
fi

# 3. Make sure the proxy container is up. It's dual-homed: the internal
#    network (to talk to the agent) AND the normal default network (to
#    actually reach the internet). This is the ONLY container here with
#    real internet access.
if ! podman container exists "$PROXY_NAME" || \
   [[ "$(podman inspect -f '{{.State.Running}}' "$PROXY_NAME" 2>/dev/null)" != "true" ]]; then
    echo "Starting proxy container..."
    podman rm -f "$PROXY_NAME" >/dev/null 2>&1 || true
    podman run -d --name "$PROXY_NAME" \
      --network "$NET",podman \
      --dns 9.9.9.9 --dns 149.112.112.112 \
      --read-only \
      --tmpfs /run:rw,mode=1777 \
      --tmpfs /var/log/squid:rw,mode=1777 \
      --tmpfs /var/spool/squid:rw,mode=1777 \
      --cap-drop=ALL \
      --security-opt no-new-privileges \
      --memory=256m --cpus=0.5 --pids-limit=50 \
      "$PROXY_IMG"
fi

# 4. A small persistent volume just for the agent's own config/session —
#    deliberately separate from the project folder mount below, so login
#    data never mixes with or gets exposed through your project code.
if ! podman volume exists "$CONFIG_VOL"; then
    podman volume create "$CONFIG_VOL"
fi

# 5. Build the agent image if it doesn't exist yet.
if ! podman image exists "$AGENT_IMG"; then
    echo "Building agent image..."
    podman build -t "$AGENT_IMG" -f Containerfile.agent .
fi

# 6. Run the agent — internal network ONLY (no direct internet route),
#    routed through the proxy by container name (resolvable since both
#    are on the shared internal network).
podman run --rm -it \
  --network "$NET" \
  --read-only \
  --tmpfs /tmp \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=2g --cpus=2 --pids-limit=200 \
  -e HTTP_PROXY="http://${PROXY_NAME}:3128" \
  -e HTTPS_PROXY="http://${PROXY_NAME}:3128" \
  -e NO_PROXY="localhost,127.0.0.1" \
  -v "$(pwd)":/home/appuser/app:Z \
  -v "$CONFIG_VOL":/home/appuser/.claude:Z \
  -w /home/appuser/app \
  "$AGENT_IMG"
