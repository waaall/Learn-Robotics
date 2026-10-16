# 独立实验项目

| 项目 | 职责 | 第一版边界 |
| --- | --- | --- |
| [lerobot](lerobot/README.md) | SO-101 初始化、通信、校准、遥操作、采集 | 保留已验证的硬件流程 |
| [training](training/README.md) | 公开数据准备、SmolVLA 微调、验证 loss、完整状态恢复 | 不连接机械臂，不提供推理命令 |
| [inference](inference/README.md) | 离线预测比较、单夹爪视角实时输入诊断 | 不更新参数，不执行真机动作 |

以上三个项目是**同一 Git 仓库中的独立部署项目**，不是三个新仓库。每个项目各有 `pyproject.toml`、`uv.lock`、`.venv`、`setup.ps1`、`run.ps1`、环境预检和 README；安装其中一个不会同步另外两个的环境。第一版锁文件针对 Windows x64、Python 3.12/3.13、CUDA 12.8 PyTorch wheel；其他平台不能据此宣称已支持。

另有独立的 [MuJoCo 物理计算实验](mujoco_physics/README.md)，固定 MuJoCo 3.16.0，研究执行器、关节耦合、重力和接触计算。它使用自己的 `pyproject.toml`、`uv.lock` 和 `.venv`，以 Python 模块命令运行；已在 macOS arm64 验证，不依赖上述 Windows 部署脚本，不连接硬件。

## 共享代码与机器配置

- `packages/smolvla_common`：必要的配置记录、数据／模型协议、处理器、统计与框架适配。由 training、inference 分别通过本地 path dependency 安装进自己的环境；两项目不互相导入。
- `tools/windows_runtime`：训练和推理的安装／启动脚本及固定哈希的 FFmpeg 清单。硬件项目保留原安装逻辑和锁文件，不借本次迁移改变控制行为。
- [tools/remote](../tools/remote/README.md)：客户端仅需标准库与 OpenSSH；校验本地机器配置、打印登录／会话命令、显式只读盘点。
- 实际服务器信息放在 `tools/remote/configs/*.local.json`，被 Git 忽略；通用源码和文档不写死个人 IP、账号或安装目录。

不要建 uv workspace 或共享 `.venv`。uv workspace 共享锁文件；需要不同环境时官方建议使用独立项目与 path dependencies。这是本仓库的部署选择，不是 LeRobot 强制的目录结构。[uv 官方说明](https://docs.astral.sh/uv/concepts/projects/workspaces/#when-not-to-use-workspaces)

上游 LeRobot 0.6.1 把 `training`、`dataset`、`smolvla` 与硬件 extras 分开。本仓库 training 声明 `training,smolvla`，inference 默认声明 `dataset,smolvla`，不安装 W&B 或舵机 SDK；仅显式选择 `--extra live` 时增加 Feetech SDK 与串口依赖，用于读取从臂。LeRobot 本体仍包含训练模块，不能把“不启用训练入口”表述成“框架绝无训练代码”。硬件项目原有 ACT 小模型软件验收及历史依赖暂保留，不属于新增的正式训练项目。[上游依赖定义](https://github.com/huggingface/lerobot/blob/v0.6.1/pyproject.toml)

## 流程和文件交接

1. training：`plan → prepare → train`，需要恢复时显式 `--resume-from`。
2. inference：读取 `prepared.json`、固定数据／骨干资产、基础模型或明确指定的完整训练模型；`plan → infer → compare`。
3. 两个环境可部署在不同机器；交接**文件**，不要求复制 `.venv` 或安装对方项目。推理输入路径、资产重定位和输出目录由独立 TOML 配置。
4. 真机执行留到下一阶段；离线拟合误差不替代抓放成功率、白臂迁移、相机和停止机制验收。

示例推理配置引用同一 checkout 下的训练产物，仅为方便填写；代码不扫描训练目录，也不默认选择最新 checkpoint。跨机器需复制同版本完整资产并显式填写路径，不能只拿一个权重文件。

### 旧入口迁移

旧的 `smolvla_lab` 合并入口和 `setup.ps1 -SmolVLA` 不再使用；改为两个独立项目的 setup 和模块入口。新准备记录为 `manifest_version=1`，冻结配置不再包含推理参数。旧合并配置／prepared 文件不能直接套用：**保留原产物，在新 run_dir 重新准备，不自动删除、改写或升级旧运行。** 新推理消费本版本训练导出的完整模型及协议记录。

## 本地开发验证

仓库根目录执行，使用已安装 NumPy／PyTorch 的 Python 3.12+：

```shell
python tools/test_offline.py
```

该入口仅给开发测试组织源码路径，不是部署捷径；生产共享包由各项目的 uv 安装。测试覆盖协议、官方训练循环替身、CPU 推理适配、资产重定位、独立复制后的 plan、环境和 SSH 边界，不打开串口、摄像头或网络。安装后也可分别运行各项目的 `python -m unittest discover -v`。

2026-10-13 本机验证：80 项无网络／无硬件测试通过；三份 uv 锁文件分别通过离线一致性检查；源码编译与空白检查通过；共享包在临时隔离环境中 editable 安装成功，两个项目的 plan 无需 PYTHONPATH 可运行。硬件锁文件、依赖和执行代码保持原状（setup 仅更新说明注释）。

本次迁移时的验证范围见各项目 README；4090 上的训练／恢复与闭环控制尚未验收，未再次连接服务器。2026-10-13 后续在本机 RTX 3060 Ti 完成独立推理环境安装，以及单夹爪相机＋真实从臂状态的 10 次 SmolVLA 推理，动作仅落盘；新增适配后 90 项无硬件测试通过，具体延迟与限制见 inference README。
