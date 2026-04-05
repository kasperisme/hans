#!/bin/bash
# Hans setup — installs Python deps, creates venv, links `ask` CLI.
# Assumes Ollama is already installed and running.
#
# Usage:
#   bash deploy/setup-mac.sh

set -e

echo "=== Hans Setup ==="

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# --- Python venv ---
if [ ! -d ".venv" ] || [ ! -x ".venv/bin/python" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv --clear
fi

echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# --- Log directory ---
mkdir -p "$HOME/.tiered-agent/logs"

# --- ask CLI symlink ---
mkdir -p "$HOME/bin"
ln -sf "$PROJECT_DIR/router/ask" "$HOME/bin/ask"
chmod +x "$PROJECT_DIR/router/ask"

if ! echo "$PATH" | grep -q "$HOME/bin"; then
  echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.zprofile"
  export PATH="$HOME/bin:$PATH"
fi

# --- .env check ---
if [ ! -f ".env" ]; then
  echo ""
  echo "WARNING: .env not found — copy and edit:"
  echo "  cp .env.example .env && nano .env"
fi

echo ""
echo "=== Setup complete ==="
echo "  ask 'hvad er de seneste picks?'"
echo "  ask --stats"
