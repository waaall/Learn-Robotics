# Robotics Lab

机器人交互实验室。以“课程 → 课时 → 实验”组织原理讲解、公式、交互仿真和结果分析。整体产品需求见 [整体需求](docs/demand/overall-demand.md)，课程实现见 [课程与 Panda 适配](docs/design/courses.md)。项目与 `experiments/` 独立，不依赖其硬件、模型、策略、数据或运行环境。

## 支持平台与快速启动

以下为完整功能的部署目标，实际测试结果见 [跨平台验证记录](docs/validation/deployment.md)：

| 目标 | 部署方式 |
| --- | --- |
| WSL2、Linux AMD64/ARM64 | 原生 Python 与浏览器，共用 `lab.sh` |
| Apple Silicon macOS | 原生 ARM64 Python 与浏览器，共用 `lab.sh` |
| Docker Linux AMD64/ARM64 | 单应用镜像；Windows/macOS 使用 Docker Desktop，Linux 使用 Docker Engine |

Windows 原生 Python、WSL1 和 Intel Mac 原生部署不属于支持目标。WSL2 内使用 Linux 工具链。所有目标共用 FastAPI 应用、MuJoCo 3.16.0、模型资源、同源查看器代理及跨源隔离配置，不依赖 `experiments/`。平台差异仅用于原生虚拟环境隔离。

### 原生部署：WSL2 / Linux / Apple Silicon Mac

