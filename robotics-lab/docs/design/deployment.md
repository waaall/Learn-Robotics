# 统一部署与启动设计

日期：2026-10-19。支持 WSL2/Linux AMD64、ARM64，Apple Silicon macOS 原生部署，以及 Linux AMD64/ARM64 Docker。Windows 完整运行通过 WSL2 或 Docker Desktop；不维护 Windows 原生 Python 和 Intel Mac 原生部署。

## 应用结构

所有部署运行相同的 `python -m robotics_lab serve`：

```text
浏览器 → 应用端口 → FastAPI
                    ├─ /api/*：课程、数值计算、记录与会话
                    ├─ /：构建后的课程页面（/lab-assets/*）
                    └─ ViewerGateway → 127.0.0.1:<动态端口>
                                         └─ 官方 MuJoCo WebViewer 子进程
```

原生默认监听 `127.0.0.1:18320`；Docker 内监听 `0.0.0.0:8000`，默认映射宿主机 `127.0.0.1:18320`。配置解析集中于 `config.py`，不再按操作系统维护应用配置。

`lab.sh` 仅负责环境准备和命令分发，WSL2 按 Linux 处理。Python 环境目录按 `uname` 的系统与架构隔离；相同命令用于全部原生目标。Docker 直接使用 Compose，不另写 Bash/PowerShell 版本的 Docker 操作逻辑。

## 同源查看器网关

`gateway.py` 为全部部署提供相同路由：

| 路径 | 转发内容 |
| --- | --- |
| `/viewer/`、`/viewer/*` | 官方 HTML、JS、WASM |
| `/assets/*` | 官方字体与渲染资源 |
| `/model` | 模型与带查询参数的分块下载 |
| `/ui`、`/state`、`/drop` | 官方双向 WebSocket，保留查询、文本、二进制帧及关闭代码 |

HTTP 使用应用生命周期内复用的 HTTPX AsyncClient，按原始字节流转发，连接在结束或取消时关闭；不缓存整个 WASM 文件。上游普通 HTTP 响应后关闭 TCP，因此禁用闲置连接复用；HEAD 使用对应 GET 的响应头并立即关闭内容流。过滤逐跳响应头及请求凭据，不继承宿主机代理设置。代理目标始终来自当前存活会话的内部回环端口，客户端不能指定任意代理主机。WebSocket 的两个方向任一结束时取消并等待另一个方向。

纯 ASGI 中间件为页面、静态资源、API、错误响应和 WebSocket 握手设置 COOP `same-origin`、COEP `require-corp`。iframe 与父页面同源，不再依赖动态公开端口或跨源 iframe 授权。开发时 Vite 仅转发同一应用的路由，并为自己的顶层页面设置相同隔离头。

依据：[HTTPX 流式响应与关闭要求](https://www.python-httpx.org/async/#streaming-responses)、[websockets asyncio 客户端](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html)、[跨源隔离条件](https://developer.mozilla.org/en-US/docs/Web/API/Window/crossOriginIsolated)。

## MuJoCo 3.16.0 适配

查看器使用固定版本的 `experimental.studio.launch_web`、官方插件与原始 JS/WASM，不引入第二套三维渲染器。`doctor` 核实原生扩展、客户端资源和 Python 导入，不依据操作系统名称推断组件是否齐全。缺件时返回非零退出码。

上游 WebViewer 3.16.0 在构造函数中将 HTTP 地址固定为 `::`，未提供 `ViewerConfig.host`。本项目在查看器子进程的适配入口临时替换 `web_server.bind_public_socket`，委托原工厂以 `127.0.0.1` 创建套接字，退出时恢复。该适配与操作系统无关，仅用于限制内部端口监听地址；升级 MuJoCo 时需复核此处。

依据：[上游启动器](https://github.com/google-deepmind/mujoco/blob/3.16.0/python/mujoco/experimental/studio/launch_web.py)、[固定监听地址实现](https://github.com/google-deepmind/mujoco/blob/3.16.0/python/mujoco/experimental/studio/web_viewer.py)、[套接字工厂与资源协议](https://github.com/google-deepmind/mujoco/blob/3.16.0/python/mujoco/experimental/studio/web/web_server.py)。

## 配置与依赖

- `uv.lock` 是 Python 依赖版本来源；Docker 的带哈希 `requirements.lock` 从同一锁文件导出。
- HTTPX 从测试依赖调整为网关运行依赖，websockets 作为直接运行依赖声明；测试不再维护另一份依赖清单。
- Node 仅用于前端安装与构建，版本由前端锁文件约束；原生和容器运行时均无需 Node。
- 原生和 Docker 都通过 `PYTHONPATH` 直接运行 `src`；原生 `uv sync --no-install-project` 只安装依赖，不依赖可编辑安装的 `.pth`。
- 原生脚本通过 uv 读取可选 `.env`。直接使用 Python 命令时，调用方传入环境变量；应用自身不实现另一套 dotenv 解析器。
- 数据相对路径以项目为基准。原生默认 `.runtime`；Docker 使用 `/var/lib/robotics-lab` 命名卷。数据存储位置、端口和镜像标签在 README 中逐项说明。

## 进程与验证

服务保持一个 Uvicorn worker、一个交互会话。关闭应用时结束查看器并关闭网关 HTTP 连接池；换课时旧进程终止，相关 WebSocket 随之结束。重启不恢复交互仿真内存，已落盘数值记录保留。

验证分为组件检查、单元/协议回归、`smoke` 服务验收和可见浏览器验收。启动脚本测试使用参数记录替身覆盖 Linux AMD64/ARM64、Darwin ARM64 和含空格路径，不将模拟系统名称作为实机验收。

不增加 ROS、训练框架、CUDA、`experiments/` 或其他项目的依赖；Panda、G1 与基础物理课程保持原有模型、控制和数据职责。
