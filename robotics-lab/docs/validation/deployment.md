# 跨平台部署验证记录

日期：2026-10-19。对象为本次统一单端口、单服务部署；不将旧双容器记录或模拟系统名称作为新版本实机验证。

## 环境与目标

- 宿主机：macOS 27.0.1，ARM64；Python 3.12.11，uv 0.13.0，Node.js 26.7.0、npm 11.19.0。
- 仿真：MuJoCo 3.16.0，NumPy 2.5.4；使用项目锁定依赖与随源码提供的模型、策略。
- 浏览器：可见 Playwright Chromium 145.0.7632.6，实际加载官方 WASM、模型、材质及 UI。
- Docker：Docker Desktop，Engine/CLI 29.5.3、Compose 5.1.4，Linux ARM64 引擎；AMD64 构建和运行使用 Docker Desktop 自带的跨架构模拟能力，不作为 AMD64 实体硬件测试。

| 目标 | 验证状态 |
| --- | --- |
| Apple Silicon macOS 原生 | 安装、组件检查、53 项测试、服务协议与浏览器交互通过 |
| Linux ARM64 Docker | 镜像构建、53 项测试、组件检查、连续两轮服务验收与浏览器渲染通过 |
| Linux AMD64 Docker | 最终多架构镜像构建、53 项测试和四种查看器服务协议验收通过（模拟运行） |
| WSL2/Linux 原生 | 共用脚本参数测试通过；本次无对应宿主机，尚未实机复验 |
| Windows Docker Desktop | Compose 无平台专属脚本；本次无 Windows 宿主机，尚未实机复验 |
| Safari、Firefox | 本次未验收 |

WSL1、Windows 原生 Python 和 Intel Mac 原生运行不属于部署目标。

## 共享回归与服务协议

- 53 项测试覆盖原有 Panda、G1、基础物理、API 与会话控制，并增加配置、同源响应头、HTTP 字节流/长度/查询/MIME/HEAD、WebSocket 文本与二进制、上游关闭代码和无会话拒绝。
- Bash 入口使用记录参数的工具替身，验证 Linux x86_64、Linux aarch64、Darwin arm64 的安装命令一致；环境目录按平台隔离；包含空格的路径和启动参数正常。该测试不运行对应平台二进制。
- 原生与 Docker 共用 `python -m robotics_lab smoke`。从三门、十四节课程目录中解析实验，不在验收脚本固定课程数量。
- 服务验收实际打开单摆、落球、Panda 结构和 G1 结构四种查看器，读取完整 WASM 并检查长度与签名、下载模型分块、接收二进制 WebSocket 状态。
- Panda 与 G1 暂停后单步增量分别对应各自运行记录的模型时间步长，恢复初态后时间为零；结束后会话为空。独立数值记录可以从 API 读回。
- ARM64 Docker 对最终短连接/模型就绪修复连续执行两轮协议验收，均通过；最终 AMD64 镜像也完成相同四种查看器协议验收。
- 同一 `robotics-lab:0.1.0` 标签已实际构建并导入 ARM64/AMD64 manifest，按架构检查成功。模拟 AMD64 时显式指定目标平台，并使用本地构建镜像。
- 原生服务重启、ARM64 容器重建后，原数值记录均能通过 API 读取。原生实际查看器的两个 TCP 监听均为 `127.0.0.1`，正常结束父应用后查看器子进程清理通过。

## 实际浏览器交互

原生生产页面、Vite 开发页面与 Docker ARM64 页面均完成：

1. 父页面 `crossOriginIsolated` 为 `true`；iframe 地址与页面同源，其隔离状态为 `true`。
2. 官方客户端完成 WASM 初始化，实际渲染 Panda 网格、G1 网格、地面和官方操作 UI。
3. Panda 暂停后单步增加约 0.001 s；通过网页结束实验。
4. 切换到 G1 学习策略行走课，启动 NumPy LSTM 策略，观测到基座位移，采样时 `policy_active=true`、`fallen=false`。
5. 两类实验结束后服务无残留会话，正常测试过程的页面脚本错误与控制台错误列表为空。

G1 的短时位移仅用于确认策略执行和交互链路，不作为长时行走稳定性基准。原有控制与策略数值回归另由 53 项测试覆盖。

## 验收中发现的实现问题

- 查看器启动：官方 WebViewer 先监听 HTTP，再发布模型和重建服务。仅检查首页 200 会过早就绪；现在要求 `/model?total_bytes` 返回正的模型大小，新增对应回归测试。
- HTTP 生命周期：上游基于 websockets 的握手钩子服务普通 HTTP，普通响应后关闭 TCP。共享网关关闭闲置连接复用并发送 `Connection: close`，避免复用与上游关闭竞争导致的偶发 502；WebSocket 仍保持双向长连接。依据为锁定 websockets 包的 `ServerProtocol.send_response` 和 MuJoCo 3.16.0 的 `web_server.py`。
- 源码环境：此 iCloud 目录内的虚拟环境被附加隐藏属性，CPython 3.12 跳过被标记隐藏的 `.pth`，导致可编辑安装后续无法定位项目。原生与 Docker 统一通过 `PYTHONPATH` 运行 `src`，原生 `uv sync --no-install-project` 只准备锁定依赖，没有增加 macOS 专属修补分支。
- 监听地址：官方 3.16.0 默认绑定 `::`，子进程适配强制使用回环套接字工厂；内部端口不作为公共协议返回。

## 独立交付目录

- 单镜像 ARM64 临时 ZIP 已实际生成，ZIP CRC、归档 SHA-256、逐文件 SHA-256 与镜像 tar 内的 Linux ARM64 配置均通过。
- 交付文件只有一个镜像归档、Compose、配置、说明和验证记录，没有平台脚本或构建上下文。
- 在 `/tmp` 的独立解压目录使用本地已构建镜像启动 18324 服务，再次完成四种查看器的完整协议验收；不读取项目源码、虚拟环境或 Node 依赖。本次未清空 Docker 引擎后重新导入镜像。
- 本次测试容器和测试卷在验收后清理；保留本机 18320 原生服务。临时 ZIP 用于打包回归，没有作为正式版本发布。

## 日志与未验证事项

本机验收日志位于项目忽略目录 `.runtime/validation/`，包括 `setup-macos.log`、`tests-macos.log`、`smoke-macos.log`、两种架构的 Docker 构建日志及服务验收日志。浏览器脚本和截图保存在 `/tmp/`，不作为项目测试依赖提交。

仍存在既有的前端大于 500 kB 构建提示和 Starlette TestClient 对 httpx 的弃用提示；测试与运行通过。本次没有为消除提示升级无关依赖。

本次不验收多人会话、远程 HTTPS/认证、长期压力、非默认物理条件下的策略稳定性，也不提供 Intel Mac 或 Windows 原生兼容层。
