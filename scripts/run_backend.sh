#!/usr/bin/env bash
# Start the Agent API with one switch: scripts/run_backend.sh [ollama|openai]
#   ollama (default) — local development, no billing
#   openai           — demo/submission, billed per request (asks y/N first)
# Reads .env if present (Uvicorn itself does not).
# If port 8000 is already in use, the process holding it is stopped first.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; source .env; set +a; fi
BACKEND="${1:-${WISH_LLM_BACKEND:-ollama}}"
export WISH_LLM_BACKEND="$BACKEND"
export WISH_AGENT_ENABLED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

source scripts/_free_port.sh

case "$BACKEND" in
    ollama)
        echo "LLM: ollama fast=${WISH_OLLAMA_FAST_MODEL:-${WISH_LLM_MODEL:-qwen3:8b}} quality=${WISH_OLLAMA_QUALITY_MODEL:-${WISH_OLLAMA_FAST_MODEL:-${WISH_LLM_MODEL:-qwen3:8b}}}"
        ;;
    openai)
        if [ -z "${OPENAI_API_KEY:-}" ] || [ "${OPENAI_API_KEY}" = "sk-..." ]; then
            echo "ERROR: OPENAI_API_KEY is empty. Put your key in .env (see .env.example)." >&2
            exit 1
        fi
        echo "LLM: openai fast=${OPENAI_FAST_MODEL:-gpt-4o-mini} quality=${OPENAI_QUALITY_MODEL:-gpt-4o}"
        echo "WARNING: every search calls the OpenAI API and is billed to your account."
        echo "         The question and up to 3 candidate subtitle excerpts (20s context) are sent to OpenAI."
        read -r -p "Continue? [y/N] " answer
        case "$answer" in [yY]|[yY][eE][sS]) ;; *) echo "Aborted."; exit 1 ;; esac
        ;;
    *)
        echo "ERROR: unknown backend '$BACKEND' (use ollama or openai)." >&2
        exit 1
        ;;
esac

free_port 8000
exec .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
