# Docker 发布设计

日期：2026-10-17。部署以当前单用户课程实验为目标，保留两个课程、九节课及原有源码启动方式。

## 服务与资源

Compose 包含两个长期服务。`web` 为 React 静态页面和 Nginx，监听容器 8080，默认发布到宿主机 `127.0.0.1:18320`；`api` 为 Python/FastAPI，监听容器 8000，并管理一个 MuJoCo WebViewer 子进程，其容器内部端口固定为 8081。API 和查看器都没有宿主机端口映射。

Nginx 的 `/api/` 转发 API，`/viewer/` 提供官方客户端。官方客户端保留根路径 `/model`、`/ui`、`/state`、`/drop`、`/assets/`，Nginx 将它们转发给查看器；课程页面的构建资源改用 `/lab-assets/`，避免资源路径冲突。没有修改上游 WASM 二进制或引入自制三维渲染器。

代理支持 WebSocket Upgrade，保留模型和 UI 数据流；顶层页面、iframe 和查看器响应提供 COOP/COEP，支持官方 WASM pthread/SharedArrayBuffer。远程使用 HTTPS，本机 localhost 使用 HTTP。Docker 内部 DNS 动态解析 API 地址，支持后端容器重建。[Nginx WebSocket 代理](https://nginx.org/en/docs/http/websocket.html)、[MuJoCo 3.16.0 查看器服务](https://github.com/google-deepmind/mujoco/blob/3.16.0/python/mujoco/experimental/studio/web/web_server.py)

`ROBOTICS_LAB_VIEWER_PORT` 与 `ROBOTICS_LAB_VIEWER_URL` 由容器配置；源码模式未配置时仍使用动态端口和直接访问。数值计算、课程模型和控制器接口保持原有职责。容器入口直接执行 Linux Python，不依赖宿主机 shell、Python、Node.js 或已有 WSL 虚拟环境。

## 构建与发布

API 镜像分为 `dependencies`、`verifier`、`runtime`。依赖采用 `uv.lock` 导出的带哈希清单；verifier 运行全部单元测试并确认官方 WebViewer 原生模块和客户端资源齐全；最终镜像从干净运行依赖阶段复制环境，并从 verifier 复制已验证的源码。最终镜像不包含测试依赖和构建工具。课程、Panda 网格与许可证随镜像发布。

Web 在 Node 构建阶段完成 TypeScript 检查与 Vite 构建，最终镜像只保留 Nginx 与静态资源。前端构建阶段使用构建机架构，最终 Nginx 使用目标架构。

构建命令：

```bash
docker compose -f compose.yaml -f compose.build.yaml build
docker compose up -d --wait
```

依赖更新后重新生成清单，不手工编辑导出文件：

```bash
uv lock
uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file requirements.lock
uv export --locked --no-dev --extra dev --no-emit-project --format requirements.txt --output-file requirements-test.lock
```

当前交付 AMD64 包。ARM64 包按用户要求留待 macOS 构建和验收。以下为后续多架构发布命令，要求构建器支持对应架构或已配置 QEMU，不表示本次已交付两种包：

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t robotics-lab-api:0.1.0 --load .
docker buildx build --platform linux/amd64,linux/arm64 -t robotics-lab-web:0.1.0 --load ./frontend
python tools/package_release.py --arch amd64
python tools/package_release.py --arch arm64
```

打包脚本按架构导出两个镜像，加入无构建配置的 `compose.yaml`、PowerShell/shell 启动脚本、版本配置、快速开始和包含 SHA-256 的清单，生成 `dist/` 下 ZIP 与校验文件。版本改变时同时调整项目版本、Compose 默认标签和发布参数。当前不采用额外的 Cython 业务模块编译步骤。

## 数据与进程

默认使用 Docker 命名卷，API 以 UID/GID `10001:10001` 写入数值记录和会话日志。首次创建时卷继承镜像目录权限；可切换为已有宿主机目录，目录权限由部署者配置。`ROBOTICS_LAB_DATA_DIR` 在 Compose 中表示宿主机目录，在 API 容器内固定为 `/var/lib/robotics-lab`。

根文件系统只读，临时文件使用 tmpfs，两个服务以非 root 用户运行，移除 capabilities，设置 `init` 和关闭等待时间。API 正常关闭时终止当前查看器；强制结束容器时容器进程一并终止。重启后不自动恢复旧仿真状态，数值记录保留。课程完成状态仍是浏览器 localStorage。

服务固定一个 Uvicorn worker。增加 worker 或容器副本需要重新设计会话归属与调度。健康检查用于服务存活，组件检查用于安装资源验收；真实交互通过 `tools/smoke_docker.py` 和浏览器测试验证，不能仅据 `/api/health` 判断三维实验可用。

当前控制器以小矩阵计算为主，镜像默认设置 `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`，避免为每个仿真进程启动过多计算线程；验证阶段使用相同配置。后续大规模批量实验可单独测量并覆盖环境变量。

## 适用平台

Windows、macOS 在 Linux 虚拟机中运行这些 Linux 容器，Linux 使用本机容器引擎。AMD64 和 ARM64 镜像分别适配 CPU 指令集；Docker 不自动消除架构、浏览器和宿主机虚拟化要求。当前已完成 AMD64 交付，ARM64 的构建配置和包生成参数已准备，完整验收与交付留待 macOS；模拟环境已执行的检查不替代实机验证。[Docker 多架构构建](https://docs.docker.com/build/building/multi-platform/)、[Docker Desktop macOS 安装](https://docs.docker.com/desktop/setup/install/mac-install/)

本次流程参考 `camera_calibration` 的 Web/API 分容器、单端口、分阶段测试和持久数据组织，在 Robotics Lab 内独立维护镜像、依赖、配置和验收；不建立运行或数据依赖。
