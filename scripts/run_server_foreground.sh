#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${ROOT_DIR}/server.pid"
OUT_LOG="${ROOT_DIR}/server.out.log"
ERR_LOG="${ROOT_DIR}/server.err.log"

cleanup() {
  rm -f "${PID_FILE}"
}

trap cleanup EXIT

if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
  echo "LongFiction-AI is already running."
  echo "URL: $(bash "${ROOT_DIR}/scripts/get_server_url.sh")"
  exit 0
fi

cd "${ROOT_DIR}"
printf '\n[%s] Starting LongFiction-AI\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "${OUT_LOG}"
python3 main.py >> "${OUT_LOG}" 2>> "${ERR_LOG}" &
server_pid="$!"
echo "${server_pid}" > "${PID_FILE}"
echo "LongFiction-AI server window is active."
echo "URL: $(bash "${ROOT_DIR}/scripts/get_server_url.sh")"
wait "${server_pid}"
