# Inference：SmolVLA 离线推理与比较

## 范围与独立性

入口只有 `plan / infer / compare`。从留出轨迹的当前观测与语言生成动作块，保存预测、掩码误差和延迟；**不下载训练资产、不更新参数、不连接机械臂／实时摄像头、不发送任何动作**。真机执行留到下一阶段。

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

这保留了已有离线推理方式，不新增实时异步队列、动作执行、插值、控制器、相机采集或机器人驱动。

输出：

- `<baseline 或 checkpoint>/report.json`：状态、协议、模型、各轴误差、计时、显存和限制。
- 同目录 `actions.npz`：预测／示范动作块、padding mask、全局帧号；`samples.csv`：轨迹编号及分阶段计时。
- `comparison.json`：微调前后差值和两份报告来源。负误差差值只说明离线拟合改善，不设置无依据的通用通过阈值。

## 验证状态与依据

2026-10-13：迁移后的 CPU 替身测试覆盖完整离线文件流程、重命名模型目录、无训练状态推理、资产重定位、固定噪声、padding 和基线比较；隔离复制后的 plan 无需训练／硬件项目，也不导入重依赖。**这不是真实 SmolVLA 前向验证；Windows 安装、4090 实际模型推理／延迟及真机执行均未验收。**

[SmolVLA 动作生成源码（LeRobot 0.6.1）](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/smolvla/modeling_smolvla.py)对应显式噪声与动作块接口；[处理器源码](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/smolvla/processor_smolvla.py)对应预／后处理及归一化。这是锁定版本的适配，不承诺兼容任意更新版。

公开数据可能已出现在基础模型预训练中；离线误差不证明闭环抓放成功、语言泛化或黑臂到白臂／单相机的迁移。下一阶段再接相机、采自有示范并讨论真机控制与停止机制。
