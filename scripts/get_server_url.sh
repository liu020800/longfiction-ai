#!/usr/bin/env bash
set -euo pipefail

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

if [[ -z "${ip}" ]]; then
  echo "http://127.0.0.1:8000/"
  exit 0
fi

echo "http://${ip}:8000/"
