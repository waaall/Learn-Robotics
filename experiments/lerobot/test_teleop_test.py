"""Offline regression checks for observation tolerance and command trajectory limits."""
from types import SimpleNamespace
import unittest

from hardware import JOINTS, read_motor_status
from teleop_test import PositionReadError, TrialStop, preflight_faults, requested_positions, targets, validate_position


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


if __name__ == '__main__':
    unittest.main()
