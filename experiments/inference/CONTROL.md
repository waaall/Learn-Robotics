# LLM 调度、SmolVLA 诊断与 SO-101 受限执行

本入口用于 `experiments/inference/` 的单从臂实验。上层 LLM 通过工具观察环境、选择任务、发起短时执行并检查结果；本地常驻进程持有模型、相机与串口，处理时序和停机。当前会话已由 Codex 实际调用这些工具。程序本身不请求 LLM API；独立 API 客户端可依据工具契约绑定同一组方法。本版本没有注册 MCP 服务。

## 模块与控制接口

| 模块 | 职责 |
| --- | --- |
| `supervisor.py` | 仅绑定 `127.0.0.1` 的工具服务、单任务调度、外部 LLM 决策记录、视觉观测关联、看门狗 |
| `tool_contract.json` | `observe / load_model / preview / start_task / status / stop / annotate / shutdown` 的输入 schema |
| `control.py` | 处理器统计绑定审计、输入检查、速度、标定范围、累计运动量及跟踪误差限制 |
| `control_hardware.py` | 独占从臂、校准／模式核对、目标写入回读、力矩接管与逐轴释放 |
| `recording.py` | 连续 MJPEG AVI 与逐帧主机单调时间戳 |
| `evidence.py` | 从日志生成 CSV／指标，并导出按实际帧时间重建的 H.264 短片 |

LLM 的输入为近期图像、关节／设备状态和任务目标；输出为任务文本、选用控制器、活动关节、持续时间和简要决策依据。SmolVLA 的输入仍为真实 wrist RGB 图像、六维状态及任务文本，输出 50×6 动作块。执行器与舵机位置环承担动作调度和目标跟踪。

`start_task` 提供两个显式控制器：

- `vla`：模型生成动作，只执行短前缀并重新观测。必须通过状态／动作统计的精确特征绑定检查。当前基础模型无法通过，动作不会下发。
- `wrist_nod`：确定性的腕俯仰正弦技能，最多 ±3°，只允许 `wrist_flex`。这是控制链验收技能，日志中 `source=deterministic_wrist_nod`、`model_action=null`；它不构成 VLA 指令跟随的证据。

两种控制器的请求、实际输入、实际目标、编码器反馈和执行结果分别保存。`job.state=completed` 表示程序执行结束，任务成功需结合反馈与图像另行判断。

## 当前配置与本地停机

默认控制目标频率为 20 Hz，身体关节目标速度上限 8°/s，夹爪为 12 标定单位/s；实际周期另行测量。身体累计目标偏移不超过启动位置 ±20°，目标与机械标定端点保留 24 个编码器刻度；单次执行不超过 3 秒。点头技能还要求正弦目标的最大导数不超过关节速度上限。

开启力矩前，读取各轴当前位置，将启动目标逐轴写为当前位置并回读验证；随后才开启力矩。保持已保存的标定、模式、PID 和保护参数，记录原寄存器值。活动关节以外的目标保持启动值。读取保留底层协议错误，异常、陈旧帧、录像故障、温度超过本实验设定的 55°C 或跟踪误差超过配置值会停止任务。55°C 是实验保守阈值，未声称为厂商额定温度。

段间持有最后目标，并由独立本地线程监测；`observe / status` 更新 60 秒监督租约，整个服务最多运行 600 秒。`stop` 取消任务、逐轴关闭力矩并回读；日志磁盘故障也不能阻止关闭力矩的事务。关闭力矩会解除位置保持。进程被强制杀死或主机故障时，软件看门狗无法继续执行。

## 使用

先按 README 安装 `-Live` 环境。以下在 `experiments/inference/` 的 PowerShell 中执行。设备访问需要当前运行环境允许访问串口与相机。

```powershell
# 输出工具 schema，不接触设备。
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor tools

# 一个终端常驻运行；省略 --allow-motion 时只能诊断。
.\run.ps1 python -m smolvla_inference.supervisor serve --allow-motion

# 另一个终端或 LLM 工具调用这些命令。
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call observe
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call load_model
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call status
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call preview --params '{"task":"Nod the gripper up and down slightly.","noise_sample":0}'
```

观察返回的 `image_path`，确认当前图像和状态后，将真实 `observation_id`、任务和依据写入一个 JSON 文件，例如：

```json
{
  "controller": "wrist_nod",
  "task": "Nod the gripper once and return to the starting target.",
  "seconds": 3,
  "amplitude_deg": 2.5,
  "active_joints": ["wrist_flex"],
  "observation_id": "填写刚刚检查的观测 ID",
  "reason": "填写基于当前画面的执行依据"
}
```

```powershell
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call start_task --params '@request.json'
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call status
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call observe
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call stop
.\.venv\Scripts\python.exe -m smolvla_inference.supervisor call shutdown
```

服务通过输出目录中的会话文件保存随机 token，客户端读取后只向本地发送。不要把会话 token 放入模型提示或公共日志。HTTP 采用 `{method, params}` 请求；本版本以 CLI 作为当前 LLM 的调用适配器。

## 记录与回放

每次服务独立创建 `outputs/supervised/<时间>/`，保存：

- `report.json`：冻结模型身份、运行环境、配置、统计绑定检查、任务状态和停机结果。
- `operations.jsonl`：工具请求、LLM 决策、观测、模型预测、寄存器写入尝试、逐周期命令与反馈。
- `camera.avi`、`frames.jsonl`：连续画面及每帧主机收帧时间。AVI 按请求的 30 FPS 编码；直接播放时长可能不同于实际采集时长。
- `observation-*.jpg`、`prediction-*-input.png`、`prediction-*.npz`：供 LLM 查看和模型实际使用的输入，以及归一化／处理后动作、噪声种子与样本号。
- `metrics.json`、`trial-*-trajectory.csv`、`trial-*.mp4`：派生指标与按实测时间戳重建的 H.264 短片。原始录像与日志保持保存。

关闭服务后运行，FFmpeg 路径使用仓库固定版本的 `bin/ffmpeg.exe`：

```powershell
.\.venv\Scripts\python.exe -m smolvla_inference.evidence outputs/supervised/<时间> --ffmpeg <固定FFmpeg路径>
```

`reports/plot_control.py` 可用独立的 Matplotlib 环境从 CSV 生成 PNG／SVG，不需要向推理环境安装绘图库。

## 模型统计与适配状态

固定权重 `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6` 的两个处理器状态文件只有 `so100*.buffer.action` 统计；没有 `observation.state` 统计，也没有精确绑定到 `action` 的统计。LeRobot 0.6.1 在找不到特征键时返回原张量。`preview` 允许保留这一诊断输出；`vla` 执行入口明确拒绝它。

不自动选择任意 SO-100 统计组，不把动作统计代替状态统计，不用单次姿态拟合统计，也不将模型潜变量直接解释为本机关节目标。后续需要恢复有来源的完整输入／输出统计，并核实机器人参考系、单位、轴序、方向和相机布局，再重做受限闭环验证；这些适配工作不必然要求更新模型权重。

来源：[基础模型卡](https://huggingface.co/lerobot/smolvla_base)、[归一化迁移问题 #4415](https://github.com/huggingface/lerobot/issues/4415)、[LeRobot 0.6.1 处理器实现](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/processor/normalize_processor.py)、[SO follower 位置控制实现](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/robots/so_follower/so_follower.py)。上层具身推理与 VLA 编排的系统参考见 [Gemini Robotics ER 文档](https://ai.google.dev/gemini-api/docs/robotics-overview)。
