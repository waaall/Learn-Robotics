"""CPU failure-injection tests for execution gates and torque cleanup. No serial access."""

from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from smolvla_inference.control import ControlStop, Limits, audit_processors, bounded_targets, validate_action, validate_start
from smolvla_inference.control_hardware import PositionFollower
from smolvla_inference.live_hardware import JOINTS
from smolvla_inference.supervisor import Runtime


class ControlMathTests(unittest.TestCase):
    def setUp(self):
        self.limits = Limits()
        self.calibration = {j: SimpleNamespace(range_min=0, range_max=4095) for j in JOINTS}
        self.mid = dict.fromkeys(JOINTS, 2048)

    def test_invalid_limits_and_model_actions(self):
        for kwargs in ({"max_burst_s": float("nan")}, {"joint_speed_deg_s": 100}, {"margin_ticks": True}):
            with self.assertRaises(ValueError):
                Limits(**kwargs)
        for action in ([0] * 5, [float("nan")] * 6, [101] * 6, [0] * 5 + [-1]):
            with self.assertRaises(ControlStop):
                validate_action(action)

    def test_endpoints_refuse_activation(self):
        for value in (0, 23, 4095, 5000):
            with self.assertRaises(ControlStop):
                validate_start({**self.mid, "elbow_flex": value}, self.calibration, self.limits)

    def test_speed_trajectory_does_not_reset_to_lagging_encoder(self):
        requested = dict.fromkeys(JOINTS, 4000)
        previous = dict(self.mid)
        for _ in range(10):
            previous, reasons = bounded_targets(requested, previous, self.mid, self.mid,
                                                 self.calibration, .05, self.limits)
        self.assertAlmostEqual(previous["wrist_flex"] - 2048, 8 * 4095 / 360 * .5)
        self.assertTrue(reasons["wrist_flex"]["speed"])

    def test_cumulative_excursion_and_calibration_margin(self):
        previous = {j: 2048 + 20 * 4095 / 360 for j in JOINTS}
        requested = dict.fromkeys(JOINTS, 6000)
        targets, reasons = bounded_targets(requested, previous, previous, self.mid,
                                           self.calibration, .05, self.limits)
        self.assertLessEqual(targets["wrist_flex"], previous["wrist_flex"])
        self.assertTrue(reasons["wrist_flex"]["range_or_excursion"])

    def test_stall_stale_interval_and_bad_encoder_stop(self):
        for raw, dt in (({**self.mid, "elbow_flex": 0}, .05), (self.mid, .3),
                        ({**self.mid, "elbow_flex": -1}, .05)):
            with self.assertRaises(ControlStop):
                bounded_targets(self.mid, self.mid, raw, self.mid, self.calibration, dt, self.limits)


