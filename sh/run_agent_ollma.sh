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

VISION_MODEL="${OLLAMA_VISION_MODEL:-qwen3-vl:4b-instruct}"

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

echo "공지·일정 API: http://127.0.0.1:8100"
echo "Vision: $VISION_MODEL / num_ctx=${OLLAMA_VISION_NUM_CTX:-16384}"
echo "종료: Ctrl+C"

exec .venv/bin/python3 server.py
