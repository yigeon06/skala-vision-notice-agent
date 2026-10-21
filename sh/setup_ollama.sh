#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

VISION_MODEL="${OLLAMA_VISION_MODEL:-qwen3-vl:4b-instruct}"
EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-bge-m3}"

command -v ollama >/dev/null 2>&1 \
  || { echo "ERROR: Ollama를 먼저 설치하세요: https://ollama.com"; exit 1; }

if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama 서버를 시작합니다..."
  nohup ollama serve >/tmp/notice_schedule_ollama.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
  || { echo "ERROR: Ollama 서버를 시작하지 못했습니다."; exit 1; }

if ollama list | grep "^${VISION_MODEL}" >/dev/null; then
  echo "이미 설치됨: $VISION_MODEL"
else
  echo "모델을 받습니다: $VISION_MODEL"
  ollama pull "$VISION_MODEL"
fi

if ollama list | grep "^${EMBEDDING_MODEL}" >/dev/null; then
  echo "이미 설치됨: $EMBEDDING_MODEL"
else
  echo "모델을 받습니다: $EMBEDDING_MODEL"
  ollama pull "$EMBEDDING_MODEL"
fi

echo "준비 완료: $VISION_MODEL, $EMBEDDING_MODEL"
