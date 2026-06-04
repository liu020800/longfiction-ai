#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Starting LongFiction-AI in the current WSL terminal..."
echo "Keep this terminal window open while you use the app."
bash "${ROOT_DIR}/scripts/run_server_foreground.sh"
