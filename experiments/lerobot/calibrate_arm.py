"""Interactive calibration using LeRobot 0.6.1; writes offsets and limits, no motion targets."""
import argparse
from dataclasses import asdict
from datetime import datetime
import importlib.metadata
import json
from pathlib import Path
import shutil

from hardware import ARMS, probe, resolve_port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=ARMS)
    parser.add_argument("--dry-run", action="store_true", help="Resolve board identity and show paths; do not open serial port")
    args = parser.parse_args()
    if importlib.metadata.version("lerobot") != "0.6.1":
        raise RuntimeError("This wrapper was reviewed for LeRobot 0.6.1; review again before upgrading.")
    port = resolve_port(args.arm)
    directory = Path(__file__).parent / "outputs" / "calibration" / args.arm
    device_id = ARMS[args.arm]["id"]
    print(f"Arm={args.arm}, port={port}, serial={ARMS[args.arm]['serial']}")
    print(f"Calibration file: {directory / (device_id + '.json')}")
    if args.dry_run:
        print("DRY RUN: no serial access or writes")
        return
    state = probe(args.arm)
    if any(m["torque_enabled"] != 0 for m in state["motors"]):
        raise RuntimeError("A motor is holding torque. Support the arm and stop the other controller before calibration.")
    print("Support the arm. Calibration disables torque and WRITES operating mode, homing offsets and range limits.")
    input("Press ENTER when ready to start manual calibration (Ctrl+C to cancel)...")
    # Import lazily so dry-run remains free of device construction and register access.
    if args.arm == "leader":
        from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
        device = SO101Leader(SO101LeaderConfig(port=port, id=device_id, calibration_dir=directory, use_degrees=True))
    else:
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
        device = SO101Follower(SO101FollowerConfig(port=port, id=device_id, calibration_dir=directory, use_degrees=True))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = directory / "backups" / stamp
    backup.mkdir(parents=True)
    if device.calibration_fpath.exists():
        shutil.copy2(device.calibration_fpath, backup / "previous-file.json")
    try:
        # Do not call device.connect(): normal follower configuration enables torque.
        device.bus.connect()
        original = {name: asdict(value) for name, value in device.bus.read_calibration().items()}
        (backup / "motor-calibration-before.json").write_text(json.dumps(original, indent=2), encoding="utf-8")
        device.calibrate()
        if not device.bus.is_calibrated:
            raise RuntimeError("Calibration register readback does not match the saved calibration")
        print("PASS: calibration saved and motor registers match.")
    finally:
        # No Goal_Position writes or torque enabling. Close even if the handshake failed.
        if device.bus.port_handler.is_open:
            device.bus.disconnect(disable_torque=False)


if __name__ == "__main__":
    main()
