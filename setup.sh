#!/usr/bin/env bash
# Create the project virtual environment and install dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f config/.env ]]; then
  cp config/.env.example config/.env
  echo "Created config/.env from config/.env.example"
else
  echo "config/.env already exists; leaving it unchanged"
fi

echo "Setup complete. Start with:"
echo "  ./run.sh              # Flask development server (foreground)"
echo "  ./start_server.sh     # Gunicorn (background)"
echo "  ./stop_server.sh      # stop Gunicorn"
