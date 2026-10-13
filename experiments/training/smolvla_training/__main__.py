"""训练入口：仅 plan、prepare、train；不提供推理或机器人执行子命令。"""

import argparse
import json
from pathlib import Path

from smolvla_common.config import load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="SmolVLA 正式训练；不连接机械臂")
    parser.add_argument("--config", type=Path, required=True, help="训练 TOML 配置")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="只打印训练参数，不导入训练框架或联网")
    commands.add_parser("prepare", help="显式下载并冻结资产，划分完整轨迹并重算训练统计")
    training = commands.add_parser("train", help="官方训练循环与完整状态保存")
    training.add_argument("--resume-from", type=Path, help="明确指定原运行的完整 checkpoint")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command == "plan":
            print(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            from .data import prepare
            manifest = prepare(cfg)
            print(json.dumps({"prepared_manifest": str(cfg.run_dir / "prepared.json"),
                              "revisions": manifest["revisions"], "split": manifest["split"]},
                             ensure_ascii=False, indent=2))
        else:
            from .training import train
            print(train(cfg, args.resume_from))
    except (ValueError, RuntimeError, KeyError, TypeError, OSError, ImportError) as error:
        parser.exit(1, f"训练停止：{error}\n")


if __name__ == "__main__":
    main()
