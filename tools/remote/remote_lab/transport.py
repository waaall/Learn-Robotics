"""生成安全的 SSH 参数和 PowerShell 字面量；检查不依赖远程命令参数是否被 shell 接收。"""

import base64
import gzip
import json
import os
import re
import shlex
import subprocess

from .config import RemoteConfig


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def ssh_args(cfg: RemoteConfig, *, interactive=False, first_use=False):
    if first_use and not interactive:
        raise ValueError("首次信任主机只能使用人工交互连接")
    args = ["ssh", "-o", f"StrictHostKeyChecking={'ask' if first_use else 'yes'}",
            "-o", f"BatchMode={'no' if interactive else 'yes'}",
            "-o", f"ConnectTimeout={cfg.ssh.connect_timeout_seconds}"]
    if not interactive:
        args.append("-T")
    if cfg.ssh.user:
        args.extend(["-l", cfg.ssh.user])
    if cfg.ssh.port is not None:
        args.extend(["-p", str(cfg.ssh.port)])
    if cfg.ssh.identity_file:
        args.extend(["-i", str(cfg.ssh.identity_file), "-o", "IdentitiesOnly=yes"])
    # host 始终作为单独参数传递，不通过 shell 拼接命令。
    args.append(cfg.ssh.host)
    return args


def command_text(args, *, powershell=None):
    if powershell is None:
        powershell = os.name == "nt"
    return "& " + " ".join(ps_literal(arg) for arg in args) if powershell else shlex.join(args)


def encoded_stdin(script):
    if len(script.encode("utf-8")) > 30000:
        raise ValueError("检查脚本及路径过长，请缩短机器路径")
    # 大量 stdin 预先送入 Windows SSH 会话可能阻塞；压缩并分段，不落地临时脚本。
    payload = base64.b64encode(gzip.compress(script.encode("utf-8"), mtime=0)).decode("ascii")
    bootstrap = (
        "$b=[Convert]::FromBase64String($env:__RemoteLabPayload);"
        "$m=[IO.MemoryStream]::new($b);"
        "$z=[IO.Compression.GZipStream]::new($m,[IO.Compression.CompressionMode]::Decompress);"
        "$r=[IO.StreamReader]::new($z,[Text.Encoding]::UTF8);"
        "&([scriptblock]::Create($r.ReadToEnd()))"
    )
    # 环境变量只属于此短期登录进程及其子进程，不写机器／用户环境配置。
    lines = ["$env:__RemoteLabPayload = ''"]
    lines.extend(f"$env:__RemoteLabPayload += '{payload[i:i + 1024]}'" for i in range(0, len(payload), 1024))
    encoded = base64.b64encode(bootstrap.encode("utf-16-le")).decode("ascii")
    lines.extend([f"powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}",
                  "exit $LASTEXITCODE"])
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def decode_report(output, marker):
    # 只接受独立完整的协议行；登录提示、脚本回显和退出码 0 都不代表检查已执行。
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    pattern = re.compile(re.escape(marker) + r":([A-Za-z0-9+/=]+):END")
    matches = [match.group(1) for line in clean.splitlines() if (match := pattern.fullmatch(line.strip()))]
    if len(matches) != 1:
        raise RuntimeError("没有收到唯一完整的检查报告；可能是远程 shell 未执行脚本，不能视为成功")
    try:
        report = json.loads(base64.b64decode(matches[0], validate=True).decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise RuntimeError("远程检查报告编码损坏") from error
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise RuntimeError("远程检查报告协议不匹配")
    if report.get("status") != "collected":
        raise RuntimeError(f"远程检查失败：{report.get('error', '没有错误说明')}")
    checks = report.get("checks")
    if not isinstance(checks, dict) or not checks or any(type(v) is not bool for v in checks.values()):
        raise RuntimeError("远程检查缺少有效的部署前置条件")
    if type(report.get("ready_for_setup")) is not bool or report["ready_for_setup"] != all(checks.values()):
        raise RuntimeError("远程检查前置条件与结论不一致")
    return report


def run_readonly(cfg: RemoteConfig, script, marker):
    try:
        result = subprocess.run(ssh_args(cfg), input=encoded_stdin(script),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=cfg.ssh.check_timeout_seconds, check=False)
    except FileNotFoundError as error:
        raise RuntimeError("当前客户端未找到 OpenSSH 的 ssh 命令") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("SSH 检查超时；未安装、同步或启动训练，请检查网络及服务器 shell") from error
    output = result.stdout.decode("utf-8", errors="replace")
    if result.returncode:
        # 子 PowerShell 失败时保留结构化错误；不能只显示无关的启动 profile 提示。
        if marker + ":" in output:
            try:
                decode_report(output, marker)
            except RuntimeError as error:
                raise RuntimeError(f"远程检查失败（退出码 {result.returncode}）：{error}") from error
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"SSH 失败（退出码 {result.returncode}）：{message or '检查认证、网络和主机指纹'}")
    return decode_report(output, marker)
