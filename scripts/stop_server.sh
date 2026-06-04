#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${ROOT_DIR}/server.pid"
PORT="8000"

find_port_pid() {
  ss -ltnp 2>/dev/null | sed -n "s/.*:${PORT} .*pid=\\([0-9]\\+\\).*/\\1/p" | head -n 1
}

stopped="0"

if [[ -f "${PID_FILE}" ]]; then
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "${pid}" 2>/dev/null; then
        stopped="1"
        break
      fi
      sleep 1
    done
    if [[ "${stopped}" != "1" ]]; then
      kill -9 "${pid}" 2>/dev/null || true
      stopped="1"
    fi
  fi
  rm -f "${PID_FILE}"
fi

port_pid="$(find_port_pid || true)"
if [[ -n "${port_pid}" ]]; then
  kill "${port_pid}" 2>/dev/null || true
  sleep 1
  if kill -0 "${port_pid}" 2>/dev/null; then
    kill -9 "${port_pid}" 2>/dev/null || true
  fi
  stopped="1"
fi

if [[ "${stopped}" == "1" ]]; then
  echo "LongFiction-AI has been stopped."
else
  echo "LongFiction-AI is not running."
fi
