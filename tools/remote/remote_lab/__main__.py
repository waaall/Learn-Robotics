"""无训练依赖的远程入口；只有 check 联网，其余命令仅输出配置或手动操作指引。"""

import argparse
import json
from pathlib import Path

from .config import load_config
from .inspection import check_server, session_script
from .transport import command_text, ssh_args


def main(argv=None):
    parser = argparse.ArgumentParser(description="Windows 训练服务器配置与只读盘点，不自动部署")
    parser.add_argument("--config", type=Path, required=True, help="不提交的本地 JSON 机器配置")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="本地校验并显示解析后的配置；不联网")
    ssh = commands.add_parser("ssh-command", help="打印手动登录命令；不执行")
    ssh.add_argument("--first-use", action="store_true", help="打印需人工核对并确认新主机指纹的命令")
    ssh.add_argument("--shell", choices=("auto", "powershell", "posix"), default="auto")
    commands.add_parser("session", help="打印服务器 PowerShell 会话变量；不执行、不安装")
    commands.add_parser("check", help="通过 SSH 只读盘点 OS、GPU、路径、工具和版本")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command == "validate":
            print(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2))
        elif args.command == "ssh-command":
            powershell = None if args.shell == "auto" else args.shell == "powershell"
            print(command_text(ssh_args(cfg, interactive=True, first_use=args.first_use), powershell=powershell))
        elif args.command == "session":
            print(session_script(cfg), end="")
        else:
            report = check_server(cfg)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            # 盘点成功但安装前置条件不齐，和 SSH／协议失败使用不同退出码。
            if not report["ready_for_setup"]:
                parser.exit(2)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"远程操作停止：{error}\n")


if __name__ == "__main__":
    main()
