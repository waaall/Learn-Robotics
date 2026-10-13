"""离线推理入口只读取模型／数据文件，不导入训练项目、不更新参数、不执行机器人动作。"""

import argparse
import json
from pathlib import Path

from .config import load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="SmolVLA 离线推理与比较；不连接机械臂")
    parser.add_argument("--config", type=Path, required=True, help="独立推理 TOML 配置")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="打印本机输入／输出和评估配置，不联网或导入模型")
    infer = commands.add_parser("infer", help="基线或明确指定的完整模型，仅生成动作文件")
    choice = infer.add_mutually_exclusive_group()
    choice.add_argument("--baseline", action="store_true")
    choice.add_argument("--checkpoint", type=Path, help="本机模型目录，不要求训练状态文件")
    compare = commands.add_parser("compare", help="比较明确指定且同协议的完成报告，不加载模型")
    compare.add_argument("--baseline-report", type=Path, required=True)
    compare.add_argument("--trained-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        job = load_config(args.config)
        if args.command == "plan":
            print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
        elif args.command == "infer":
            from .engine import infer
            print(infer(job, baseline=args.baseline, checkpoint=args.checkpoint))
        else:
            from smolvla_common.protocol import compare_reports, read_json, write_json
            result = compare_reports(read_json(args.baseline_report), read_json(args.trained_report))
            result["report_sources"] = {"baseline": str(args.baseline_report.resolve()),
                                        "trained": str(args.trained_report.resolve())}
            write_json(job.output_dir / "comparison.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, KeyError, TypeError, OSError, ImportError) as error:
        parser.exit(1, f"离线推理停止：{error}\n")


if __name__ == "__main__":
    main()
