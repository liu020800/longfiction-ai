#!/usr/bin/env bash
set -euo pipefail

PORT="8000"

if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "STATUS: running"
  echo "URL: $(bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/get_server_url.sh")"
  exit 0
fi

echo "STATUS: stopped"
exit 1
