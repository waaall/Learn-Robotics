"""Interactive 60 Hz teleoperation trial with per-cycle JSONL diagnostics (LeRobot 0.6.1)."""
import argparse
from dataclasses import asdict
from datetime import datetime
import importlib.metadata
import json
import math
from pathlib import Path
import time

from hardware import ARMS, JOINTS, probe, read_motor_status, resolve_port

CALIBRATION_TOLERANCE_TICKS = 32  # Observation tolerance only (~2.8 degrees); never extends goals.
TARGET_MARGIN_TICKS = 24


class TrialStop(RuntimeError):
    """An expected diagnostic stop, reported without a Python traceback."""


class PositionReadError(RuntimeError):
    def __init__(self, device_name, raw, violations):
        self.snapshot = {'device': device_name, 'raw': raw, 'violations': violations}
        super().__init__(f'{device_name}: invalid position: {violations}')


def validate_position(raw, calibration, device_name):
    """Keep encoder limits strict; tolerate small excursions around recorded mechanical endpoints."""
    excursions, violations = {}, {}
    for joint, value in raw.items():
        c = calibration[joint]
        lo, hi = max(0, c.range_min), min(4095, c.range_max)
        distance = max(lo - value, value - hi, 0)
        if not 0 <= value <= 4095 or distance > CALIBRATION_TOLERANCE_TICKS:
            violations[joint] = {'raw': value, 'range': [lo, hi], 'outside_ticks': distance}
        elif distance:
            excursions[joint] = {'raw': value, 'range': [lo, hi], 'outside_ticks': distance}
    if violations:
        raise PositionReadError(device_name, raw, violations)
    return excursions


def targets(requested, previous_targets, bounds, elapsed, speeds):
    """Advance a bounded command trajectory independently of measured follower position."""
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('Invalid command interval')
    result, reasons = {}, {'speed': [], 'range': []}
    for joint in JOINTS:
        lo, hi = bounds[joint]
        previous = previous_targets[joint]
        if not lo <= previous <= hi:
            raise TrialStop(f'{joint}: initial command is outside test range; reposition manually')
        goal = max(lo, min(hi, requested[joint]))
        change = goal - previous
        max_change = speeds[joint] * elapsed
        result[joint] = previous + max(-max_change, min(max_change, change))
        if abs(change) > max_change + 1e-6:
            reasons['speed'].append(joint)
        if goal != requested[joint]:
            reasons['range'].append(joint)
    return result, reasons


def position(device):
    raw = device.bus.sync_read('Present_Position', normalize=False, num_retry=2)
    excursions = validate_position(raw, device.calibration, device.name)
    normalized = normalize(device, raw)
    return {'raw': raw, 'position': normalized, 'calibration_excursions': excursions}


def normalize(device, raw):
    values = device.bus._normalize({device.bus.motors[j].id: v for j, v in raw.items()})
    return {j: values[device.bus.motors[j].id] for j in JOINTS}


def requested_positions(leader, held, active_joint):
    return {j: leader[j] if active_joint is None or j == active_joint else held[j] for j in JOINTS}