class HardwareTransactionTests(unittest.TestCase):
    def follower(self):
        device = PositionFollower.__new__(PositionFollower)
        device.bus, device.event = Mock(), Mock()
        device.calibration = {j: SimpleNamespace(range_min=0, range_max=4095) for j in JOINTS}
        device.limits, device.owns_torque, device.register_writes = Limits(), False, 0
        device.read = Mock(return_value={"raw": dict.fromkeys(JOINTS, 2048),
                                       "telemetry": {j: {"torque_enabled": 0} for j in JOINTS}})
        device.bus.read.return_value = 2048
        return device

    def test_goal_readback_failure_never_enables_torque(self):
        device = self.follower()
        device.bus.read.return_value = 1234
        with self.assertRaises(ControlStop):
            device.arm()
        self.assertFalse(device.owns_torque)
        self.assertFalse(any(c.args[0] == "Torque_Enable" for c in device.bus.write.call_args_list))

    def test_partial_enable_has_cleanup_ownership_and_releases_all_axes(self):
        device = self.follower()
        def write(key, joint, value, **kwargs):
            if key == "Torque_Enable" and joint == "elbow_flex" and value == 1:
                raise RuntimeError("injected enable failure")
        device.bus.write.side_effect = write
        with self.assertRaises(RuntimeError):
            device.arm()
        self.assertTrue(device.owns_torque)
        device.bus.read.return_value = 0
        self.assertEqual(device.release(), [])
        released = [c.args[1] for c in device.bus.write.call_args_list if c.args[0] == "Torque_Enable" and c.args[2] == 0]
        self.assertEqual(released, list(JOINTS))

    def test_release_attempts_other_axes_after_one_failure(self):
        device = self.follower()
        device.owns_torque = True
        device.bus.read.return_value = 0
        def write(key, joint, *args, **kwargs):
            if joint == "shoulder_pan":
                raise RuntimeError("injected serial error")
        device.bus.write.side_effect = write
        self.assertEqual(len(device.release()), 1)
        self.assertEqual(device.bus.write.call_count, 6)
        self.assertTrue(device.owns_torque)

    def test_log_disk_failure_does_not_prevent_emergency_torque_off(self):
        device = self.follower()
        device.owns_torque = True
        device.event.side_effect = OSError("injected full log disk")
        device.bus.read.return_value = 0
        self.assertEqual(device.release(), [])
        self.assertEqual(device.bus.write.call_count, 6)
        self.assertFalse(device.owns_torque)


