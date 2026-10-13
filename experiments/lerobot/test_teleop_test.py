"""Offline checks for command limits, startup verification and interrupted SDK cleanup."""
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scservo_sdk import COMM_SUCCESS, PacketHandler

from hardware import JOINTS, read_motor_status
import teleop_test
from teleop_test import (
    PositionReadError, TrialStop, preflight_faults, release_follower_torque,
    requested_positions, targets, validate_position, verify_startup_goals,
)


class TeleopBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.calibration = {j: SimpleNamespace(range_min=860, range_max=3197) for j in JOINTS}
        self.raw = dict.fromkeys(JOINTS, 2000)
        self.bounds = dict.fromkeys(JOINTS, (-90, 90))
        self.speeds = dict.fromkeys(JOINTS, 50)

    def test_one_tick_above_recorded_endpoint_is_logged(self):
        self.raw['wrist_flex'] = 3198
        excursions = validate_position(self.raw, self.calibration, 'leader')
        self.assertEqual(excursions['wrist_flex']['outside_ticks'], 1)
        self.assertEqual(self.raw['wrist_flex'], 3198)

    def test_small_excursions_both_sides_are_allowed(self):
        for value in (828, 3229):
            with self.subTest(value=value):
                self.raw['wrist_flex'] = value
                excursions = validate_position(self.raw, self.calibration, 'leader')
                self.assertEqual(excursions['wrist_flex']['outside_ticks'], 32)

    def test_large_excursion_aborts_and_preserves_raw_snapshot(self):
        self.raw['wrist_flex'] = 3230
        with self.assertRaises(PositionReadError) as caught:
            validate_position(self.raw, self.calibration, 'leader')
        self.assertEqual(caught.exception.snapshot['raw']['wrist_flex'], 3230)

    def test_encoder_limits_stay_strict(self):
        self.calibration = {j: SimpleNamespace(range_min=0, range_max=4156) for j in JOINTS}
        for value in (-1, 4096):
            with self.subTest(value=value):
                self.raw['elbow_flex'] = value
                with self.assertRaises(PositionReadError):
                    validate_position(self.raw, self.calibration, 'leader')

    def test_bidirectional_trajectory_speed(self):
        for demand, expected in ((60, 15), (-60, 5), (12, 12)):
            with self.subTest(demand=demand):
                sent, reasons = targets(dict.fromkeys(JOINTS, demand), dict.fromkeys(JOINTS, 10), self.bounds, 0.1, self.speeds)
                self.assertEqual(set(sent.values()), {expected})
                self.assertEqual(reasons['range'], [])

    def test_range_limit_is_distinct_from_speed_limit(self):
        sent, reasons = targets(dict.fromkeys(JOINTS, 93), dict.fromkeys(JOINTS, 89), self.bounds, 0.1, self.speeds)
        self.assertEqual(set(sent.values()), {90})
        self.assertEqual(reasons['speed'], [])
        self.assertEqual(reasons['range'], list(JOINTS))

    def test_stalled_follower_does_not_freeze_command(self):
        # A stationary follower at 77 degrees used to freeze its command at 72 degrees.
        # The trajectory must keep advancing toward the requested 59 degrees.
        previous = dict.fromkeys(JOINTS, 77)
        demand = dict.fromkeys(JOINTS, 59)
        for _ in range(20):
            sent, _ = targets(demand, previous, self.bounds, 0.02, self.speeds)
            self.assertTrue(all(abs(sent[j] - previous[j]) <= 1 + 1e-6 for j in JOINTS))
            previous = sent
        self.assertEqual(set(previous.values()), {59})

    def test_invalid_initial_command_aborts(self):
        with self.assertRaises(TrialStop):
            targets(dict.fromkeys(JOINTS, 0), dict.fromkeys(JOINTS, 96), self.bounds, 0.1, self.speeds)

    def test_speed_limit_scales_with_elapsed_time(self):
        for elapsed, expected in ((0, 0), (0.02, 1), (0.1, 5)):
            sent, _ = targets(dict.fromkeys(JOINTS, 50), dict.fromkeys(JOINTS, 0), self.bounds, elapsed, self.speeds)
            self.assertEqual(set(sent.values()), {expected})

    def test_gripper_and_arm_speeds_are_separate(self):
        speeds = {j: 10 if j == 'gripper' else 60 for j in JOINTS}
        sent, _ = targets(dict.fromkeys(JOINTS, 50), dict.fromkeys(JOINTS, 0), self.bounds, 0.1, speeds)
        self.assertEqual(sent['gripper'], 1)
        self.assertEqual(sent['shoulder_lift'], 6)

    def test_invalid_time_cannot_create_a_target(self):
        for elapsed in (-0.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                targets(dict.fromkeys(JOINTS, 0), dict.fromkeys(JOINTS, 0), self.bounds, elapsed, self.speeds)

    def test_single_joint_trial_holds_other_joints(self):
        leader, held = dict.fromkeys(JOINTS, 50), dict.fromkeys(JOINTS, 10)
        requested = requested_positions(leader, held, 'shoulder_lift')
        self.assertEqual(requested['shoulder_lift'], 50)
        self.assertTrue(all(requested[j] == 10 for j in JOINTS if j != 'shoulder_lift'))

    def test_status_keeps_fault_bits_and_goal_readback(self):
        data = [0] * 31
        data[0] = 1  # Torque enabled
        data[2], data[3] = 0xB8, 0x09  # Goal = 2488
        data[25] = 32  # Status register
        class Packet:
            def readTxRx(self, port, motor, address, length):
                return data, 0, 32
        state = read_motor_status(None, Packet(), ['shoulder_lift'])['shoulder_lift']
        self.assertEqual(state['packet_error'], 32)
        self.assertEqual(state['status_raw'], 32)
        self.assertEqual(state['goal_position_raw'], 2488)
        self.assertEqual(state['torque_enabled'], 1)

    def test_failed_status_read_does_not_invent_motor_values(self):
        class Packet:
            def readTxRx(self, *args):
                return [], -1, 0
            def getTxRxResult(self, comm):
                return 'timeout'
        state = read_motor_status(None, Packet(), ['shoulder_lift'])['shoulder_lift']
        self.assertEqual(state['read_error'], 'timeout')
        self.assertNotIn('torque_enabled', state)

    def test_responding_overloaded_motor_is_reported_as_alarm(self):
        result = {'arm': 'follower', 'motors': [{'joint': 'gripper', 'id': 6, 'model': 777,
                  'torque_enabled': 0, 'packet_errors': {'ping': 32}}],
                  'status': {'gripper': {'comm': 0, 'packet_error': 32, 'torque_enabled': 0}}}
        faults = preflight_faults(result)
        self.assertEqual(len(faults), 1)
        self.assertIn('RESPONDED', faults[0])
        self.assertIn('overload (32)', faults[0])

    def test_healthy_preflight_allows_handshake(self):
        result = {'arm': 'follower', 'motors': [{'joint': 'gripper', 'id': 6, 'model': 777,
                  'torque_enabled': 0}], 'status': {'gripper': {'comm': 0, 'packet_error': 0,
                  'torque_enabled': 0}}}
        self.assertEqual(preflight_faults(result), [])


class StartupGoalTests(unittest.TestCase):
    def setUp(self):
        self.raw = dict.fromkeys(JOINTS, 2000)
        self.verification = {}
        self.goals = dict.fromkeys(JOINTS, 1024)
        self.bus = Mock()
        self.bus.read.side_effect = lambda name, joint, **kw: (
            self.goals[joint] if name == 'Goal_Position' else 0)
        self.bus.write.side_effect = lambda name, joint, value, **kw: self.goals.update({joint: value})

    def test_all_startup_goals_are_acknowledged_and_verified(self):
        verify_startup_goals(self.bus, self.raw, self.verification)
        self.assertTrue(self.verification['verified'])
        self.assertEqual(self.verification['readback_raw'], self.raw)
        self.bus.sync_write.assert_not_called()
        for joint in JOINTS:
            self.bus.write.assert_any_call('Goal_Position', joint, 2000, normalize=False, num_retry=2)

    def test_existing_torque_blocks_all_startup_writes(self):
        self.bus.read.side_effect = lambda name, joint, **kw: int(joint == 'elbow_flex')
        with self.assertRaisesRegex(TrialStop, 'torque enabled'):
            verify_startup_goals(self.bus, self.raw, self.verification)
        self.bus.write.assert_not_called()
        self.assertFalse(self.verification['verified'])

    def test_goal_write_failure_cannot_mark_startup_verified(self):
        self.bus.write.side_effect = OSError('write failed')
        with self.assertRaisesRegex(TrialStop, 'write failed'):
            verify_startup_goals(self.bus, self.raw, self.verification)
        self.assertFalse(self.verification['verified'])
        self.assertEqual(self.verification['readback_raw'], {})

    def test_failed_read_preserves_partial_verification(self):
        def read(name, joint, **kw):
            if name == 'Torque_Enable':
                return 0
            if joint == 'elbow_flex':
                raise OSError('timeout')
            return self.goals[joint]
        self.bus.read.side_effect = read
        with self.assertRaisesRegex(TrialStop, 'timeout'):
            verify_startup_goals(self.bus, self.raw, self.verification)
        self.assertFalse(self.verification['verified'])
        self.assertEqual(self.verification['readback_raw'], {'shoulder_pan': 2000, 'shoulder_lift': 2000})

    def test_mismatched_goal_exits_main_without_enabling_torque(self):
        @dataclass
        class Calibration:
            range_min: int = 860
            range_max: int = 3197

        leader, follower = Mock(), Mock()
        for device in (leader, follower):
            device.config = SimpleNamespace(port='offline')
            device.calibration_fpath = 'offline.json'
            device.calibration = {j: Calibration() for j in JOINTS}
            device.bus.is_calibrated = True
            device.bus.port_handler.is_open = True
            # A write appears successful, but the readback retains a stale goal.
            device.bus.read.side_effect = lambda name, joint, **kw: 1024 if name == 'Goal_Position' else 0
        modules = {
            'lerobot.teleoperators.so_leader': SimpleNamespace(
                SO101Leader=Mock(return_value=leader), SO101LeaderConfig=SimpleNamespace),
            'lerobot.robots.so_follower': SimpleNamespace(
                SO101Follower=Mock(return_value=follower), SO101FollowerConfig=SimpleNamespace),
        }
        snapshot = {'raw': self.raw, 'position': dict.fromkeys(JOINTS, 0), 'calibration_excursions': {}}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(sys.modules, modules),
            patch.object(teleop_test, '__file__', str(Path(folder) / 'teleop_test.py')),
            patch.object(teleop_test.importlib.metadata, 'version', return_value='0.6.1'),
            patch.object(teleop_test, 'resolve_port', return_value='offline'),
            patch.object(teleop_test, 'probe', side_effect=lambda role, **kw: {'arm': role, 'motors': [], 'status': {}}),
            patch.object(teleop_test, 'position', return_value=snapshot),
            patch.object(teleop_test, 'normalize', side_effect=lambda device, raw: {j: (v - 2000) / 10 for j, v in raw.items()}),
            patch.object(sys, 'argv', ['teleop_test.py']),
            patch('builtins.input', return_value=''),
            patch('builtins.print'),
        ):
            teleop_test.main()
            metadata_path = next((Path(folder) / 'outputs/teleop-tests').glob('*/metadata.json'))
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        follower.configure.assert_not_called()
        self.assertEqual(metadata['result'], 'diagnostic_stop')
        self.assertFalse(metadata['startup_goal_verification']['verified'])
        self.assertEqual(metadata['startup_goal_verification']['readback_raw']['shoulder_pan'], 1024)
        self.assertTrue(all(call.args[0] == 'Goal_Position' for call in follower.bus.write.call_args_list))


