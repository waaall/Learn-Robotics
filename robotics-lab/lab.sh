#!/usr/bin/env bash
# WSL2、Linux 与 Apple Silicon macOS 共用的原生环境安装与前台启动入口。
set -euo pipefail
cd "$(dirname "$0")"

system=$(uname -s)
machine=$(uname -m)
case "$system:$machine" in
  Linux:x86_64|Linux:aarch64|Linux:arm64|Darwin:arm64) ;;
  *) echo "原生部署不支持 $system/$machine；请使用 Linux AMD64/ARM64 Docker。" >&2; exit 1 ;;
esac
command -v uv >/dev/null || { echo '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }

# 环境按操作系统和架构隔离；缓存与下载的 Python 均保存在项目忽略目录。
export UV_PROJECT_ENVIRONMENT="$PWD/.venv/$system-$machine"
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.cache/python"
# 原生与容器都直接运行 src，避免依赖可编辑安装的 .pth 注册及文件隐藏属性。
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
uv_args=(run --locked --no-sync)
if [[ -f .env ]]; then uv_args+=(--env-file .env); fi

action="${1:-start}"
if [[ $# -gt 0 ]]; then shift; fi
case "$action" in
  setup)
    command -v npm >/dev/null || { echo '请先安装 Node.js 22.12+（推荐 24 LTS）。' >&2; exit 1; }
    uv sync --locked --no-install-project --python 3.12
    npm ci --prefix frontend --cache "$PWD/.cache/npm" --no-audit --no-fund
    npm run build --prefix frontend
    exec uv "${uv_args[@]}" python -m robotics_lab doctor
    ;;
  start|doctor|test|smoke)
    [[ -x "$UV_PROJECT_ENVIRONMENT/bin/python" ]] || { echo '缺少本平台虚拟环境，请先执行 bash lab.sh setup。' >&2; exit 1; }
    case "$action" in
      start)
        [[ -f frontend/dist/index.html ]] || { echo '前端尚未构建，请先执行 bash lab.sh setup。' >&2; exit 1; }
        exec uv "${uv_args[@]}" python -m robotics_lab serve "$@"
        ;;
      doctor) exec uv "${uv_args[@]}" python -m robotics_lab doctor "$@" ;;
      test) exec uv "${uv_args[@]}" python -m unittest discover -s tests -v "$@" ;;
      smoke) exec uv "${uv_args[@]}" python -m robotics_lab smoke "$@" ;;
    esac
    ;;
  *) echo '用法: bash lab.sh [setup|start [--host HOST --port PORT]|doctor|test|smoke [--url URL]]' >&2; exit 2 ;;
esac
