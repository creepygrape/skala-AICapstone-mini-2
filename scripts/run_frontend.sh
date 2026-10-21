#!/usr/bin/env bash
# Start the Vue dev server on :5173 (proxies /api to the backend on :8000).
# If port 5173 is already in use, the process holding it is stopped first.
# Open http://localhost:5173/ (not 127.0.0.1: some embedded videos refuse that origin).
set -euo pipefail
cd "$(dirname "$0")/.."

source scripts/_free_port.sh
[ -d frontend/node_modules ] || npm --prefix frontend ci
free_port 5173
echo "Frontend: http://localhost:5173/  (backend expected on http://127.0.0.1:8000)"
exec npm --prefix frontend run dev -- --port 5173 --strictPort
