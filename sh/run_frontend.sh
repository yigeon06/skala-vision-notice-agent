#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"

[ -d node_modules ] \
  || { echo "ERROR: frontend에서 먼저 'npm install'을 실행하세요."; exit 1; }

exec npm run dev
