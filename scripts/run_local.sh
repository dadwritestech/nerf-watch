#!/bin/sh
# Run the suite against the local llama-server on :8080 (Windows + Git Bash).
# The server was started with --api-key; read it from the running process into an env var
# for this shell only. It is never written to disk.
set -e
cd "$(dirname "$0")/.."
LLAMA_API_KEY=$(powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'llama-server%'\" | Select-Object -ExpandProperty CommandLine" \
  | grep -- '--port 8080' | sed -E 's/.*--api-key[ =]([^ ]+).*/\1/' | tr -d '\r')
export LLAMA_API_KEY
python -m nerfwatch run --include-local "$@"
python -m nerfwatch status
python -m nerfwatch build
