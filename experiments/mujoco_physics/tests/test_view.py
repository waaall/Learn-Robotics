"""无窗口核对查看器使用的物理模型、初态恢复和算例选择。"""

import copy
import unittest
from unittest.mock import patch

import mujoco
import numpy as np

from physics_lab.common import DEFAULT_CONFIG, load_config, load_model, mass_matrix, sha256
from physics_lab.view import INITIAL_KEY, main, prepare_view


class ViewerTests(unittest.TestCase):
    def test_view_preserves_physics_and_initial_state(self):
        for name, case in load_config(DEFAULT_CONFIG)["cases"].items():
            with self.subTest(case=name):
                path = DEFAULT_CONFIG.parent / case["model"]
                original_hash = sha256(path)
                model, data = load_model(case, DEFAULT_CONFIG.parent)
                view_model, view_data = prepare_view(case, DEFAULT_CONFIG.parent)
                self.assertEqual(view_model.nkey, model.nkey + 1)
                for field in ("qpos", "qvel", "ctrl", "qacc", "qfrc_actuator"):
                    np.testing.assert_allclose(getattr(view_data, field), getattr(data, field))
                np.testing.assert_allclose(mass_matrix(view_model, view_data), mass_matrix(model, data))
                self.assertEqual(original_hash, sha256(path))

    def test_key_restores_configuration(self):
        case = copy.deepcopy(load_config(DEFAULT_CONFIG)["cases"]["torque"])
        case["timestep"] = 0.002
        model, data = prepare_view(case, DEFAULT_CONFIG.parent)
        initial_qpos, initial_ctrl = data.qpos.copy(), data.ctrl.copy()
        mujoco.mj_step(model, data)
        data.ctrl[:] = 0
        key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, INITIAL_KEY)
        mujoco.mj_resetDataKeyframe(model, data, key)
        np.testing.assert_array_equal(data.qpos, initial_qpos)
        np.testing.assert_array_equal(data.ctrl, initial_ctrl)
        self.assertEqual(data.time, 0)
        self.assertEqual(model.opt.timestep, case["timestep"])

    def test_all_cases_use_official_viewer(self):
        with patch("mujoco.viewer.launch") as launch:
            self.assertEqual(main([]), 0)
            self.assertEqual(launch.call_count, len(load_config(DEFAULT_CONFIG)["cases"]))

    def test_single_case_uses_official_viewer(self):
        with patch("mujoco.viewer.launch") as launch:
            self.assertEqual(main(["--case", "pendulum"]), 0)
            launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
