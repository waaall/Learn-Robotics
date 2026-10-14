# Inference：SmolVLA 离线比较与实时输入诊断

模型原理见[SmolVLA：模型架构、训练与推理](../../research/smolvla-architecture.md)，包括上下文编码、动作块生成、K/V 缓存与数值积分。本文说明推理部署、诊断和指标计算。

## 范围与独立性

离线入口 `python -m smolvla_inference` 保留 `plan / infer / compare`：从留出轨迹生成动作块，保存预测、误差与延迟，不连接硬件。新增独立入口 `python -m smolvla_inference.live`，读取 SO-101 从臂与夹爪相机，使用基础模型生成动作文件。两种入口都不更新权重、不执行机器人动作。

自己的 `pyproject.toml`、`uv.lock`、`.venv`、setup、runner、配置和软件预检；可独立部署到另一台 Windows NVIDIA 机器，不要求 training 的代码或环境。共享包通过 path dependency 安装，推理只依赖**交接文件**。部署需保留本项目、`packages/smolvla_common` 和 `tools/windows_runtime` 的仓库相对结构。

| 文件 | 职责 |
| --- | --- |
| `configs/smolvla-offline.toml` | 输入准备记录／模型、本机资产覆盖、评估参数、独立输出路径 |
| `smolvla_inference/config.py` | 不包含训练超参数的推理配置校验 |
| `smolvla_inference/engine.py` | 固定噪声、观测筛选、处理器加载、预测、掩码指标和计时 |
| `smolvla_inference/__main__.py` | 显式基线／模型选择及同协议比较 |
| `test_inference.py`、`test_portable_artifacts.py` | CPU 替身适配、资产重定位与协议测试 |

## 1. 安装与软件预检

先按 [远程工具说明](../../tools/remote/README.md)选择 inference 目标、本地校验并只读盘点，明确同步代码后，在**服务器 PowerShell**粘贴该目标的 session 变量块：

```powershell
& (Join-Path $Lab "setup.ps1") -Python $Python
& $Runner python -m unittest discover -v
& $Runner python check_environment.py
& $Runner python -m $EntryModule --config $Config plan
```

setup 只同步本项目环境并提供校验过的 FFmpeg shared，不动 training 或硬件项目。日常使用本项目 runner，不调用其他 `.venv`。环境预检是版本／CUDA 推理小矩阵／合成视频检查，**没有加载真实 SmolVLA**；不因 CUDA 小矩阵通过就宣称模型可用或延迟达标。实际 infer 要求 CUDA，不静默回退 CPU。

## 2. 配置输入与资产交接

独立 TOML 中四个配置节：

| 节 | 内容 |
| --- | --- |
| `paths` | 基目录、prepared_manifest、缓存和推理 output_dir |
| `assets` | dataset_dir、base_model_dir、backbone_dir；留空沿用冻结记录的路径 |
| `model` | 明确的 checkpoint；可留空后通过 CLI 指定，不能自动取 latest |
| `inference` | max_samples、warmup_runs、noise_seed |

所有相对路径基于配置所在目录与 `base_dir` 解析，与 shell 当前目录无关。示例 prepared 路径指向同一 checkout 的 training 输出，**仅是可替换配置，不是导入依赖或自动发现逻辑**；训练机器与推理机器不同，填写本机实际输入路径和资产目录。

需要从本版本 training 交接：

1. **原样**的 `prepared.json`，其中保留原配置指纹、SHA、schema、训练／验证轨迹和训练 stats。
2. 数据完整 snapshot（meta／data／videos）与骨干配置／tokenizer 完整 snapshot。
3. 基线推理需要冻结的基础模型 snapshot。
4. 训练模型推理需要完整模型目录：权重、配置、预／后处理 JSON、它们引用的状态文件及 `experiment.json`。不需要 optimizer／RNG／scheduler 等 `training_state`，也不要求 `train_config.json` 或原目录名称。

不要只复制 `model.safetensors`，也不要将 checkpoint 当作原始 VLM 权重。复制 HF snapshot 时跟随文件链接，确保新机器实际持有完整文件，不能引用原机 blobs。

