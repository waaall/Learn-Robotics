"""验收四类物理算例，并检查步长收敛、采样语义及错误配置。"""

import copy
import json
import unittest

import mujoco
import numpy as np

from physics_lab.__main__ import run_suite
from physics_lab.common import DEFAULT_CONFIG, load_config, load_model, rollout
from physics_lab.experiments import run_case


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(DEFAULT_CONFIG)
        cls.report = run_suite(DEFAULT_CONFIG)
        cls.results = {item["name"]: item for item in cls.report["results"]}

    def test_torque(self):
        self.assertTrue(self.results["torque"]["passed"], self.results["torque"])

    def test_coupling(self):
        self.assertTrue(self.results["coupling"]["passed"], self.results["coupling"])

    def test_gravity_and_energy(self):
        self.assertTrue(self.results["pendulum"]["passed"], self.results["pendulum"])

    def test_contact_and_support(self):
        self.assertTrue(self.results["contact"]["passed"], self.results["contact"])

    def test_euler_error_halves_with_timestep(self):
        case = copy.deepcopy(self.config["cases"]["torque"])
        case["timestep"] = self.results["torque"]["settings"]["timestep"] / 2
        finer = run_case("finer", case, DEFAULT_CONFIG.parent)
        coarse_error = self.results["torque"]["metrics"]["continuous_position_error_rad"]
        fine_error = finer["metrics"]["continuous_position_error_rad"]
        self.assertAlmostEqual(coarse_error / fine_error, 2.0, places=8)
        self.assertTrue(finer["passed"])

    def test_forward_does_not_advance_time(self):
        model, data = load_model(self.config["cases"]["torque"], DEFAULT_CONFIG.parent)
        initial_position = data.qpos.copy()
        mujoco.mj_forward(model, data)
        self.assertEqual(data.time, 0)
        np.testing.assert_array_equal(data.qpos, initial_position)
        mujoco.mj_step(model, data)
        self.assertAlmostEqual(data.time, model.opt.timestep)

    def test_rejects_incorrect_control_dimension(self):
        case = copy.deepcopy(self.config["cases"]["torque"])
        case["ctrl"] = [1, 2]
        with self.assertRaisesRegex(ValueError, "ctrl"):
            load_model(case, DEFAULT_CONFIG.parent)

    def test_rejects_non_integral_or_invalid_duration(self):
        model, data = load_model(self.config["cases"]["torque"], DEFAULT_CONFIG.parent)
        for duration in (-1, 0, float("nan"), float("inf"), model.opt.timestep / 2):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                list(rollout(model, data, duration))

    def test_rejects_invalid_timestep(self):
        for timestep in (0, -0.1, float("inf"), float("nan")):
            case = copy.deepcopy(self.config["cases"]["torque"])
            case["timestep"] = timestep
            with self.subTest(timestep=timestep), self.assertRaises(ValueError):
                load_model(case, DEFAULT_CONFIG.parent)

    def test_json_has_only_finite_numbers(self):
        json.dumps(self.report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
