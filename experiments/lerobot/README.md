# SO-101 / LeRobot Windows 实验环境

本实验为幻尔 SO-ARM101 标准版（一主臂、一从臂、一个摄像头）准备遥操作、采集与 ACT 学习环境。Windows 原生运行，不依赖 ROS 2。硬件与基础软件分别验收。

## 版本与范围

配置日期：2026-10-11。项目 Python 范围为 `>=3.12,<3.14`，即 3.12、3.13；本机使用已有 `C:\mysoftware\python312\python.exe`（3.12.6）。**允许解析 Python 3.13 不等于已在 3.13 上通过运行测试。**

| 组件 | 选择 |
| --- | --- |
| LeRobot | PyPI 发行版 0.6.1，`core_scripts,training,feetech` |
| PyTorch / torchvision | 2.10.0 / 0.25.0，官方 CUDA 12.8 wheel |
| TorchCodec | 0.10.0 |
| 视频共享库 | FFmpeg 8.1 系列 BtbN Windows shared 月末构建 `autobuild-2026-09-30-13-08`，归档哈希见 `ffmpeg-source.json` |
| 环境管理 | uv；完整依赖锁在 `uv.lock` |

独立环境位于本目录 `.venv`；下载缓存与 FFmpeg 在仓库根目录 `.cache`，均不提交。不会替换系统 Python 或永久修改 PATH。无需单独安装完整 CUDA Toolkit，本实验使用 wheel 附带的运行库和现有 NVIDIA 驱动。

## 安装与使用

在仓库根目录的 PowerShell 中：

```powershell
.\experiments\lerobot\setup.ps1 -Python C:\mysoftware\python312\python.exe
.\experiments\lerobot\run.ps1 python check_environment.py
.\experiments\lerobot\run.ps1 lerobot-train --help
```

其他机器可传入自己的 Python 3.12/3.13 路径。`setup.ps1` 使用锁文件安装，并下载、校验、解压 FFmpeg。下载需要数 GiB 空间和网络流量。FFmpeg 使用固定构建地址与 SHA-256，不随 `latest` 更新。已有归档只有哈希匹配才复用；缓存缺失或损坏时先下载到独立临时文件，校验通过后才替换缓存。下载中断或校验失败会清理本次临时文件并停止，修复网络后可以直接重跑；校验失败时仍须核对来源，不能跳过校验。

该 FFmpeg 归档是 2026-09-30 的月末构建；[BtbN 保留政策](https://github.com/BtbN/FFmpeg-Builds#release-retention-policy)规定月末构建保留两年，普通日构建只保留 14 天。因此固定地址不代表永久托管：归档到期或被移除前，应保存经过相同哈希验证的副本，或重新核对、验收新构建后更新清单。保留 `.cache/ffmpeg/ffmpeg.zip` 可供本机后续复用。

`run.ps1` 只为当前命令临时增加共享 FFmpeg 与虚拟环境目录。系统原有静态 FFmpeg 命令不能代替 TorchCodec 所需 DLL，因此日常运行也应使用此入口。

## 无硬件验收

`check_environment.py` 不打开串口、不连接机器人、不打开摄像头、不上传数据：

1. 验证 CUDA 可用，并记录实际 GPU、Python 和依赖版本。
2. 导入 SO101 驱动，执行校准、遥操作、采集与训练 CLI 的 `--help`。
3. 用 PyAV 编码合成 MP4，再通过 LeRobot 的 PyAV 和 TorchCodec 后端按时间戳解码。
4. 使用单视角合成输入，运行缩小版 ACT 的 GPU 前向、反向和参数更新，保存、加载模型并比较推理结果。

种子 42；批量 2、图像 64×64、动作维度 6、动作块长 4、模型维度 64，均为**软件验收设定**。关闭预训练视觉权重下载。此检查不是默认规模 ACT 训练、真实数据集训练或抓取性能验证。

结果写入 `outputs/environment-check.json`，只有整套检查通过才写出报告；复测失败时不可把旧报告当作新验收结果。

### 本机验收记录（2026-10-11）

Windows 11、Python 3.12.6、RTX 3060 Ti、驱动 595.95；PyTorch 实际版本 `2.10.0+cu128`、torchvision `0.25.0+cu128`。依赖一致性检查通过（84 个已安装包），锁定安装脚本重复执行成功。

四个 CLI 帮助入口、PyAV 编码、PyAV/TorchCodec 时间戳解码、缩小版 ACT 的 GPU 前向/反向/更新及保存加载比较全部通过。合成批次损失为 29.084135，仅用于确认数值有限，不代表任务性能。

验收过程中修正了测试脚本的旧版 SO101 导入路径，并在删除临时视频前释放解码缓存以避免 Windows 文件占用。未修改已安装的 LeRobot 源码。Codex 受限执行模式会阻止 uv 解压或 CLI 启动器解析路径，本次安装和 CLI 验收通过权限提升执行；这不是 LeRobot 导入或 GPU 兼容性失败。

同日后续修复将 FFmpeg 固定为上述月末构建：实际下载的 SHA-256、解压目录、共享 DLL 与 `ffmpeg -version` 启动检查通过。安装脚本的五个模拟场景通过：下载中断后重试、有效缓存复用、损坏缓存恢复、错误哈希拒绝及失败后重试。上面的 GPU/ACT 验收记录对应修复前的 FFmpeg 归档；本次未重新执行 CUDA/ACT 验收。

尚未验证 Python 3.13 运行、真实数据训练、摄像头采集、串口通信与机械臂动作。

## 厂商源码与后续

详见 [配套源码检查](vendor-source-review.md)。厂商包基于 0.3.4，不直接覆盖此环境。到货后仍需核对端口、舵机身份、校准、限位、相机后端及遥操作延迟。一个摄像头应只声明一个相机特征，并在采集与推理时保持名称和设置一致；不照抄手册的双摄像头示例。

下一阶段先验收单相机和小范围遥操作，再录少量短轨迹，检查时间戳、状态与动作含义，最后进行真实数据的 ACT 训练。尚无机器人连接验收时，不运行舵机初始化、校准或策略驱动命令。

## 来源

以下核实于 2026-10-11：

- [LeRobot 0.6.1 依赖定义](https://github.com/huggingface/lerobot/blob/v0.6.1/pyproject.toml)：对应本环境发行版。
- [上游安装说明](https://huggingface.co/docs/lerobot/en/installation)：滚动文档，命令以锁定版本为准。
- [TorchCodec 0.10 安装与兼容性](https://github.com/pytorch/torchcodec/tree/v0.10.0)：Windows 需要 FFmpeg shared DLL。
- [FFmpeg 官方下载入口](https://ffmpeg.org/download.html)：Windows 构建分发链接；实际采用 [BtbN 构建](https://github.com/BtbN/FFmpeg-Builds)。
