# Windows 远程配置与只读检查

客户端独立工具，针对 Windows 原生训练／离线推理服务器。只提供 `validate / ssh-command / session / check`：**不安装、同步、下载数据／模型、启动训练或执行机械臂动作**。代码不固定 IP、账号、服务器目录或某个实验目标。

## 1. 私有机器配置

在**客户端**仓库 `tools/remote` 目录操作，仅需 Python 3.12+ 和 OpenSSH Client，不需要 LeRobot、PyTorch 或 uv。以下 `python` 可替换为 `py -3.12`／`python3.12`。

```powershell
# 第一次创建；已有文件不覆盖。编辑后把全部 CHANGE_ME 替换为自己的信息。
if (!(Test-Path configs/remote.local.json)) {
    Copy-Item configs/remote.example.json configs/remote.local.json
}
git check-ignore -v configs/remote.local.json
git ls-files -- configs/remote.local.json
```

最后一条应无输出。`configs/*.local.json` 全部忽略；切换推理目标可从 `configs/inference.example.json` 创建另一个私有文件，例如 `configs/inference.local.json`。不要提交实际机器配置或用 `git add -f`；gitignore 不能撤回已跟踪内容。[Git 官方说明](https://git-scm.com/docs/gitignore)

当前配置格式是 **schema_version=2**；旧格式的实验字段须按新模板迁移为 `project` 目标，不能照搬旧命令。文件 UTF-8（可带 BOM），JSON 不支持注释。

| 字段 | 含义／限制 |
| --- | --- |
| `ssh.host` | IP、域名或 SSH Host 别名，不能包含 user@host／命令参数 |
| `ssh.user` | 用户名；空字符串继承 SSH 配置 |
| `ssh.port` | 整数端口；null 继承 SSH 配置／默认端口 |
| `ssh.identity_file` | **客户端**密钥路径；空则使用现有配置或 agent，相对路径基于 JSON 所在目录 |
| `ssh.connect_timeout_seconds` | 连接超时 1–120 秒 |
| `ssh.check_timeout_seconds` | 整次盘点超时，大于连接超时且最多 600 秒 |
| `windows.repo_dir` | **服务器**仓库根目录，带盘符的绝对路径 |
| `windows.python_executable` | **服务器**基础 Python .exe，不是另一个项目的虚拟环境 |
| `project.directory` | 目标项目相对仓库根目录的路径，如 experiments/training 或 experiments/inference |
| `project.module` | Python 入口模块名，如 smolvla_training／smolvla_inference；不允许命令参数 |
| `project.config` | TOML 相对**目标项目**的路径，不是相对仓库 |
| `project.required_files` | 盘点的额外**仓库相对**文件列表，含目标入口、共享包和公共 Windows 脚本 |

程序另会检查目标项目 pyproject／uv.lock／setup／runner 和配置文件。所有相对目标路径禁止 `..`；Windows 绝对路径支持空格、汉字和单引号，不支持 UNC／设备路径或自动展开服务器环境变量。目标项目和机器位置分开，可在同服务器安装训练和推理的独立环境，也可换不同服务器。

**不保存密码、私钥正文、Hub token 或任意远程启动命令。** identity_file 只引用文件，不读取密钥内容。也可使用本机 SSH config 的 Host 别名，user 留空、port=null、identity_file 留空，避免冲突；命令行显式选项优先于 SSH config。[OpenSSH 参数说明](https://man.openbsd.org/ssh_config)

## 2. 本地校验和手动 SSH

仍在客户端 `tools/remote`：

```powershell
# 不联网、不导入 ML 框架；validate 不证明远端文件存在。
python -m remote_lab --config configs/remote.local.json validate

# 仅打印命令。首次登录前从可信服务器控制台核对主机公钥指纹。
python -m remote_lab --config configs/remote.local.json ssh-command --first-use
python -m remote_lab --config configs/remote.local.json ssh-command

# 唯一联网入口：显式只读盘点，不改变环境或代码。
python -m remote_lab --config configs/remote.local.json check

# 打印给服务器 PowerShell 粘贴的路径变量块，不在客户端执行。
python -m remote_lab --config configs/remote.local.json session
```

手动执行打印的登录命令，不把输出直接喂给 Invoke-Expression。默认按客户端平台打印，也可加 `--shell powershell` 或 `--shell posix`。

首次可信控制台可查看服务器公钥指纹：

```powershell
Get-ChildItem "$env:ProgramData\ssh\ssh_host_*_key.pub" | ForEach-Object {
    & ssh-keygen -lf $_.FullName
}
```

不要把未经核验的 ssh-keyscan 当作信任依据。首次交互命令用 StrictHostKeyChecking=ask，由人确认；只读盘点固定 yes 和 BatchMode=yes，未知／变更密钥、不可用认证会失败，不弹密码框或自动信任。[OpenSSH 安全选项](https://man.openbsd.org/ssh_config)

`check` 读取 OS／内存／本地盘余量、GPU／驱动、基础 Python、**所选项目**已有 `.venv` 的包元数据、uv／Git、仓库 HEAD／未提交文件和缺失文件。不导入 torch、不 fetch／pull，Git 禁用可选索引写锁。报告包含机器信息，分享前脱敏。

- 退出码 0：收到有效报告，安装前置条件齐备。
- 退出码 2：报告收到，但 checks 存在缺项，例如 uv 不在当前会话 PATH 或代码未同步。
- 退出码 1：配置、认证、命令或报告协议失败，不能误报通过。

`ready_for_setup` **仅说明可以开始安装**，不证明 CUDA wheel 与驱动运行兼容、磁盘能容纳完整数据、显存足够或模型训练／推理成功。目标项目缺 `.venv` 在安装前是正常情况。

## 3. 服务器显式部署

所需工具：OpenSSH Server（能登录则不重装）、Git、Python 3.12／3.13 x64、uv、现有 NVIDIA 驱动；包与 FFmpeg shared 由各项目 setup 显式安装。完整 CUDA Toolkit／WSL 不是本版安装步骤；最终兼容性由软件预检和真实模型实验确认。uv 安装见 [官方说明](https://docs.astral.sh/uv/getting-started/installation/)。

同步前查看两端 git status 和 HEAD，保留服务器自己的修改；不做 reset --hard 或覆盖式同步。本地未提交／推送文件不会被远端 git pull 获得。需同步目标项目、共享包和公共脚本，不能只复制实验文件夹。

手动 SSH 登录后，在**服务器 PowerShell**粘贴 `session` 输出：生成 `$Repo`、`$Python`、`$Lab`、`$Runner`、`$Config`、`$EntryModule` 并切换目录；**不调用 plan、不解析输出目录、不提前导入未安装的共享包**。

接下来按所选项目文档显式执行 setup／预检／plan，再 [训练](../../experiments/training/README.md)或 [离线推理](../../experiments/inference/README.md)。机器 JSON 留在客户端，不需要上传服务器。远程交互不是调度器：本版不负责断线保活、后台启动、自动恢复、上传或取回产物，长训练前另确认可持续运行方式。

## 实现与验证边界

`remote_lab/config.py` 校验机器／项目参数；`inspection.py` 生成只读盘点和手动会话变量；`transport.py` 管理 SSH 参数、PowerShell 引用和编码报告；`__main__.py` 提供明确入口。测试不联网：

```powershell
python -m unittest -v test_remote_lab
```

Windows OpenSSH 默认 shell 可配置，不能假定 bash 或把 SSH 退出 0 当作命令已执行。[Microsoft 说明](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration) 本工具不改 shell／注册表，经 stdin 在会话中调用独立 PowerShell -NoProfile -NonInteractive -EncodedCommand；编码为 UTF-16LE。[PowerShell 参数文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1#-encodedcommand-base64encodedcommand)

脚本压缩后经本次登录进程的分段环境变量传给子进程，内存解码执行，不落地脚本或永久变量。随机标识的独立编码报告拒绝回显、横幅、重复／损坏报告和远端失败造成的伪成功。此传输曾在目标服务器的 PowerShell 默认 shell 实际只读验证；其他 shell 不保证支持，登录 profile 的原有行为也不是本程序管理范围。

2026-10-13 本次拆分：配置升级为 schema 2，盘点目标不再固定硬件项目；训练／推理模板、会话不提前调用模型环境、路径／命令注入限制经无网络测试。**本次未再次连接服务器，也未安装、同步、下载或训练。** 此前只读报告反映的是拆分前机器状态，不能据此宣称新的两个环境已经部署；部署前重跑 check。
