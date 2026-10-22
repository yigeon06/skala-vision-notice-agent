#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[ -x ".venv/bin/python3" ] \
  || { echo "ERROR: 먼저 'bash sh/setup_venv.sh'를 실행하세요."; exit 1; }

.venv/bin/python3 -c "import openai" 2>/dev/null \
  || { echo "ERROR: OpenAI SDK가 없습니다 — 'bash sh/setup_venv.sh'를 다시 실행하세요."; exit 1; }

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

TRACING_ENABLED="${LANGSMITH_TRACING:-${LANGCHAIN_TRACING_V2:-false}}"
if [ "$TRACING_ENABLED" = "true" ]; then
  LANGSMITH_KEY="${LANGSMITH_API_KEY:-${LANGCHAIN_API_KEY:-}}"
  if [ -z "$LANGSMITH_KEY" ] || [ "$LANGSMITH_KEY" = "lsv2_pt_..." ]; then
    echo "ERROR: LangSmith 추적을 켜려면 .env에 실제 API 키를 설정하세요."
    exit 1
  fi
  export LANGSMITH_API_KEY="$LANGSMITH_KEY"
  export LANGSMITH_TRACING=true LANGCHAIN_TRACING_V2=true
  export LANGSMITH_HIDE_INPUTS=true LANGSMITH_HIDE_OUTPUTS=true
  export LANGSMITH_PROJECT="${LANGSMITH_PROJECT:-${LANGCHAIN_PROJECT:-notice-schedule-agent}}"
fi

VISION_MODEL="${OLLAMA_VISION_MODEL:-qwen3-vl:4b-instruct}"
EMBEDDING_PROVIDER="${EMBEDDING_PROVIDER:-ollama}"
EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-bge-m3}"

if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama 서버를 시작합니다..."
  nohup ollama serve >/tmp/notice_schedule_ollama.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

ollama list | grep "^${VISION_MODEL}" >/dev/null \
  || { echo "ERROR: $VISION_MODEL 미설치 — bash sh/setup_ollama.sh를 실행하세요."; exit 1; }

if [ "$EMBEDDING_PROVIDER" = "ollama" ]; then
  ollama list | grep "^${EMBEDDING_MODEL}" >/dev/null \
    || { echo "ERROR: $EMBEDDING_MODEL 미설치 — bash sh/setup_ollama.sh를 실행하세요."; exit 1; }
fi

echo "공지·일정 API: http://127.0.0.1:8100"
echo "Vision: $VISION_MODEL / num_ctx=${OLLAMA_VISION_NUM_CTX:-16384}"
echo "Embedding: $EMBEDDING_PROVIDER / $EMBEDDING_MODEL"
echo "LangSmith: $TRACING_ENABLED"
echo "종료: Ctrl+C"

exec .venv/bin/python3 server.py
