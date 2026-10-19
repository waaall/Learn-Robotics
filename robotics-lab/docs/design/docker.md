# Docker 单服务构建与发布

日期：2026-10-19。容器与原生部署使用同一个 FastAPI 应用、同源查看器网关和组件/服务验收命令。应用结构见 [统一部署设计](deployment.md)。当前课程为 Panda、人形机器人和基础物理，共三门、十四节；部署不固定课程数量。

## 镜像与 Compose

`Dockerfile` 包含四个阶段：

1. `frontend`：在构建机架构的 Node 镜像中执行 `npm ci` 和 TypeScript/Vite 构建。
2. `dependencies`：从 `uv.lock` 导出的带哈希清单安装目标架构 Python 依赖，只接受预编译 wheel。
3. `verifier`：运行全部测试，并执行 `python -m robotics_lab doctor`，失败时中止镜像构建。
4. `runtime`：复制运行依赖、经过 verifier 的应用源码和前端静态资源，不包含 Node、测试源码、构建工具或另一套代理服务。

最终镜像名为 `robotics-lab:<标签>`，适用 `linux/amd64` 和 `linux/arm64`。基础镜像固定到多架构 manifest 摘要，MuJoCo 固定为 3.16.0。Docker 内部 Python 版本为 3.12。

`compose.yaml` 只定义 `lab` 服务。默认仅发布宿主机 `127.0.0.1:18320` 到容器 `8000`；官方查看器使用未公开的动态回环端口。页面、API、WASM、模型和 WebSocket 共用应用端口，无需 Nginx 和固定查看器端口。

源码构建时叠加 `compose.build.yaml`，离线包只包含不要求构建上下文的 `compose.yaml`。运行配置设置 `pull_policy: never`，要求先构建或导入镜像，避免启动时访问未发布的默认仓库：

```shell
docker compose -f compose.yaml -f compose.build.yaml build
docker compose up -d --wait --remove-orphans
```

运行时使用 UID/GID `10001:10001`、只读根文件系统、`/tmp` tmpfs、`init`、capabilities 清空与禁止权限提升。`/var/lib/robotics-lab` 使用持久命名卷；默认卷仍名为项目下的 `robotics-lab-data`，停止或替换容器不删除数据。容器内应用的网络和数据目录由 Dockerfile 指定，宿主机 `.env` 只调整发布地址、端口和镜像标签。

## 依赖与多架构构建

Python 依赖变化后，由同一锁文件生成 Docker 安装清单：

```shell
uv lock
uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file requirements.lock
```

没有单独的测试依赖锁文件；HTTPX 是同源网关的运行依赖。构建阶段测试和运行阶段读取同一套已锁定依赖。

单架构本地构建与发布：

```shell
docker buildx build --platform linux/arm64 --load -t robotics-lab:0.1.0 .
uv run --no-project --python 3.12 tools/package_release.py --arch arm64
```

AMD64 将上述架构改为 `amd64`。发布到镜像仓库时使用实际仓库地址替换示例地址：

```shell
docker buildx build --platform linux/amd64,linux/arm64 --push -t registry.example.com/robotics-lab:0.1.0 .
```

多架构构建使用具备对应节点或模拟能力的 Buildx 构建器，不自动安装 QEMU。模拟环境验证与对应硬件实测分别记录。[Docker 多架构构建](https://docs.docker.com/build/building/multi-platform/)、[Compose 文件叠加](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/)。

## 离线包与运行验收

打包工具使用 Python 3.12，并要求 Docker API 1.48+（Docker Engine 28+），以按架构导出镜像。[官方 save 平台参数](https://docs.docker.com/reference/cli/docker/image/save/#save-a-specific-platform---platform)。

`tools/package_release.py` 按目标架构导出一个应用镜像，复制 Compose、配置示例、冻结标签的 `.env` 和交付文档，计算逐文件 SHA-256，并生成 ZIP 及归档 SHA-256。包内没有平台专属启动脚本；Windows PowerShell、Linux 与 macOS 使用相同 Docker CLI 命令。

```shell
docker compose exec lab python -m robotics_lab doctor
docker compose exec lab python -m robotics_lab smoke
```

健康检查只确认 API 存活，不能证明浏览器渲染成功。`smoke` 检查真实查看器协议与课程控制，浏览器仍需验证父页面及 iframe 的 `crossOriginIsolated` 和实际三维内容。数据备份与恢复见 [交付与迁移](../deployment/quick-start.md)，实际验证状态见 [跨平台验证记录](../validation/deployment.md)。