class OfflinePort:
    """In-memory port for the real SDK; never opens a serial device."""
    def __init__(self, failed_motor=None):
        self.is_using = False
        self.interrupt_read = False
        self.failed_motor = failed_motor
        self.torque_writes = []

    def clearPort(self):
        pass

    def writePort(self, data):
        self.motor = data[2]
        if data[4] == 3 and data[5] == 40:  # WRITE Torque_Enable
            if self.motor == self.failed_motor:
                raise OSError('simulated disconnected motor')
            self.torque_writes.append((self.motor, data[6]))
        return len(data)

    def setPacketTimeout(self, length):
        pass

    def readPort(self, length):
        if self.interrupt_read:
            raise KeyboardInterrupt
        return [255, 255, self.motor, 2, 0, (~(self.motor + 2)) & 255]


class OfflineSDKBus:
    def __init__(self, port):
        self.port_handler = port
        self.packet_handler = PacketHandler(0)

    def write(self, name, joint, value, *, normalize, num_retry):
        if name != 'Torque_Enable' or normalize:
            raise AssertionError('Only raw torque writes expected')
        for _ in range(num_retry + 1):
            comm, error = self.packet_handler.write1ByteTxRx(
                self.port_handler, JOINTS.index(joint) + 1, 40, value)
            if comm == COMM_SUCCESS and error == 0:
                return
        raise RuntimeError(f'comm={comm}, error={error}')