def preflight_faults(result):
    """Explain a responding but alarmed motor before LeRobot's handshake treats it as missing."""
    faults = []
    arm = result['arm']
    for motor in result['motors']:
        joint = motor['joint']
        state = result['status'][joint]
        errors = set(motor.get('packet_errors', {}).values())
        errors.add(state['packet_error'])
        errors.discard(0)
        if errors:
            description = 'overload (32)' if errors == {32} else f'motor error bits {sorted(errors)}'
            faults.append(f'{arm}/{joint} ID {motor["id"]} RESPONDED (model {motor["model"]}) but reports {description}')
        if state['comm'] or 'read_error' in state:
            faults.append(f'{arm}/{joint}: status read failed: {state.get("read_error", state["comm"])}')
        if motor['torque_enabled'] or state.get('torque_enabled', 0):
            faults.append(f'{arm}/{joint}: torque is already enabled; stop the other controller first')
    return faults


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--joint', choices=JOINTS, help='Follow only this joint; hold other follower joints at startup positions')
    parser.add_argument('--max-speed', type=float, default=60, help='Joint target trajectory speed in degrees/second (0 < value <= 120)')
    parser.add_argument('--gripper-speed', type=float, default=50, help='Gripper target speed in normalized units/second (0 < value <= 100)')
    parser.add_argument('--dry-run', action='store_true', help='Show config and validate files; no serial access')
    args = parser.parse_args()
    if not 0 < args.seconds <= 120:
        parser.error('--seconds must be between 0 and 120')
    if not math.isfinite(args.max_speed) or not 0 < args.max_speed <= 120:
        parser.error('--max-speed must be positive and at most 120 degrees/second')
    if not math.isfinite(args.gripper_speed) or not 0 < args.gripper_speed <= 100:
        parser.error('--gripper-speed must be positive and at most 100 normalized units/second')
    speeds = {j: args.gripper_speed if j == 'gripper' else args.max_speed for j in JOINTS}
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('Reviewed for LeRobot 0.6.1 only')
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    root = Path(__file__).resolve().parent
    devices = {}
    for role, cls, cfg in [('leader', SO101Leader, SO101LeaderConfig),
                           ('follower', SO101Follower, SO101FollowerConfig)]:
        devices[role] = cls(cfg(port=resolve_port(role), id=ARMS[role]['id'],
                                calibration_dir=root / 'outputs/calibration' / role,
                                use_degrees=True))
        if set(devices[role].calibration) != set(JOINTS):
            raise RuntimeError(f'{role}: missing/incomplete calibration')
        for c in devices[role].calibration.values():
            if max(0, c.range_min) + 48 >= min(4095, c.range_max):
                raise RuntimeError(f'{role}: invalid or too narrow calibration range')
        print(f'{role}: {devices[role].config.port}, {devices[role].calibration_fpath}')
    print(f'60 Hz requested; joint target speed <= {args.max_speed} deg/s, gripper <= {args.gripper_speed} units/s; {args.seconds}s duration.')
    if args.joint:
        print(f'Following {args.joint} only; other follower joints hold their startup positions.')
    if args.dry_run:
        print('DRY RUN: no serial access or motor writes')
        return

    folder = root / 'outputs/teleop-tests' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    metadata = {'schema_version': 4, 'started': datetime.now().isoformat(), 'fps_requested': 60,
                'target_speed_limits': speeds,
                'calibration_tolerance_ticks': CALIBRATION_TOLERANCE_TICKS,
                'target_margin_ticks': TARGET_MARGIN_TICKS,
                'active_joint': args.joint,
                'seconds_requested': args.seconds, 'devices': {}, 'samples': 0}
    leader, follower = devices['leader'], devices['follower']
    may_hold_torque = False
    log = (folder / 'samples.jsonl').open('w', encoding='utf-8', buffering=1)
    try:
        metadata['preflight'] = {}
        for role in devices:
            # This raw SDK probe preserves motor error bits, unlike LeRobot's ping result.
            result = probe(role, include_status=True)
            metadata['preflight'][role] = result
            faults = preflight_faults(result)
            if faults:
                raise TrialStop('; '.join(faults) + '. No torque enabled. Resolve alarms before retrying.')
        for role, device in devices.items():
            device.bus.connect()  # Handshake only. No automatic calibration/configuration.
            if any(device.bus.read('Torque_Enable', j, normalize=False) for j in JOINTS):
                raise RuntimeError(f'{role}: torque already enabled; stop other controllers first')
            if not device.bus.is_calibrated:
                raise RuntimeError(f'{role}: calibration file/register mismatch')
            phase = {j: device.bus.read('Phase', j, normalize=False) for j in JOINTS}
            if any(v & 0x10 for v in phase.values()):
                raise RuntimeError(f'{role}: feedback mode needs review before moving (Phase bit 4 set)')
            metadata['devices'][role] = {'port': device.config.port, 'phase': phase,
                'calibration': {j: asdict(c) for j, c in device.calibration.items()}}
        low = normalize(follower, {j: max(0, c.range_min) + TARGET_MARGIN_TICKS for j, c in follower.calibration.items()})
        high = normalize(follower, {j: min(4095, c.range_max) - TARGET_MARGIN_TICKS for j, c in follower.calibration.items()})
        bounds = {j: (low[j], high[j]) for j in JOINTS}
        print('Support both arms and place them in matching middle poses. Keep clear of joints/gripper.')
        print('ENTER will configure motors and ENABLE FOLLOWER TORQUE. Ctrl+C stops and releases torque.')
        input('Ready? Press ENTER (Ctrl+C cancels): ')
        initial_l, initial_f = position(leader), position(follower)
        for joint in JOINTS:
            limit = 20 if joint == 'gripper' else 15
            delta = initial_l['position'][joint] - initial_f['position'][joint]
            print(f'{joint}: leader={initial_l["position"][joint]:.1f}, follower={initial_f["position"][joint]:.1f}, delta={delta:.1f}')
            if (args.joint is None or joint == args.joint) and abs(delta) > limit:
                raise RuntimeError(f'{joint}: starting poses differ too much; align manually and retry')
        initial_requested = requested_positions(initial_l['position'], initial_f['position'], args.joint)
        targets(initial_requested, initial_f['position'], bounds, 0, speeds)
        metadata['initial'] = {'leader': initial_l, 'follower': initial_f}
        leader.configure()  # Keeps leader torque off, sets official communication settings.
        # Replace any stale goal while torque is OFF, before official configuration enables torque.
        current = position(follower)
        held_positions = current['position']
        targets(held_positions, held_positions, bounds, 0, speeds)
        follower.bus.sync_write('Goal_Position', current['raw'], normalize=False)
        may_hold_torque = True  # Cleanup also covers partial failure inside configure().
        follower.configure()
        metadata['follower_configured_status'] = read_motor_status(follower.bus.port_handler, follower.bus.packet_handler)
        start = previous_tick = time.perf_counter()
        previous_targets = dict(held_positions)
        previous_command_time = start - 1 / 60
        previous = None
        last_print = start
        last_status = start - 1
        while time.perf_counter() - start < args.seconds:
            tick = time.perf_counter()
            row = {'t': tick - start, 'interval_ms': (tick - previous_tick) * 1000}
            previous_tick = tick
            try:
                read_start = time.perf_counter()
                row['leader'] = position(leader)
                row['leader_read_ms'] = (time.perf_counter() - read_start) * 1000
                read_start = time.perf_counter()
                row['follower'] = position(follower)
                row['follower_read_ms'] = (time.perf_counter() - read_start) * 1000
                row['requested'] = requested_positions(row['leader']['position'], held_positions, args.joint)
                if tick - last_status >= 0.5:
                    status_start = time.perf_counter()
                    row['motor_status'] = read_motor_status(follower.bus.port_handler, follower.bus.packet_handler)
                    row['status_read_ms'] = (time.perf_counter() - status_start) * 1000
                    last_status = tick
                    for joint, state in row['motor_status'].items():
                        if state['packet_error'] or state.get('torque_enabled') == 0 or 'read_error' in state:
                            raise TrialStop(f'{joint}: motor error, torque disabled or status read failed; see motor_status in log')
                if time.perf_counter() - tick > 0.2:
                    raise RuntimeError('Position reads took >200ms; refusing to send a stale target')
                for joint in JOINTS:
                    if previous:
                        for role in devices:
                            if role == 'leader' and args.joint is not None and joint != args.joint:
                                continue
                            if abs(row[role]['position'][joint] - previous[role]['position'][joint]) > 20:
                                raise RuntimeError(f'{role}/{joint}: position jumped >20 units in one sample')
                    if abs(row['requested'][joint] - row['follower']['position'][joint]) > 40:
                        row['motor_status_at_stop'] = read_motor_status(follower.bus.port_handler, follower.bus.packet_handler)
                        lpos, fpos = row['requested'][joint], row['follower']['position'][joint]
                        unit = 'normalized units' if joint == 'gripper' else 'deg'
                        raise TrialStop(f'{joint}: requested={lpos:.2f}, follower={fpos:.2f}, '
                                        f'error={abs(lpos-fpos):.2f} {unit} >40; diagnostic stop. '
                                        'Motor status captured before torque release.')
                # Limit movement of the COMMAND, not its distance from measured follower position.
                # A stalled follower must not freeze the command at a fixed 5-degree error.
                row['trajectory_dt_s'] = min(tick - previous_command_time, 0.05)
                row['sent'], row['clip_reasons'] = targets(row['requested'], previous_targets, bounds,
                                                          row['trajectory_dt_s'], speeds)
                row['clipped'] = [j for j in JOINTS if any(j in joints for joints in row['clip_reasons'].values())]
                write_start = time.perf_counter()
                follower.bus.sync_write('Goal_Position', row['sent'])
                row['write_ms'] = (time.perf_counter() - write_start) * 1000
                previous_targets = dict(row['sent'])
                previous_command_time = tick
            except Exception as exc:
                row['error'] = str(exc)
                if isinstance(exc, PositionReadError):
                    row['invalid_position'] = exc.snapshot
                raise
            finally:
                row['work_ms'] = (time.perf_counter() - tick) * 1000
                log.write(json.dumps(row) + '\n')
            metadata['samples'] += 1
            previous = row
            if tick - last_print >= 1:
                error = max(abs(row['requested'][j] - row['follower']['position'][j]) for j in JOINTS[:5])
                excursions = {role: list(row[role]['calibration_excursions']) for role in devices
                              if row[role]['calibration_excursions']}
                print(f'{row["t"]:.0f}s | joint error max={error:.1f} deg | IO={row["work_ms"]:.1f}ms '
                      f'| speed={row["clip_reasons"]["speed"]} | range={row["clip_reasons"]["range"]} '
                      f'| observed_outside_calibration={excursions}')
                last_print = tick
            time.sleep(max(0, 1 / 60 - (time.perf_counter() - tick)))
        metadata['result'] = 'duration_completed'
    except KeyboardInterrupt:
        metadata['result'] = 'user_stopped'
    except TrialStop as exc:
        metadata['result'] = 'diagnostic_stop'
        metadata['stop_reason'] = str(exc)
        print(f'STOP: {exc}')
    except Exception as exc:
        metadata['result'] = 'error'
        metadata['error'] = str(exc)
        raise
    finally:
        try:
            if may_hold_torque:
                failures = []
                for joint in JOINTS:
                    try:
                        follower.bus.write('Torque_Enable', joint, 0, num_retry=2)
                    except Exception as exc:
                        failures.append(f'{joint}: {exc}')
                if failures:
                    metadata['torque_release_errors'] = failures
                    print('TORQUE RELEASE FAILED: support the arm and disconnect motor power.', failures)
        finally:
            for device in devices.values():
                if device.bus.port_handler.is_open:
                    device.bus.port_handler.closePort()
            log.close()
            (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            if may_hold_torque:
                print('Trial ended. Support follower; torque release was attempted. Check errors above.')
            else:
                print('Trial did not enable follower torque.')
            print(f'Logs: {folder}')


if __name__ == '__main__':
    main()