通过 `assets` 显式重定位，不改写 prepared 中的历史路径或训练身份。模型与 prepared 的指纹／版本必须一致；数据 metadata 必须与冻结记录一致。**metadata 和协议检查不是所有数据／权重文件的逐字节哈希核验**，必须确保复制的是相同固定 snapshot；不能用“metadata 相同”证明任意副本相同。旧合并格式不自动升级，参见 [迁移说明](../README.md#旧入口迁移)。

## 3. 基线、训练模型和比较

```powershell
# 基线：同一训练侧 stats、留出集、噪声及动作空间，只有权重未经本次微调。
& $Runner python -m $EntryModule --config $Config infer --baseline

# 显式选择完整模型；或在 TOML 的 model.checkpoint 配好后只写 infer。
$Checkpoint = Read-Host "输入本机完整模型目录"
& $Runner python -m $EntryModule --config $Config infer --checkpoint $Checkpoint

# 取本项目配置的输出路径，不依赖训练输出树或固定步数。
$PlanJson = & $Runner python -m $EntryModule --config $Config plan
if ($LASTEXITCODE -ne 0) { throw "plan failed" }
$Plan = ($PlanJson -join "`n") | ConvertFrom-Json
$BaselineReport = Join-Path $Plan.output_dir "baseline/report.json"
$TrainedReport = Join-Path $Plan.output_dir "checkpoint/report.json"
& $Runner python -m $EntryModule --config $Config compare --baseline-report $BaselineReport --trained-report $TrainedReport
```

`compare` 必须显式指定两份报告，不加载模型或 prepared；可比协议包含原训练指纹、数据／模型版本、schema、验证轨迹、全局帧号、动作块长、Flow 步数、噪声种子和精度。任一报告未完成或协议不同就停止。相机名称／维度不匹配、处理器状态缺失、坏帧、OOM 或资产缺失也报错，不自动跳过。

第一版每个 output_dir 保存 `baseline` 和 `checkpoint` 各一次结果；重复调用会替换相应结果。比较多个模型时给各次实验配置不同 output_dir，以免混淆历史。失败会更新 report 状态，不能拿上次 completed 冒充本次成功。

## 推理方式和指标解释

- 条件仅为当前 `observation.*` 与 `task`；示范 action、padding 和未来状态不输入模型。
- 固定种子加全局帧号产生**动作块形状**的噪声；它不是实测关节状态。SmolVLA 根据条件迭代生成动作块。
- 基线使用训练侧 stats；训练模型回读保存的预／后处理器和归一化状态，不用验证统计覆盖。
- 轨迹尾部 padding 不计入误差；逐动作轴 MAE／RMSE 和首动作 MAE，不把混合单位合并成“角度误差”。
- 预热后计时，GPU 阶段显式同步。分别记录数据解码、噪声准备、预处理、模型生成和后处理，以及串行 end_to_end 的 P50／P95／最大值和 CUDA 内存峰值；不含模型加载，不等于机械臂控制周期。

以上描述的是原有离线入口；实时观测入口如下。两者都没有动作执行、插值或闭环控制器。

输出：

- `<baseline 或 checkpoint>/report.json`：状态、协议、模型、各轴误差、计时、显存和限制。
- 同目录 `actions.npz`：预测／示范动作块、padding mask、全局帧号；`samples.csv`：轨迹编号及分阶段计时。
- `comparison.json`：微调前后差值和两份报告来源。负误差差值只说明离线拟合改善，不设置无依据的通用通过阈值。

## 验证状态与依据

2026-10-13 的离线迁移验收：CPU 替身测试覆盖完整离线文件流程、重命名模型目录、无训练状态推理、资产重定位、固定噪声、padding 和基线比较；隔离复制后的 plan 无需训练／硬件项目，也不导入重依赖。这些离线替身测试不代表真实模型前向或闭环控制；当天追加的实时输入验收见下文。

[SmolVLA 动作生成源码（LeRobot 0.6.1）](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/smolvla/modeling_smolvla.py)对应显式噪声与动作块接口；[处理器源码](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/smolvla/processor_smolvla.py)对应预／后处理及归一化。这是锁定版本的适配，不承诺兼容任意更新版。

公开数据可能已出现在基础模型预训练中；离线误差不证明闭环抓放成功、语言泛化或黑臂到白臂／单相机的迁移。

## 单夹爪视角实时诊断

输入唯一的 `observation.images.wrist`、从臂六轴状态和任务指令。不依赖公共数据集或 training 的 prepared 文件，也不伪造 top 图像。此入口目前只支持 `lerobot/smolvla_base`，用于验收实时输入到模型输出的链路，不能据此认定它已学会当前桌面的任务。

在仓库根目录 PowerShell 中：

```powershell
# 安装独立推理环境及只读串口依赖，-Python 填本机 Python 3.12 路径。
& .\experiments\inference\setup.ps1 -Live -Python C:\mysoftware\python312\python.exe
$InferencePython = Join-Path $PWD 'experiments/inference/.venv/Scripts/python.exe'
Push-Location .\experiments\inference
try {
    & $InferencePython -m smolvla_inference.live plan
    & $InferencePython -m smolvla_inference.live prepare
    & $InferencePython -m smolvla_inference.live capture --samples 3
    & $InferencePython -m smolvla_inference.live infer --samples 10 --task 'Pick up the object and place it in the container.'
} finally { Pop-Location }
```

`configs/smolvla-wrist-live.toml` 中的 USB 序列号和标定路径针对当前从臂。更换设备需显式修改；相机重插后检查 camera_index。`prepare` 下载公开基础模型、骨干配置与 tokenizer，将两个实际 commit SHA 存到仓库 `.cache/smolvla-live/assets.json`；`infer` 只用已准备的本地文件。基础模型完整权重已包含视觉语言骨干，不重复下载骨干权重。

镜像直连可在运行 `prepare` 前清除本次 PowerShell 的代理，并设置 `$env:HF_ENDPOINT = 'https://hf-mirror.com'`；[镜像使用说明](https://hf-mirror.com/)提供该环境变量。手动下载权重后可运行 `python -m smolvla_inference.live prepare --weights '本地 model.safetensors 路径'`，程序核对固定版本的文件大小和 SHA-256 后才导入，已有模型不会被错误文件覆盖。

硬件适配直接使用 LeRobot 0.6.1 `FeetechMotorsBus` 的只读连接与寄存器读取，不调用 `Robot.connect/configure`，结束时显式 `disconnect(disable_torque=False)`。文件标定必须匹配设备，力矩必须关闭；不会回写标定或切换模式。只读取从臂，主臂无需连接。

状态顺序是 shoulder_pan、shoulder_lift、elbow_flex、wrist_flex、wrist_roll、gripper；前五轴按本机标定映射到 −100～100，夹爪为 0～100。编码器超出 0～4095 时停止；超出机械标定范围的输入按官方归一化裁剪，同时保存原始值与 `state_warnings`。**本机归一化状态与预训练模型状态的语义一致性尚未验证；预测使用权重自带处理器与统计，其输出不能解释为本机角度或直接下发的目标。**

相机后台连续采集 DirectShow/YUY2 640×480，BGR 转 RGB、CHW、float32 0～1 后进入官方处理器；只保留最新帧。关节读数与图像没有硬件同步，日志记录各自的主机单调时间与输入帧龄。每次诊断开始 reset 一次，随后直接 `predict_action_chunk`，不消费缓存动作；这一时序只用于不执行动作的连续诊断。

每次运行新建 `outputs/wrist-live/<时间>/`：`first-frame.jpg`、`samples.jsonl`、每次的 `chunk-XXXX.npz`、汇总 `actions.npz` 与 `report.json`。动作块应为 50×6，有限数值才计入完成。报告含预热后的预处理／模型／后处理／总耗时 P50、P95、最大值和显存峰值；总耗时含采集与落盘，不等于控制周期。每块立即保存，中断也保留已生成结果，Ctrl+C 会关闭相机和串口。

[基础模型配置与处理器](https://huggingface.co/lerobot/smolvla_base/tree/main)、[SmolVLA 图像及动作块实现](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/smolvla/modeling_smolvla.py)对应此入口的权重加载与单视角适配；这不是公共双相机任务模型的闭环部署。

2026-10-13 本机实测：通过 HF Mirror 直连下载固定版本 `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6`，906,712,520 字节权重的 SHA-256 与官方元数据 `7cd549ac2351fb069c0ddb3c34ad2d09cfc92b56a15dccdfc2e41467aaca01eb` 一致。RTX 3060 Ti 连续 10 次真实图像／从臂状态推理通过，输出 `(10, 50, 6)` 全部有限数值；关闭 AMP，10 个 Flow 步，预热 2 次。

| 实测项目 | 结果 |
| --- | --- |
| 模型生成 P50 / P95 | 341.6 / 371.3 ms |
| 含采集与落盘的总耗时 P50 / P95 | 349.4 / 385.5 ms |
| PyTorch 峰值 allocated / reserved | 1,263,996,928 / 1,319,108,608 字节 |
| 相机主机取帧速率 | 22.61 FPS |
| 标定范围警告 / 动作下发 / 舵机寄存器写入 | 0 / 0 / 0 |

完整报告位于本机 `outputs/wrist-live/20261013-222042-639058/report.json`，动作块及输入记录在同目录。模型首次加载约 82 秒，未计入上述预热后耗时。90 项无硬件开发测试通过；本次验证了实时输入到动作文件的链路，未验证抓放成功率、实时执行队列或闭环控制。
