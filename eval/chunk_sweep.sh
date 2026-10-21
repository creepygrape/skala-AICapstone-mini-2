#!/usr/bin/env bash
# Compare chunk window/stride on the same gold set (A/B only: no LLM, no billing).
# Run where eval/private/gold.jsonl and its approval file exist. Each new setting builds its own dense
# index (a few minutes on CPU, cached under data/index/ afterwards).
#
#   eval/chunk_sweep.sh                                   # default dataset, Korean first queries
#   eval/chunk_sweep.sh "--dataset eval/private/gold.jsonl --rewrites eval/private/gold.rewrites.json"
#
# Results: eval/private/chunk-<window>-<stride>.json (existing files are never overwritten).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe
EXTRA="${1:---dataset eval/private/gold.jsonl --systems A,B}"
SETTINGS="${CHUNK_SETTINGS:-10:5 20:10 30:15 40:20}"      # window:stride (20:10 is the current default)
for setting in $SETTINGS; do
    window="${setting%%:*}"; stride="${setting##*:}"
    echo "== window=${window}s stride=${stride}s"
    WISH_CHUNK_WINDOW="$window" WISH_CHUNK_STRIDE="$stride" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUTF8=1 \
        "$PY" -m eval.run_eval $EXTRA --output "eval/private/chunk-${window}-${stride}.json"
done
