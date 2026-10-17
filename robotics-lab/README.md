# Robotics Lab

机器人交互实验室。以“课程 → 课时 → 实验”组织原理讲解、公式、交互仿真和结果分析。整体产品需求见 [整体需求](docs/demand/overall-demand.md)，课程实现见 [课程与 Panda 适配](docs/design/courses.md)。项目与 `experiments/` 独立，不依赖其硬件、模型、策略、数据或运行环境。

## Docker 启动（推荐）

Windows/macOS 安装并启动 Docker Desktop，使用 Linux 容器；Linux 安装 Docker Engine 与 Compose 插件。当前交付包为 `linux/amd64`，适用于 Intel/AMD 桌面电脑；容器内统一使用 Linux Python 3.12 和 MuJoCo 3.16.0。宿主机无需安装 Python、Node.js 或手动配置 WSL Ubuntu。ARM64 构建配置保留，Apple Silicon 包的构建与验收后续在 macOS 完成，当前未交付 ARM64 包。

从源码首次构建并启动：

```powershell
# Windows PowerShell，在 robotics-lab 目录执行
./run-docker.ps1 build
./run-docker.ps1
```

```bash
# Linux / macOS，在 robotics-lab 目录执行
bash run-docker.sh build
bash run-docker.sh
```

打开 <http://localhost:18320>。默认进入 Panda 课程；通过“课程目录”选择课时，再打开交互实验。API、官方查看器、模型资源和 WebSocket 使用同一个入口端口。

已有离线交付 ZIP 时，解压后运行脚本的 `load` 操作，再正常启动，详见 [离线包使用与数据迁移](docs/deployment/quick-start.md)。源码构建需要联网；离线包导入后不需要下载依赖或模型。

脚本支持 `build`、`load`、`up`（默认）、`stop`、`logs` 和 `status`。停止会保留数据卷。复制 `.env.example` 为 `.env` 可调整端口和数据目录。默认只向本机开放，单用户使用；远程部署需要 HTTPS、认证及浏览器跨源隔离配置。

发布结构、双架构构建和打包见 [Docker 发布设计](docs/design/docker.md)，实际验证状态见 [Docker 验证记录](docs/validation/docker.md)。原有 Python/WSL 源码启动脚本保留，适合开发调试。

## 当前能力

- **Panda 机械臂基础，7 节**：机械臂结构与正运动学、关节位置控制与动态响应、机械臂自重与重力补偿、雅可比、逆运动学、轨迹跟踪、夹爪接触与抓取。原正运动学链接跳转到合并后的第一节。
- **基础物理实验，2 节**：保留重力单摆和落球接触，重新组织为课时。
- 每节提供研究问题、前置知识、公式、操作步骤、观测与分析、练习及来源；KaTeX 和字体随前端构建，运行时不依赖 CDN。
- 课程目录可收起并记住展开状态；宽屏并排显示三维实验、实时观测和参数，操作按钮、曲线与原理讲解依次位于下方，窄屏自动纵向排列。
- Panda 网页控件与仿真进程相连，第一节通过位置伺服连续运动到目标；控制课可分别调整位置增益与阻尼。重力课提供从相同初态开始的释放、补偿保持操作，并隐藏目标球。
- 雅可比课以两秒单关节运动对照矩阵预测与末端位置差分速度，显示速度投影箭头、对应矩阵列、三轴速度及误差。IK 课收敛后通过位置伺服连续运动，分别显示求解残差与实际跟踪误差；未收敛时保留上一有效关节目标。另支持轨迹、抓取、暂停、继续、1 ms 单步和恢复初态。
- 实时末端位姿、关节力矩、雅可比、IK 残差和任务结果按课时显示；可导出交互观测或下载独立计算记录。
- 手动标记课时完成状态，保存在当前浏览器；切换课时会结束当前查看器会话。
- 官方 Studio WebViewer 组件检查与单会话进程管理；组件缺失时可运行独立数值验证。

Panda 资源固定于官方 Menagerie 提交 `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35`，保留 Apache-2.0 许可证。模型及网格随源码提供，首次克隆后的安装不需要另外下载模型。控制适配和场景修改见 [课程设计](docs/design/courses.md)，实测见 [课程验证记录](docs/validation/courses.md)。

尚未实现人形机器人课程、任意模型组合、避障规划、AI 策略、完整交互回放和学习账户。交互观测导出保存网页操作与采样，不保证复现官方查看器内的全部编辑；独立验证始终从预设初态计算，不读取当前交互修改。

## 运行环境

Docker 内由 Linux Python 计算，浏览器渲染三维场景。以下为不使用 Docker 时的源码运行方式；完整官方 WebViewer 使用 Linux/WSL 路线。

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

本机 Ubuntu 的依赖已安装后，也可在 Windows PowerShell 中进入本目录，执行 `./run-wsl.ps1`，默认使用 WSL 的默认发行版；也可用 `./run-wsl.ps1 -Port 8001 -Distribution Ubuntu-22.04` 指定端口和发行版。发行版名称以 `wsl --list --verbose` 为准。该脚本直接运行已安装的 Linux 虚拟环境，运行时不依赖 Windows 的 Python。

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
| `src/robotics_lab/assets` | 基础实验目录、Panda 上游模型与课程场景 |
| `src/robotics_lab/curriculum.py` | 课程、课时讲解与实验引用 |
| `src/robotics_lab/physics.py` | 初态加载和独立数值计算 |
| `src/robotics_lab/diagnostics.py` | 安装包组件与资源检查 |
| `src/robotics_lab/viewer.py` | 官方 WebViewer 适配 |
| `src/robotics_lab/panda.py` | Panda 专属运动学、控制、观测与接触任务 |
| `src/robotics_lab/studio.py` | 仿真线程中的课程命令、实时步进和观测发布 |
| `src/robotics_lab/sessions.py` | 查看器进程生命周期 |
| `src/robotics_lab/api.py` | 目录、数值运行、记录和会话接口 |
| `frontend` | 实验选择、说明、仿真窗口与独立结果展示 |
| `.runtime` | 本地生成的记录与会话日志，不纳入版本控制 |

当前界面与服务按单用户、单查看器会话设计；Docker 不改变会话数量。长期需求中的其他功能继续单独适配。
