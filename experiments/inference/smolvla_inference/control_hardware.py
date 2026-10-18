"""Acknowledged SO-101 position execution, with explicit startup/stop transactions.

Shares the live adapter's identity and range-position mapping. Does not run Robot.configure,
change calibration, PID gains, operating mode, or servo protection settings.
"""

import time
from dataclasses import asdict

from .control import ControlStop, validate_action, validate_start
from .live_hardware import JOINTS, ReadOnlyFollower, validate_raw


class PositionFollower:
    def __init__(self, serial, calibration, limits, event):
        reader = ReadOnlyFollower(serial, calibration)
        self.bus, self.calibration = reader.bus, reader.calibration
        self.metadata = dict(reader.metadata)
        self.metadata.pop("motor_register_writes", None)
        self.metadata["calibration"] = {j: asdict(c) for j, c in self.calibration.items()}
        self.limits, self.event = limits, event
        self.owns_torque = False
        self.register_writes = 0

    def open(self):
        self.bus.connect()
        actual = self.bus.read_calibration()
        configuration = {}
        for joint in JOINTS:
            expected, found = self.calibration[joint], actual[joint]
            if any(getattr(expected, k) != getattr(found, k) for k in ("range_min", "range_max", "homing_offset")):
                raise ControlStop(f"{joint}: stored/register calibration mismatch")
            configuration[joint] = {key: self.bus.read(key, joint, normalize=False, num_retry=2)
                                    for key in ("Operating_Mode", "Phase", "P_Coefficient", "I_Coefficient", "D_Coefficient")}
            if configuration[joint]["Operating_Mode"] != 0 or configuration[joint]["Phase"] & 0x10:
                raise ControlStop(f"{joint}: unsupported operating/feedback mode")
        self.metadata["existing_servo_configuration"] = configuration
        state = self.read()
        if any(v["torque_enabled"] for v in state["telemetry"].values()):
            raise ControlStop("another controller already enabled torque")
        self.event("hardware_opened", metadata=self.metadata, observation=state)
        return state

    def read(self):
        begin = time.perf_counter()
        raw, telemetry = {}, {}
        port, packet = self.bus.port_handler, self.bus.packet_handler
        for motor, joint in enumerate(JOINTS, 1):
            data, comm, error = packet.readTxRx(port, motor, 40, 31)
            if comm or error or len(data) != 31:
                raise ControlStop(f"{joint}: telemetry failure comm={comm}, packet_error={error}, bytes={len(data)}")
            def value(address, size=1):
                return int.from_bytes(bytes(data[address - 40:address - 40 + size]), "little")
            raw[joint] = value(56, 2)
            telemetry[joint] = {"torque_enabled": value(40), "goal_raw": value(42, 2),
                                "position_raw": raw[joint], "velocity_raw": value(58, 2),
                                "load_raw": value(60, 2), "voltage_raw": value(62),
                                "temperature_c": value(63), "status_raw": value(65),
                                "moving_raw": value(66), "current_raw": value(69, 2)}
            if telemetry[joint]["temperature_c"] > self.limits.max_temperature_c:
                raise ControlStop(f"{joint}: temperature exceeded experiment limit")
            if self.owns_torque and telemetry[joint]["torque_enabled"] != 1:
                raise ControlStop(f"{joint}: torque disappeared during execution")
        warnings = validate_raw(raw, self.calibration)
        normalized = self.bus._normalize({i: raw[j] for i, j in enumerate(JOINTS, 1)})
        return {"raw": raw, "state": [normalized[i] for i in range(1, 7)],
                "state_warnings": warnings, "telemetry": telemetry,
                "read_start_monotonic": begin, "read_end_monotonic": time.perf_counter()}

    def _write(self, key, joint, value, *, emergency=False):
        try:
            self.event("register_write_attempt", register=key, joint=joint, value=value)
        except Exception:
            # A full/unavailable log disk must never prevent torque-off transactions.
            if not emergency:
                raise
        self.bus.write(key, joint, value, normalize=False, num_retry=1)
        self.register_writes += 1

    def arm(self):
        state = self.read()
        validate_start(state["raw"], self.calibration, self.limits)
        if any(t["torque_enabled"] for t in state["telemetry"].values()):
            raise ControlStop("torque must be off before taking ownership")
        for joint in JOINTS:
            self._write("Goal_Position", joint, state["raw"][joint])
        for joint in JOINTS:
            if self.bus.read("Goal_Position", joint, normalize=False, num_retry=2) != state["raw"][joint]:
                raise ControlStop(f"{joint}: startup goal readback mismatch")
        self.owns_torque = True  # Cleanup must also cover a partial enable failure.
        for joint in JOINTS:
            self._write("Torque_Enable", joint, 1)
        self.event("torque_owned", observation=self.read())
        return state

    def action_to_raw(self, action):
        validate_action(action)
        converted = self.bus._unnormalize({i: float(v) for i, v in enumerate(action, 1)})
        return {j: converted[i] for i, j in enumerate(JOINTS, 1)}

    def send(self, targets):
        if not self.owns_torque:
            raise ControlStop("controller does not own torque")
        for joint in JOINTS:
            self._write("Goal_Position", joint, round(targets[joint]))

    def release(self):
        failures = []
        if self.owns_torque:
            for joint in JOINTS:
                try:
                    self.bus.port_handler.clearPort()
                    self.bus.port_handler.is_using = False
                    self._write("Torque_Enable", joint, 0, emergency=True)
                    if self.bus.read("Torque_Enable", joint, normalize=False, num_retry=1) != 0:
                        raise ControlStop("torque-off readback mismatch")
                except Exception as error:
                    failures.append(f"{joint}: {error}")
            self.owns_torque = bool(failures)
            try:
                self.event("torque_release", failures=failures)
            except Exception:
                pass  # Motor readbacks, not logging availability, determine torque ownership.
        return failures

    def close(self):
        failures = self.release()
        if self.bus.is_connected:
            self.bus.disconnect(disable_torque=False)
        return failures
