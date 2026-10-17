# Docker 验证记录

日期：2026-10-17。本页记录本次构建、运行和交付包验收，不将模拟环境等同于目标宿主机实测。

## 环境

- 宿主机：Windows AMD64，Docker Desktop 4.66.1，Linux Engine 29.3.1，Compose 5.1.0。
- 原生容器：`linux/amd64`。ARM64 使用临时注册的 QEMU；模拟运行与 macOS/Apple Silicon 实机验收分别记录。
- Python 3.12、MuJoCo 3.16.0；Python 与 Node 依赖按各自锁文件安装。基础镜像固定到本次构建的多架构 manifest 摘要。
- 浏览器：Windows Chrome 155，Playwright CLI 驱动。宿主机脚本分别验证 PowerShell 与 Ubuntu 22.04 WSL 的 Bash。

## AMD64 验证结果

- API 构建阶段 36 项测试通过，包括物理数值、Panda 控制与课程契约、固定端口/代理地址、数据目录配置后重新创建应用读取原记录；官方查看器组件检查 `available: true`。
- 前端 Docker 构建完成 TypeScript 检查和 Vite 生产构建，最终 Nginx 配置 `nginx -t` 通过。
- 通过统一入口启动 Panda、单摆、落球三种实际查看器；验证 HTML、WASM 二进制签名、响应头、二进制 WebSocket 状态流、单步和恢复初态。服务端脚本为 `tools/smoke_docker.py`。
- 浏览器渲染 Panda 和第二节关节控制课程，顶层及 iframe 的 `crossOriginIsolated` 均为 `true`。正常运行重新加载后控制台无错误。三维截图在忽略目录 `output/playwright/`。
- 网页将关节 2 目标设置为 `0.1 rad`，暂停时实际角度约 `0.099999815 rad`。点击单步，仿真时间增加 `0.0010000000000047748 s`；恢复初态后时间归零。
- 切换到下一课自动结束旧会话，状态接口返回 `null`；第二课可重新打开三维实验并运行网页独立数值验证。
- 停止 API 后通过 `docker compose cp` 备份完整数据目录，再启动服务，原记录 `dca1f029-94dd-4e03-b66a-5e7e60358db2` 可经统一入口读取。
- 运行镜像不包含测试依赖 `httpx`；API 以 UID 10001 运行，API 和查看器仅在容器内部监听，对外只有 Web 端口。

测试期间服务端脚本主动切换/终止会话，或容器停止与重建时，已打开的浏览器可能记录连接中断；正常运行验收在这些操作结束后重新加载，并单独检查控制台。

## ARM64 与离线交付

- AMD64 ZIP 已实际生成；检查 ZIP CRC、归档 SHA-256、清单中每个文件的 SHA-256 和 shell 脚本 LF 换行均通过。
- 将 ZIP 解压到独立目录，使用包内 PowerShell 脚本 `load` 导入两个镜像；以独立项目名和端口 18322 启动，目录没有源码、构建文件、Python 虚拟环境或 Node 依赖。
- 对包内镜像再次执行三种查看器、完整 WASM 读取、WebSocket、暂停后单步、恢复初态及数值记录验证，全部通过；包内 Bash 脚本也在 WSL 实际启动成功。
- 验收脚本显式先暂停再测量单步时长，避免运行中的状态采样跨越多个积分步。离线包测试服务和测试卷在完成后清理，不影响主服务数据卷。
- 最终包为 `dist/robotics-lab-0.1.0-linux-amd64.zip`，大小 148,836,093 字节，旁附 `.zip.sha256`。最终说明调整后重新验证 ZIP CRC、归档与逐文件 SHA-256；包内镜像的配置摘要和文件系统层序列与已导入运行的镜像一致。

ARM64 已在 QEMU 中确认 Python 可执行、模型可加载、官方查看器组件 `available: true`，部分物理与课程测试通过，包括两项长时抓取测试。按用户要求停止剩余 ARM64 构建和包验收；本次未生成 ARM64 API 交付镜像或离线包，完整构建及实机验收留待 macOS。此次临时注册的 `qemu-aarch64` 在结束后移除。

## 尚未完成的实机验证

- macOS Intel、macOS Apple Silicon 宿主机实测；Safari、Firefox 浏览器实测。
- 独立 Linux 实体宿主机测试。当前 Linux shell 已在 WSL 验证，Linux 容器已在 Docker Desktop 内核运行。
- 远程 HTTPS/认证部署、多人独立会话及长期压力测试。当前交付采用本地单用户模式。

当前 Starlette TestClient 对 httpx 的弃用提示仍存在；测试正常完成，运行镜像不包含该测试依赖。
