# Training：SmolVLA 公开数据正式微调

模型原理见[SmolVLA：模型架构、训练与推理](../../research/smolvla-architecture.md)，包括 VLM、动作专家、状态投影、Flow Matching 和梯度计算。本文说明部署、训练与验收流程。

## 范围

Windows 原生单卡训练项目，入口只有 `plan / prepare / train`。负责下载并冻结资产、完整轨迹划分、训练侧统计量、官方训练循环、验证 loss 与 checkpoint 保存／恢复；**不连接机械臂、不打开实时摄像头、不提供离线／真机推理命令、不自动上传模型**。离线推理由 [inference 项目](../inference/README.md)负责。

默认使用配置中的公开抓放数据和预训练 SmolVLA，20,000 步、batch 8；冻结 VLM，训练动作专家及状态投影。这里是完整微调流程，不是从零预训练或全参数解冻。显存、耗时与收敛必须实测，默认值不是 4090 可运行保证；OOM 不会触发偷偷减 batch 或切 CPU。改训练规模时使用新 run_dir 并重新 prepare。

| 文件 | 职责 |
| --- | --- |
| `configs/smolvla-so100.toml` | 模型／数据版本、缓存／输出、训练参数；无推理参数 |
| `smolvla_training/__main__.py` | 独立 CLI，重依赖按命令延迟导入 |
| `smolvla_training/data.py` | 显式下载、视频预检、训练侧统计量 |
| `smolvla_training/training.py` | 官方训练循环适配、完整状态保存和恢复 |
| `../../packages/smolvla_common` | 共享配置、数据／模型协议与 LeRobot 接口适配 |
| `test_training.py` | 无下载／无硬件的配置与训练循环替身测试 |

公共数据 ID 只在示例 TOML 中声明；程序不固定轨迹数、关节名称、相机数量或动作维度。第一版接受 LeRobot v3.0、RGB HWC 相机、一维 state/action 和有效语言标签；不同机器人的动作语义不能因维度相同就视为可互换。

## 1. 独立部署与预检

先按 [远程配置与只读盘点](../../tools/remote/README.md)填写客户端私有机器配置、核对 SSH 主机身份、明确同步代码。服务器需要本项目、共享包和 `tools/windows_runtime`；未提交／推送的本地文件不会被服务器 git pull 自动取得。远程辅助不会替你安装或同步。

以下在**服务器 PowerShell**执行；先粘贴客户端 `remote_lab ... session` 生成的变量块，目标须是 training。该块只声明路径和切换目录，不提前调用未安装的模型环境。需要已有 uv，见 [官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)。

```powershell
# 只安装 training/.venv，不动硬件或 inference 的环境。
& (Join-Path $Lab "setup.ps1") -Python $Python
& $Runner python -m unittest discover -v
& $Runner python check_environment.py
& $Runner python -m $EntryModule --config $Config plan

# 安装后再读取 plan；输出目录来自配置，不写死机器路径。
$PlanJson = & $Runner python -m $EntryModule --config $Config plan
if ($LASTEXITCODE -ne 0) { throw "plan failed" }
$Plan = ($PlanJson -join "`n") | ConvertFrom-Json
$Run = $Plan.run_dir
```

`setup.ps1` 使用本项目 `uv.lock`，安装本地共享包，并校验／解压固定哈希的 FFmpeg shared。`run.ps1` 使用本项目 `.venv/Scripts` 并临时提供 DLL 路径。不要用 hardware 的 runner 或全局 pip 绕过锁文件。

`plan` 不导入 PyTorch／LeRobot、不联网、不分配 GPU；仍须先安装共享包。`check_environment.py` 检查版本、CUDA 小矩阵梯度更新、合成视频的 PyAV／TorchCodec 时间戳解码；**不是 SmolVLA 模型前向或训练验收**。失败会替换旧的成功状态。

## 2. 显式准备数据和模型

```powershell
# 只有 prepare 显式访问 Hub 下载训练资产。
& $Runner python -m $EntryModule --config $Config prepare
```

步骤：

1. 解析数据、基础模型、VLM 骨干 revision 为完整提交号，下载固定 snapshot；骨干仅下载配置／tokenizer，完整 VLM 权重来自 SmolVLA checkpoint。
2. 读取真实 metadata、轨迹和任务；按任务分组，以固定种子划分完整轨迹，约 20% 留出。每个任务至少一条训练和一条验证，不随机拆分相邻帧。
3. **只从训练轨迹的原始 state/action 重算统计量**，不使用含验证数据的全局 stats。视觉保持基础模型的 IDENTITY 归一化。
4. 抽查开头／中间／末尾样本的全部相机与语言标签；不是全量坏帧扫描，后续坏帧仍报错停止。
5. 成功后原子写入 `prepared.json`：格式版本、冻结配置及指纹、SHA、schema、轨迹划分、训练 stats、资产路径和环境记录。

路径从 TOML 的 `base_dir` 解析，不依赖启动目录；示例缓存为仓库 `.cache/smolvla`，运行产物为本项目 `outputs/smolvla/so100-pickplace`。不把公开数据数值直接解释成实机角度或夹爪单位。

相同配置重复 prepare 复用冻结记录，不跟随 main 更新；改变 batch、步数或资产须用新 run_dir。旧合并配置／prepared 不自动升级，见 [迁移说明](../README.md#旧入口迁移)。

## 3. 正式训练与恢复

```powershell
# 默认每 2,000 步保存并计算留出集 Flow Matching loss，不做环境闭环评估。
& $Runner python -m $EntryModule --config $Config train

