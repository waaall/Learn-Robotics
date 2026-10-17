# Robotics Lab

机器人交互实验室。整体产品需求见 [整体需求](docs/demand/overall-demand.md)，工程组织见 [框架设计](docs/design/framework.md)。

## 当前电脑快速启动

WSL Ubuntu 环境与前端已安装、构建。在本目录的 Windows PowerShell 中执行 `./run-wsl.ps1`，再用 Windows 浏览器打开 <http://localhost:8000>。网页中选择实验后打开交互仿真，或单独运行数值验证。

新电脑的安装步骤见下文。完整交互仿真使用 Linux 的 Python 环境。

## 当前能力

- 两个自带实验：重力单摆、落球接触，包含明确初态与实验说明。
- 本地网页目录、实验说明、独立数值验证、真实结果曲线与 JSON 记录下载。
- 官方 Studio WebViewer 组件检查与单会话进程管理；组件缺失时明确报告原因。
- 官方交互仿真与独立数值验证分开：后者始终从预设初态运行，不读取交互窗口中的修改。

尚未实现 Menagerie 模型目录、参数编辑、控制器实验、AI 策略接入和完整课程。已完成的实测及待验证内容见 [验证记录](docs/validation/framework.md)。

## 运行环境

本项目采用本地 Python 计算、浏览器访问的部署方式。官方 WebViewer 使用 Linux/WSL 路线。

**MuJoCo 3.16.0 原生 Windows 安装包不支持官方 WebViewer。** 上游构建配置在 Windows 跳过 `headless_ui` 和 `state_payload`，且 Windows wheel 未分发浏览器客户端。Windows 仍可运行目录、数值验证和结果查看。[上游构建配置](https://github.com/google-deepmind/mujoco/blob/3.16.0/python/mujoco/experimental/studio/web/CMakeLists.txt)

准备 Python 3.12、uv 和 Node.js 22.12+ 或 24。Python 与前端各有独立锁文件。不同系统使用独立虚拟环境，不复制或共享虚拟环境目录。

## Windows：构建界面与验证数值实验

在本目录执行：

```powershell
./setup.ps1
./run.ps1
```

打开 <http://localhost:8000>。Windows 下交互仿真入口根据组件检查结果禁用；可以运行独立数值验证。

```powershell
.venv/Scripts/python.exe -m robotics_lab doctor
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe -m robotics_lab simulate drop-ball --output .runtime/drop-ball.json
```

## Ubuntu / WSL：官方 WebViewer 运行环境

在 Ubuntu 中进入本目录，使用 Linux 的 uv。前端可使用 Windows 已构建的 `frontend/dist`，也可以在 Linux 使用 Node.js 构建。

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-linux"
export UV_CACHE_DIR="$PWD/.cache/uv-linux"
uv sync --locked --extra dev --python 3.12
uv run --locked python -m robotics_lab doctor
bash run-linux.sh
```

Windows 浏览器访问 <http://localhost:8000>。如该端口已被其他进程占用，可执行 `bash run-linux.sh 8001`。查看器使用单独的动态端口；访问其他 Linux 主机时，应用端口与查看器端口都需要可达，当前尚未提供统一端口代理。

本机 Ubuntu 的依赖已安装后，也可在 Windows PowerShell 中进入本目录，执行 `./run-wsl.ps1`，或用 `./run-wsl.ps1 -Port 8001 -Distribution Ubuntu` 指定端口和发行版。该脚本直接运行已安装的 Linux 虚拟环境，运行时不依赖 Windows 的 Python。

当前电脑已在 `.venv-linux` 安装并验证 Linux 依赖。为完成本次安装而下载的 Linux uv 位于 `.cache/linux-tools/bin/uv`；若尚未将 uv 安装到 Ubuntu 的 PATH，可在上述安装命令中使用这个路径。缓存和虚拟环境均不纳入版本控制，新机器需重新安装。

`doctor` 检查扩展模块和浏览器资源。检查通过后仍需启动查看器，验证浏览器渲染及交互。网页内可启动、结束一个查看器会话；应用正常关闭时会清理其子进程。

官方查看器包含左右操作面板，建议在桌面浏览器中使用；窄窗口可以通过“独立窗口”入口打开完整查看器。

## 前端开发

```shell
npm ci --prefix frontend
npm run dev --prefix frontend
npm run build --prefix frontend
```

开发页面将 `/api` 请求转发到本机 8000 端口。构建后由本地应用提供页面。页面不使用远程字体或运行时 CDN。

## 文件职责

| 位置 | 职责 |
| --- | --- |
| `src/robotics_lab/assets` | 实验目录与模型；模型派生自本仓库已有基础算例 |
| `src/robotics_lab/physics.py` | 初态加载和独立数值计算 |
| `src/robotics_lab/diagnostics.py` | 安装包组件与资源检查 |
| `src/robotics_lab/viewer.py` | 官方 WebViewer 适配 |
| `src/robotics_lab/sessions.py` | 查看器进程生命周期 |
| `src/robotics_lab/api.py` | 目录、数值运行、记录和会话接口 |
| `frontend` | 实验选择、说明、仿真窗口与独立结果展示 |
| `.runtime` | 本地生成的记录与会话日志，不纳入版本控制 |

当前界面与服务按本地单用户、单查看器会话设计；长期需求中的其他功能继续单独适配。