class TorqueReleaseTests(unittest.TestCase):
    def test_real_sdk_interrupted_read_can_release_every_joint(self):
        port = OfflinePort()
        bus = OfflineSDKBus(port)
        port.interrupt_read = True
        with self.assertRaises(KeyboardInterrupt):
            bus.packet_handler.read1ByteTxRx(port, 1, 40)
        self.assertTrue(port.is_using)  # The original failure, reproduced in the actual SDK.
        port.interrupt_read = False
        self.assertEqual(release_follower_torque(bus), [])
        self.assertEqual(port.torque_writes, [(motor, 0) for motor in range(1, 7)])

    def test_failed_write_does_not_keep_other_joints_busy(self):
        port = OfflinePort(failed_motor=2)
        failures = release_follower_torque(OfflineSDKBus(port))
        self.assertEqual(len(failures), 1)
        self.assertIn('shoulder_lift', failures[0])
        self.assertEqual(port.torque_writes, [(motor, 0) for motor in (1, 3, 4, 5, 6)])

    def test_failed_buffer_clear_does_not_abort_remaining_joints(self):
        port = Mock(is_using=True)
        port.clearPort.side_effect = [OSError('buffer error'), None, None, None, None, None]
        bus = Mock(port_handler=port)
        failures = release_follower_torque(bus)
        self.assertEqual(len(failures), 1)
        self.assertIn('buffer error', failures[0])
        self.assertFalse(port.is_using)
        self.assertEqual(bus.write.call_count, len(JOINTS))


if __name__ == '__main__':
    unittest.main()
