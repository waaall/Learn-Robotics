"""Read-only identity/ID/position check. Never moves or configures the arms."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from hardware import ARMS, probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=["both", *ARMS], default="both")
    parser.add_argument("--details", action="store_true", help="Also read goal, torque and raw motor telemetry")
    args = parser.parse_args()
    report = {"timestamp": datetime.now().astimezone().isoformat(), "read_only": True, "devices": []}
    failed = False
    for arm in ARMS if args.arm == "both" else [args.arm]:
        try:
            result = probe(arm, include_status=args.details)
            report["devices"].append(result)
            print(f"{arm} {result['port']} serial={result['serial']}")
            for m in result["motors"]:
                print(f"  ID {m['id']} {m['joint']:14} model={m['model']} position_raw={m['position_raw']} torque={m['torque_enabled']} mode={m['mode']}")
                if m.get('packet_errors'):
                    failed = True
                    print(f'    Motor error bits: {m["packet_errors"]}')
            if args.details:
                for joint, state in result['status'].items():
                    print(f'  {joint}: {state}')
                    if state['comm'] or state['packet_error'] or 'read_error' in state:
                        failed = True
        except Exception as exc:
            failed = True
            report["devices"].append({"arm": arm, "error": str(exc)})
            print(f"FAIL {arm}: {exc}")
    report["passed"] = not failed
    dest = Path(__file__).parent / "outputs" / "communication-check.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{'PASS' if not failed else 'FAIL'}; report: {dest}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
