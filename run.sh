#!/usr/bin/env bash
# Runs the app through the venv created by install.sh. Examples:
#
#   ./run.sh elicit
#   ./run.sh report household.toml -o premortem.pdf
#
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python3 ]; then
    echo "No .venv found - run ./install.sh first." >&2
    exit 1
fi

exec .venv/bin/python3 main.py "$@"
