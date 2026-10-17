#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv-linux/bin/python ]]; then
  echo '缺少 Linux 虚拟环境，请先按 README 的 WSL 安装步骤执行 uv sync。' >&2
  exit 1
fi
exec .venv-linux/bin/python -m robotics_lab serve --port "${1:-8000}"
