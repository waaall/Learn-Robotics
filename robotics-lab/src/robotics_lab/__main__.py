"""共享命令行入口；原生与容器使用相同配置和单进程应用服务。"""

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="机器人交互实验室")
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve")
    server.add_argument("--host")
    server.add_argument("--port", type=int)
    commands.add_parser("doctor")
    commands.add_parser("catalog")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--url", help="默认访问当前配置的本机应用端口")
    smoke.add_argument("--output", type=Path)
    run = commands.add_parser("simulate")
    run.add_argument("experiment_id")
    run.add_argument("--duration", type=float)
    run.add_argument("--output", type=Path)
    args = parser.parse_args()
    # 当前课程为小矩阵计算，避免每个查看器子进程创建大量 BLAS 线程。
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        from .config import Settings
        settings = Settings.from_env(host=args.host, port=args.port)
        uvicorn.run(create_app(settings=settings), host=settings.host, port=settings.port, workers=1,
                    ws_max_size=64 * 1024 * 1024)
        return 0
    if args.command == "doctor":
        from .diagnostics import viewer_capability
        result = viewer_capability()
    elif args.command == "catalog":
        from .catalog import catalog
        result = [item.public() for item in catalog().values()]
    elif args.command == "smoke":
        from .config import Settings
        from .smoke import check_service
        settings = Settings.from_env()
        result = check_service(args.url or f"http://127.0.0.1:{settings.port}")
        args.output = args.output or settings.data_dir / "validation/smoke.json"
    else:
        from .catalog import get_experiment
        from .physics import simulate
        result = simulate(get_experiment(args.experiment_id), args.duration)
    output = getattr(args, "output", None)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    if args.command == "doctor" and not result["available"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
