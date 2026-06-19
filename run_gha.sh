#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1
export PYTHONUNBUFFERED=${PYTHONUNBUFFERED:-1}
if [[ ! -f "libs/ZIRC/src/core/gflzirc/__init__.py" ]]; then
  echo "[错误] 未检测到内置 gflzirc：libs/ZIRC/src/core/gflzirc/__init__.py" >&2
  exit 1
fi
if [[ ! -f ".env" ]]; then
  echo "[提示] 未找到 .env。请先复制 examples/gha.env.example 为 .env 并填写 UID/SIGN。" >&2
fi
python3 gfam_gha.py "$@"
