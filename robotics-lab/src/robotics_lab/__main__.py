import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="机器人交互实验室")
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    commands.add_parser("doctor")
    commands.add_parser("catalog")
    run = commands.add_parser("simulate")
    run.add_argument("experiment_id")
    run.add_argument("--duration", type=float)
    run.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)
        return 0
    if args.command == "doctor":
        from .diagnostics import viewer_capability
        result = viewer_capability()
    elif args.command == "catalog":
        from .catalog import catalog
        result = [item.public() for item in catalog().values()]
    else:
        from .catalog import get_experiment
        from .physics import simulate
        result = simulate(get_experiment(args.experiment_id), args.duration)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
