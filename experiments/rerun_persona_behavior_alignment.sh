#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${PYTHON_BIN:-}" && -x "/tmp/projectdut-openai-venv/bin/python" ]]; then
  PYTHON_BIN="/tmp/projectdut-openai-venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
DB_PATH="${PERSONA_ALIGNMENT_DB:-experiments/cafe-live-100x3-20260928.sqlite}"
RUN_ID="${PERSONA_ALIGNMENT_RUN_ID:-run_cafe_100x3_live_20260928}"
SESSION_NO="${PERSONA_ALIGNMENT_SESSION_NO:-1}"
OUTPUT_PATH="${PERSONA_ALIGNMENT_OUTPUT:-experiments/persona-alignment-cog-attention-span-session-1.json}"

RESUME_FLAG=()
if [[ "${1:-}" == "--resume" ]]; then
  RESUME_FLAG=(--resume)
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--resume]" >&2
  exit 2
fi

"$PYTHON_BIN" -m paper_research.benchmark_persona_behavior_alignment_llm \
  --self-check

"$PYTHON_BIN" -m paper_research.benchmark_persona_behavior_alignment_llm \
  --db "$DB_PATH" \
  --run-id "$RUN_ID" \
  --session-no "$SESSION_NO" \
  --live \
  "${RESUME_FLAG[@]}" \
  --output "$OUTPUT_PATH"
