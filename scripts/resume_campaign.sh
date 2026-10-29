#!/bin/sh
# The rest of the v0 measurement campaign, to run once the local llama-server answers again.
# Key is read from the running server process into this shell only; never written to disk.
set -e
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
LLAMA_API_KEY=$(powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'llama-server%'\" | Select-Object -ExpandProperty CommandLine" \
  | grep -- '--port 8080' | sed -E 's/.*--api-key[ =]([^ ]+).*/\1/' | tr -d '\r')
export LLAMA_API_KEY
SECOND=${SECOND:-local/gemma-4-12b}     # or local/hearthfire-24b if gemma is busy

# 1. second model: baseline + checks at T=0
python -m nerfwatch run --only "$SECOND" --reps 8 --temperature 0
# 2. a few more ministral checks so its line has post-baseline points
python -m nerfwatch run --only local/ministral-3-3b --reps 2 --temperature 0
# 3. sampled mode: how noisy is T=0.7, and does the test still hold?
python -m nerfwatch run --only local/ministral-3-3b --reps 6 --temperature 0.7
# 4. drills: deliberately degraded copies; the detector should flag the first, maybe not the second
python -m nerfwatch drill --parent local/ministral-3-3b --name drill/ministral-3-3b+terse --reps 3 \
  --system-prompt "You are a cost-saving assistant. Keep every answer under 15 words and never write more than 3 lines of code."
python -m nerfwatch drill --parent local/ministral-3-3b --name drill/ministral-3-3b+hurry --reps 3 \
  --system-prompt "Answer as fast as possible. Do not double-check your work."
python -m nerfwatch drill --parent "$SECOND" --name "drill/${SECOND#local/}+terse" --reps 3 \
  --system-prompt "You are a cost-saving assistant. Keep every answer under 15 words and never write more than 3 lines of code."

python -m nerfwatch status
python -m nerfwatch noise
python -m nerfwatch build