准备 uv 0.13+（[安装说明](https://docs.astral.sh/uv/getting-started/installation/)）和 Node.js 22.12+（推荐 24 LTS）。在本目录执行相同命令：

```bash
bash lab.sh setup
bash lab.sh start
```

打开 <http://localhost:18320>。`setup` 按 `uv.lock` 创建本平台 Python 3.12 环境、按前端锁文件安装并构建界面，最后检查官方查看器组件。首次安装需联网，模型和策略已随源码提供。运行时不需要 Node 或外部 CDN。服务在前台运行，按 Ctrl+C 结束服务和查看器。

环境保存在 `.venv/<系统>-<架构>/`，缓存保存在 `.cache/`。不同操作系统或架构不共享 Python 虚拟环境。WSL2 建议将仓库放在 Linux 文件系统；无需在 Windows 安装 Python。可以从 Windows Terminal 进入 WSL2 后执行上述命令，不再维护另一套 PowerShell Python 启动流程。

### Docker 部署

安装并启动使用 Linux 容器的 Docker Desktop，或安装 Docker Engine 与 Compose v2+。所有宿主机使用相同命令：

```shell
docker compose -f compose.yaml -f compose.build.yaml build
docker compose up -d --wait --remove-orphans
```

打开 <http://localhost:18320>。构建默认使用 Docker 引擎架构；Apple Silicon 对应 `linux/arm64`，Intel/AMD Linux 容器对应 `linux/amd64`，无需修改部署文件。宿主机无需 Python、Node 或单独安装 WSL 发行版。

```shell
docker compose ps
docker compose logs --tail 100 -f
docker compose down
```

停止保留数据卷。离线包导入、数据备份与多架构构建见 [交付与迁移](docs/deployment/quick-start.md) 和 [Docker 构建设计](docs/design/docker.md)。

## 当前能力

- **Panda 机械臂基础，7 节**：机械臂结构与正运动学、关节位置控制与动态响应、机械臂自重与重力补偿、雅可比、逆运动学、轨迹跟踪、夹爪接触与抓取。原正运动学链接跳转到合并后的第一节。
- **人形机器人，5 节**：结构与浮动基座、质心与足底接触、双脚站立与重心转移、学习策略控制行走、扰动与恢复。采用 Unitree 官方 G1 双腿 12 驱动关节模型，上身固定；目标经连续参考和动力学执行。后两节运行官方预训练 LSTM 策略，提供平滑启动、速度修改、减速与有限时长外力。详见 [人形课程实现](docs/design/humanoid.md)。
- **基础物理实验，2 节**：保留重力单摆和落球接触，重新组织为课时。
- 每节提供研究问题、前置知识、公式、操作步骤、观测与分析、练习及来源；KaTeX 和字体随前端构建，运行时不依赖 CDN。
- 课程目录可收起并记住展开状态；宽屏并排显示三维实验、实时观测和参数，操作按钮、曲线与原理讲解依次位于下方，窄屏自动纵向排列。
- Panda 网页控件与仿真进程相连，第一节通过位置伺服连续运动到目标；控制课可分别调整位置增益与阻尼。重力课提供从相同初态开始的释放、补偿保持操作，并隐藏目标球。
- 雅可比课以两秒单关节运动对照矩阵预测与末端位置差分速度，显示速度投影箭头、对应矩阵列、三轴速度及误差。IK 课收敛后通过位置伺服连续运动，分别显示求解残差与实际跟踪误差；未收敛时保留上一有效关节目标。另支持轨迹、抓取、暂停、继续、1 ms 单步和恢复初态。
- 实时末端位姿、关节力矩、雅可比、IK 残差和任务结果按课时显示；可导出交互观测或下载独立计算记录。
- 手动标记课时完成状态，保存在当前浏览器；切换课时会结束当前查看器会话。
- 官方 Studio WebViewer 组件检查与单会话进程管理；组件缺失时可运行独立数值验证。

Panda 资源固定于官方 Menagerie 提交 `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35`，保留 Apache-2.0 许可证。模型及网格随源码提供，首次克隆后的安装不需要另外下载模型。控制适配和场景修改见 [课程设计](docs/design/courses.md)，实测见 [课程验证记录](docs/validation/courses.md)。

尚未实现任意模型组合、避障规划、策略训练、VLA、完整交互回放和学习账户。人形策略不包含跌倒起身，结果对应具体模型及配置；改变物理条件后可能失败。交互观测导出保存网页操作与采样，不保证复现官方查看器内的全部编辑；独立验证始终从预设初态计算，不读取当前交互修改。

## 配置与验证

可复制 `.env.example` 为 `.env` 后调整配置。原生脚本由 uv 加载 `.env`，Docker Compose 读取同一份部署参数；已有进程环境变量优先。命令行 `start --host ... --port ...` 可覆盖原生网络配置。

| 参数 | 原生部署 | Docker 部署 |
| --- | --- | --- |
| `ROBOTICS_LAB_HOST` | 服务监听地址，默认 `127.0.0.1` | 宿主机端口绑定地址，默认 `127.0.0.1` |
| `ROBOTICS_LAB_PORT` | 应用端口，默认 `18320` | 宿主机映射端口，默认 `18320`；容器内固定为 `8000` |
| `ROBOTICS_LAB_DATA_DIR` | 记录与日志目录，默认 `.runtime`；相对项目解析 | 不读取宿主机该值，数据使用独立命名卷 |
| `ROBOTICS_LAB_TAG` | 不使用 | 应用镜像标签 |

页面、API、官方客户端、模型与 WebSocket 均从同一端口访问。查看器子进程内部使用动态回环端口，不再向前端暴露或配置查看器端口、URL。原生部署与 Docker 默认使用各自独立的数据存储；课程完成状态仍保存在浏览器。

```bash
# 原生：组件检查、全部回归测试、已启动服务的协议验收
bash lab.sh doctor
bash lab.sh test
bash lab.sh smoke

# 覆盖端口；验收时使用相同地址
bash lab.sh start --port 18321
bash lab.sh smoke --url http://127.0.0.1:18321
```

```shell
# Docker：使用相同的 Python 命令和验收实现
docker compose exec lab python -m robotics_lab doctor
docker compose exec lab python -m robotics_lab smoke
```

`doctor` 检查 `headless_ui`、`state_payload`、JS/WASM 和查看器导入，缺件时返回非零状态码。`smoke` 在目录中选择代表实验，检查 HTTP、WASM 完整长度、模型分块、WebSocket、暂停、单步和恢复；会创建运行记录，已有会话时拒绝验收。该命令不替代浏览器实际三维渲染检查。

默认本机、单用户、单会话。远程部署需另行配置 HTTPS 和认证，保留 COOP/COEP；本次未增加多人会话或远程安全部署。运行结构与上游适配依据见 [统一部署设计](docs/design/deployment.md)。

## 前端开发

```shell
npm ci --prefix frontend
npm run dev --prefix frontend
npm run build --prefix frontend
```

先启动应用服务，再启动 Vite。开发页面将 API、查看器资源和 WebSocket 转发到本机应用端口（默认 18320，也读取项目 `.env`），并提供跨源隔离响应头。构建后由同一应用提供页面。页面不使用远程字体或运行时 CDN。

## 文件职责

| 位置 | 职责 |
| --- | --- |
| `src/robotics_lab/assets` | 基础实验目录、Panda 上游模型与课程场景 |
| `src/robotics_lab/curriculum.py` | 课程、课时讲解与实验引用 |
| `src/robotics_lab/physics.py` | 初态加载和独立数值计算 |
| `src/robotics_lab/config.py` | 各部署共用的应用配置 |
| `src/robotics_lab/gateway.py` | 官方查看器 HTTP/WebSocket 代理与跨源隔离 |
| `src/robotics_lab/diagnostics.py` | 安装包组件与资源检查 |
| `src/robotics_lab/viewer.py` | 官方 WebViewer 适配 |
| `src/robotics_lab/panda.py` | Panda 专属运动学、控制、观测与接触任务 |
| `src/robotics_lab/humanoid.py` | G1 连续参考、预训练策略推理、接触观测与独立验证 |
| `src/robotics_lab/humanoid_curriculum.py` | 五节人形课程的原理、公式、操作与来源 |
| `src/robotics_lab/studio.py` | 仿真线程中的课程命令、实时步进和观测发布 |
| `src/robotics_lab/sessions.py` | 查看器进程生命周期 |
| `src/robotics_lab/api.py` | 目录、数值运行、记录和会话接口 |
| `lab.sh` | WSL2、Linux、Apple Silicon Mac 原生环境与启动 |
| `compose.yaml`、`Dockerfile` | 同一应用的单服务、多架构容器部署 |
| `src/robotics_lab/smoke.py` | 原生和 Docker 共用的协议验收 |
| `frontend` | 实验选择、说明、仿真窗口与独立结果展示 |
| `.runtime` | 本地生成的记录与会话日志，不纳入版本控制 |

当前界面与服务按单用户、单查看器会话设计；Docker 不改变会话数量。长期需求中的其他功能继续单独适配。