# 成功后读取实际输出，而不是假设某个固定步数目录。
$Result = Get-Content -LiteralPath (Join-Path $Run "training-result.json") -Raw | ConvertFrom-Json
if ($Result.status -ne "completed") { throw "training not completed" }
$ModelDir = $Result.checkpoint
```

官方 `lerobot_train.train` 管理梯度更新、优化器、LR 调度、评估和完整训练状态。本项目仅在当前进程／调用期间替换数据工厂、严格权重加载、固定 tokenizer 和 Windows `latest.json` 索引，不修改 site-packages。

一次普通训练前向为每个示范动作块采样噪声和一个流时间，构造带噪动作并计算速度场监督损失，随后更新可训练参数。推理才执行多步流积分；`training.steps` 的优化器更新次数与 `num_steps=10` 的动作生成积分次数含义不同。训练与推理的并排说明、噪声作用和公式见[模型原理第 7 节](../../research/smolvla-architecture.md#7-flow-matching-训练与推理)。

默认 `max_eval_samples = 0`，每次验证遍历全部留出帧。本次冻结的公开数据有 10 条验证轨迹、3,759 帧。设置正数上限时，按轨迹均衡分配样本，并在每条轨迹内分散选取前、中、后帧；上限小于验证轨迹数会报错。`validation-sampling.json` 记录实际参与验证的帧数和每条轨迹的计数。限量验证包装为 `Subset`，避免上游按任务再次截取最前面的帧。

验证上限也是冻结配置的一部分；旧 `prepared.json` 或 checkpoint 不能与改变后的配置混用。修改后须在新 run_dir 重新 prepare，并保留旧运行的产物。

中断恢复须明确选择**同一运行**的完整 checkpoint，可传 checkpoint 步数目录或其中的 `pretrained_model`：

```powershell
# 由人选择已有完整产物，不只给权重文件；路径不是默认固定步数。
$Checkpoint = Read-Host "输入本运行完整 checkpoint 路径"
& $Runner python -m $EntryModule --config $Config train --resume-from $Checkpoint
```

恢复回读优化器、调度器、随机状态和训练步数，核对 `experiment.json`、冻结版本、配置指纹与原运行输出目录。新训练拒绝覆盖已有 train 目录；初版只恢复剩余步数，不通过改配置延长已完成运行。不要直接用上游 CLI 重放 train_config.json，否则缺失本实验随机轨迹划分和训练侧 stats 适配。

多 worker 视频 I/O 与 GPU 非确定性可能影响逐位复现。正式 GPU 验收应额外做中断／恢复测试，不能用替身单测代替。另需短烟测时复制 TOML、改新 run_dir 和步数／频率／warmup，默认配置仍为完整微调。

## 4. 交给 inference 的文件

- `prepared.json`：原样保留；携带训练身份、schema、划分、SHA 和训练侧统计量。
- `training-result.json` 中指明的完整模型目录：`config.json`、`model.safetensors`、预／后处理 JSON、它们引用的全部状态文件及 `experiment.json`。可复制并重命名目录。
- 冻结数据 snapshot（meta／data／videos）、骨干配置／tokenizer snapshot；需基线比较时另带基础模型 snapshot。

**推理不需要训练 `.venv`、training_state 或 train_config.json；训练恢复仍需要后两者。** 复制 snapshot 时必须带齐实际文件，不能留下仅在原机器可解析的链接。inference 配置显式重定位资产，保持原准备记录和归一化状态不变，详见 [推理交接](../inference/README.md#2-配置输入与资产交接)。不自动打包、上传或覆盖另一机器。

输出另包括 `train/checkpoints/<step>/training_state/` 和 `training-result.json`；训练完成会记录 `offline_inference_verified=false`，不自动宣称离线或闭环验收通过。

## 验证状态与一手依据

2026-10-13：本机 Python 3.12.11、NumPy 2.2.6、PyTorch 2.9.1，仅用于离线 CPU 适配测试；运行入口严格要求锁定的 LeRobot 0.6.1／PyTorch 2.10 等版本。本次迁移完成无网络测试、源码编译、独立依赖锁检查；**未执行 Windows setup、4090 真实模型训练／恢复，也未重跑硬件测试**。

- [LeRobot 0.6.1 训练源码](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/lerobot_train.py)：本项目复用的训练、评估与保存接口。
- [数据工厂](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/factory.py)：时间窗口和默认划分；本项目另行冻结随机轨迹划分／训练统计。
- [SmolVLA 官方说明](https://huggingface.co/docs/lerobot/v0.6.1/smolvla)、[论文](https://arxiv.org/abs/2506.01844)：模型微调与架构，不据此推断本机成功率。

公开数据可能与基础模型预训练重叠，单任务实验不证明语言泛化；黑臂公开数据不证明白臂／单相机迁移。真机阶段另采集同步示范并验证动作单位、校准、控制链和停止机制。
