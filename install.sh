#!/usr/bin/env bash
# One-time setup: system libraries (for PDF export) + a Python venv with
# the project's dependencies. Run this once from the "app" directory:
#
#   ./install.sh
#
set -euo pipefail
cd "$(dirname "$0")"

# Guard against a copied-in directory (or an already-created .venv) still owned
# by a different uid than the one running this script - e.g. leftover ownership
# from wherever this folder was copied from. python3 -m venv would otherwise
# fail deep inside with a confusing PermissionError traceback.
if [ ! -w . ]; then
    echo "error: no write permission on $(pwd)." >&2
    echo "This directory is owned by $(stat -c '%U (uid %u)' . 2>/dev/null || stat -f '%Su (uid %u)' .), not $(whoami) (uid $(id -u))." >&2
    echo "Fix it, then re-run this script:" >&2
    echo "  sudo chown -R \$(id -u):\$(id -g) $(pwd)" >&2
    exit 1
fi
if [ -e .venv ] && [ ! -w .venv ]; then
    echo "error: .venv exists but isn't writable by $(whoami)." >&2
    echo "Remove it and re-run, or fix ownership:" >&2
    echo "  sudo chown -R \$(id -u):\$(id -g) $(pwd)/.venv" >&2
    exit 1
fi

echo "== Installing system dependencies (Pango/Cairo, needed by WeasyPrint for PDF export) =="
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip \
        libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libffi-dev
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip pango cairo-gobject gdk-pixbuf2 libffi-devel
elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --needed python python-pip pango cairo gdk-pixbuf2 libffi
else
    echo "Warning: unrecognized package manager - install Pango/Cairo manually," >&2
    echo "or PDF export (main.py report ...) will fail at runtime." >&2
fi

echo "== Creating Python virtual environment (.venv) =="
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo
echo "Done. Run the app with ./run.sh, e.g.:"
echo "  ./run.sh elicit"
echo "  ./run.sh report household.toml -o premortem.pdf"
