#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo '请先安装 Docker Engine 或 Docker Desktop。' >&2; exit 1; }
engine=$(docker info --format '{{.OSType}}')
[[ "$engine" == linux ]] || { echo '请将 Docker 切换为 Linux 容器。' >&2; exit 1; }
docker compose version >/dev/null
compose_args=(-f compose.yaml)
if [[ -f compose.build.yaml ]]; then compose_args+=(-f compose.build.yaml); fi
case "${1:-up}" in
  up)
    docker compose "${compose_args[@]}" up -d --wait --wait-timeout 120
    address=$(docker compose "${compose_args[@]}" port web 8080)
    printf 'Robotics Lab: http://%s\n' "$address"
    ;;
  build) docker compose "${compose_args[@]}" build ;;
  load) docker image load -i images.tar ;;
  stop) docker compose "${compose_args[@]}" down ;;
  logs) docker compose "${compose_args[@]}" logs --tail 100 -f ;;
  status) docker compose "${compose_args[@]}" ps ;;
  *) echo '用法: bash run-docker.sh [up|build|load|stop|logs|status]' >&2; exit 2 ;;
esac