class SupervisorGateTests(unittest.TestCase):
    def runtime(self):
        runtime = Runtime.__new__(Runtime)
        runtime.bus_lock = threading.RLock()
        runtime.cancel = threading.Event()
        runtime.allow_motion, runtime.policy, runtime.limits = False, Mock(), Limits()
        runtime.fault = None
        runtime.processor_audit = {"ready_for_vla_execution": False, "issues": ["missing stats"]}
        runtime.hardware = Mock()
        runtime.hardware.owns_torque = False
        runtime.observations = {}
        return runtime

    def test_motion_disabled_and_unreviewed_scene_refused(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, "allow-motion"):
            runtime._check_task({})
        runtime.allow_motion = True
        with self.assertRaisesRegex(RuntimeError, "visually reviewed"):
            runtime._check_task({"seconds": 1, "observation_id": "unseen"})

    def test_cancellation_during_inference_cannot_enable_torque(self):
        runtime = self.runtime()
        def predict(*args):
            runtime.cancel.set()
            return np.zeros((50, 6)), {}, 0
        runtime.predict = predict
        result = runtime._execute({"task": "nod", "seconds": 1, "active_joints": ["wrist_flex"]})
        self.assertEqual(result["commands_sent"], 0)
        runtime.hardware.arm.assert_not_called()

    def test_stop_sets_cancellation_before_releasing(self):
        runtime = self.runtime()
        runtime.event = Mock()
        def release():
            self.assertTrue(runtime.cancel.is_set())
            return []
        runtime.hardware.release.side_effect = release
        self.assertTrue(runtime.stop()["stopped"])

    def test_executed_prefix_holds_all_inactive_joint_targets(self):
        runtime = self.runtime()
        runtime.origin = dict.fromkeys(JOINTS, 2048)
        runtime.commands_sent = 0
        runtime.recorder, runtime.camera, runtime.event = Mock(), Mock(), Mock()
        runtime.camera.after.side_effect = lambda *args: (1, time.perf_counter(), None)
        state = {"raw": dict(runtime.origin), "state": [0, 0, 0, 0, 0, 50]}
        runtime.hardware.read.return_value = state
        def arm():
            runtime.hardware.owns_torque = True
            return state
        runtime.hardware.arm.side_effect = arm
        runtime.hardware.calibration = {j: SimpleNamespace(range_min=0, range_max=4095) for j in JOINTS}
        runtime.hardware.action_to_raw.side_effect = lambda action: {
            j: (v + 100) / 200 * 4095 if j != "gripper" else v / 100 * 4095
            for j, v in zip(JOINTS, action)}
        runtime.predict = Mock(return_value=(np.ones((50, 6)) * 10, {}, 0))
        result = runtime._execute({"task": "tilt", "seconds": .13, "active_joints": ["wrist_flex"]})
        self.assertGreaterEqual(result["commands_sent"], 2)
        for call in runtime.hardware.send.call_args_list:
            for joint in JOINTS:
                if joint != "wrist_flex":
                    self.assertEqual(call.args[0][joint], 2048)
            self.assertLess(abs(call.args[0]["wrist_flex"] - 2048), 8 * 4095 / 360 * .2)

    def test_new_pose_requires_another_visual_review(self):
        runtime = self.runtime()
        runtime.allow_motion = True
        runtime.observations["reviewed"] = {"observed_monotonic": time.perf_counter(), "raw": dict.fromkeys(JOINTS, 2048)}
        runtime.hardware.calibration = {j: SimpleNamespace(range_min=0, range_max=4095) for j in JOINTS}
        runtime.hardware.read.return_value = {"raw": {**dict.fromkeys(JOINTS, 2048), "wrist_flex": 2100}}
        with self.assertRaisesRegex(RuntimeError, "moved since"):
            runtime._check_task({"seconds": 1, "observation_id": "reviewed", "active_joints": ["wrist_flex"],
                                 "task": "nod", "reason": "reviewed clear table"})

    def test_dataset_prefixed_stats_and_missing_state_fail_audit(self):
        pipeline = SimpleNamespace(steps=[SimpleNamespace(_tensor_stats={"so100.buffer.action": {}})])
        result = audit_processors(pipeline, pipeline)
        self.assertFalse(result["ready_for_vla_execution"])
        self.assertEqual(len(result["issues"]), 2)

    def test_missing_processor_cannot_pass_audit(self):
        result = audit_processors(SimpleNamespace(steps=[]), SimpleNamespace(steps=[]))
        self.assertFalse(result["ready_for_vla_execution"])

    def test_valid_stats_bind_to_exact_features(self):
        def tensor(values):
            result = Mock()
            result.detach.return_value.cpu.return_value.reshape.return_value.tolist.return_value = values
            return result
        stats = {"mean": tensor([0.] * 6), "std": tensor([1.] * 6)}
        pre = SimpleNamespace(steps=[SimpleNamespace(_tensor_stats={"observation.state": stats})])
        post = SimpleNamespace(steps=[SimpleNamespace(_tensor_stats={"action": stats})])
        self.assertTrue(audit_processors(pre, post)["ready_for_vla_execution"])

    def test_actual_vla_gate_refuses_unbound_stats_before_arming(self):
        runtime = self.runtime()
        runtime.allow_motion = True
        raw = dict.fromkeys(JOINTS, 2048)
        runtime.observations["reviewed"] = {"observed_monotonic": time.perf_counter(), "raw": raw}
        runtime.hardware.calibration = {j: SimpleNamespace(range_min=0, range_max=4095) for j in JOINTS}
        runtime.hardware.read.return_value = {"raw": raw}
        with self.assertRaisesRegex(RuntimeError, "VLA execution refused"):
            runtime._check_task({"seconds": 1, "observation_id": "reviewed", "active_joints": ["wrist_flex"],
                                 "controller": "vla", "task": "nod", "reason": "reviewed"})
        runtime.hardware.arm.assert_not_called()

    def test_log_failure_while_raising_watchdog_fault_still_stops(self):
        runtime = self.runtime()
        runtime.shutdown = threading.Event()
        runtime.started = time.perf_counter()
        runtime.recorder = Mock()
        runtime.recorder.check.side_effect = RuntimeError("injected recorder failure")
        runtime.event = Mock(side_effect=OSError("injected disk failure"))
        runtime.stop = Mock()
        with self.assertRaises(OSError):
            runtime._monitor()
        runtime.stop.assert_called_once_with("injected recorder failure")


if __name__ == "__main__":
    unittest.main()
