"""Identity checks and read-only probes for this pair of SO-101 arms."""
from serial.tools import list_ports
from scservo_sdk import PacketHandler, PortHandler

ARMS = {
    "leader": {"serial": "5C82109341", "id": "hiwonder_leader"},
    "follower": {"serial": "5C82109737", "id": "hiwonder_follower"},
}
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def read_motor_status(port, packet, joints=JOINTS):
    """Read the STS-compatible SRAM block, preserving packet error bits and raw telemetry units."""
    states = {}
    for joint in joints:
        motor = JOINTS.index(joint) + 1
        for _ in range(3):
            data, comm, error = packet.readTxRx(port, motor, 40, 31)
            if not comm and len(data) == 31:
                break
        state = {'id': motor, 'comm': comm, 'packet_error': error}
        if comm or len(data) != 31:
            state['read_error'] = packet.getTxRxResult(comm) or f'Expected 31 bytes, got {len(data)}'
        else:
            def value(address, size=1):
                offset = address - 40
                return int.from_bytes(bytes(data[offset:offset + size]), 'little')
            state.update({
                'torque_enabled': value(40), 'goal_position_raw': value(42, 2),
                'torque_limit_raw': value(48, 2), 'position_raw': value(56, 2),
                'velocity_raw': value(58, 2), 'load_raw': value(60, 2),
                'voltage_raw': value(62), 'temperature_raw': value(63),
                'status_raw': value(65), 'moving_raw': value(66), 'current_raw': value(69, 2),
            })
        states[joint] = state
    return states


def resolve_port(arm):
    matches = [p for p in list_ports.comports() if p.serial_number == ARMS[arm]["serial"]]
    if len(matches) != 1:
        raise RuntimeError(f"{arm}: expected exactly one board with serial {ARMS[arm]['serial']}; found {len(matches)}")
    return matches[0].device


def probe(arm, include_status=False):
    """Only ping/read instructions; no register writes, torque changes or Robot.connect()."""
    name = resolve_port(arm)
    port, packet = PortHandler(name), PacketHandler(0)
    rows = []
    try:
        if not port.openPort():
            raise RuntimeError(f"Cannot open {name}")
        for motor, joint in enumerate(JOINTS, 1):
            model, comm, error = packet.ping(port, motor)
            if comm or model != 777 or (error and not include_status):
                raise RuntimeError(f"{name} ID {motor}: model={model}, comm={comm}, error={error}")
            row = {"id": motor, "joint": joint, "model": model}
            if include_status and error:
                row['packet_errors'] = {'ping': error}
            for key, address, size in (("position_raw", 56, 2), ("torque_enabled", 40, 1), ("mode", 33, 1)):
                read = packet.read2ByteTxRx if size == 2 else packet.read1ByteTxRx
                value, comm, error = read(port, motor, address)
                if comm or (error and not include_status):
                    raise RuntimeError(f"{name} ID {motor} {key}: comm={comm}, error={error}")
                row[key] = value
                if include_status and error:
                    row.setdefault('packet_errors', {})[key] = error
            rows.append(row)
        status = read_motor_status(port, packet) if include_status else None
    finally:
        if port.is_open:
            port.closePort()
    result = {"arm": arm, "port": name, "serial": ARMS[arm]["serial"], "baudrate": 1000000, "motors": rows}
    if include_status:
        result['status'] = status
    return result
