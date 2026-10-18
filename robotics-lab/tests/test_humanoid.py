import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
import mujoco
import numpy as np

from robotics_lab.api import create_app
from robotics_lab.catalog import get_experiment
from robotics_lab.humanoid import ASSETS, G1Policy, HOME, HumanoidController, SmoothReference
from robotics_lab.physics import load_model, simulate


class HumanoidTests(unittest.TestCase):
    def controller(self, mode="g1-structure"):
        m, d = load_model(get_experiment(mode))
        return HumanoidController(m, d, mode)

    def advance(self, c, seconds):
        for _ in range(round(seconds / c.model.opt.timestep)):
            c.step()

    def test_policy_matches_official_torchscript_sequence_and_resets(self):
        policy = G1Policy()
        with np.load(ASSETS / "policy_reference.npz", allow_pickle=False) as reference:
            actions = np.array([policy(x) for x in reference["observations"]])
            np.testing.assert_allclose(actions, reference["actions"], atol=2e-5, rtol=2e-5)
            policy.reset()
            np.testing.assert_allclose(policy(reference["observations"][0]), actions[0], atol=1e-6)

    def test_reference_retarget_preserves_position_velocity_and_acceleration(self):
        reference = SmoothReference(np.zeros(2))
        reference.move([1, -.2], 0, 3)
        previous = reference.sample(1.1)
        reference.move([-.2, .3], 1.1, 2)
        for before, after in zip(previous, reference.sample(1.1)):
            np.testing.assert_allclose(before, after, atol=1e-12)
        q, v, a = reference.sample(3.1)
        np.testing.assert_allclose(q, [-.2, .3], atol=1e-12)
        np.testing.assert_allclose(v, 0, atol=1e-12)
        np.testing.assert_allclose(a, 0, atol=1e-12)

    def test_model_and_continuous_pose_changes_without_state_overwrite(self):
        c = self.controller()
        self.assertEqual((c.model.nq, c.model.nv, c.model.nu), (19, 18, 12))
        self.assertEqual(c.model.vis.global_.cameraid, c.model.camera("course_follow").id)
        self.assertEqual(c.model.cam_mode[0], mujoco.mjtCamLight.mjCAMLIGHT_TRACKCOM)
        initial = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
        c.configure({"squat": .15})
        np.testing.assert_array_equal(c.data.qpos, initial[0])
        np.testing.assert_array_equal(c.data.qvel, initial[1])
        self.assertEqual(c.data.time, initial[2])
        self.advance(c, 1)
        previous = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
        ref = c.reference.sample(c.data.time)
        c.configure({"squat": .08, "lean": .01, "shift": .01})
        np.testing.assert_array_equal(c.data.qpos, previous[0])
        np.testing.assert_array_equal(c.data.qvel, previous[1])
        self.assertEqual(c.data.time, previous[2])
        for before, after in zip(ref, c.reference.sample(c.data.time)):
            np.testing.assert_allclose(before, after, atol=1e-12)
        c.step()
        self.assertLess(np.max(np.abs(c.data.qpos-previous[0])), .01)
        self.advance(c, 5)
        self.assertFalse(c.state()["fallen"])
        self.assertGreater(np.linalg.norm(c.data.qpos[7:]-HOME), .04)

    def test_default_standing_contacts_and_weight(self):
        c = self.controller("g1-contact")
        self.advance(c, 6)
        state = c.state()
        self.assertFalse(state["fallen"])
        self.assertGreater(len(state["support_polygon"]), 2)
        self.assertGreater(state["support_margin_m"], 0)
        force = np.array(state["foot_forces"])[:, 2]
        self.assertTrue(np.all(force > 100))
        self.assertAlmostEqual(sum(force), c.model.body_subtreemass[c.root]*9.81, delta=2)

    def test_walk_and_smooth_stop_keep_physical_state_and_memory(self):
        c = self.controller("g1-walking")
        self.advance(c, 1)
        previous = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
        c.start_walk()
        np.testing.assert_array_equal(c.data.qpos, previous[0])
        np.testing.assert_array_equal(c.data.qvel, previous[1])
        self.assertEqual(c.data.time, previous[2])
        self.advance(c, 7)
        self.assertFalse(c.state()["fallen"])
        self.assertGreater(c.state()["displacement_m"], .8)
        old_command = c.command_reference.sample(c.data.time)
        memory = c.policy.hidden.copy()
        c.stop_walk()
        np.testing.assert_array_equal(c.policy.hidden, memory)
        for before, after in zip(old_command, c.command_reference.sample(c.data.time)):
            np.testing.assert_allclose(before, after, atol=1e-12)
        self.advance(c, 5)
        np.testing.assert_allclose(c.state()["command"], 0, atol=1e-10)
        self.assertFalse(c.state()["fallen"])

    def test_force_envelope_and_payload_preserve_physical_state(self):
        c = self.controller("g1-recovery")
        c.start_walk()
        self.advance(c, 3)
        before = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
        c.configure({"push_force": 20, "push_duration": .4, "payload": 1})
        c.push()
        np.testing.assert_array_equal(c.data.qpos, before[0])
        np.testing.assert_array_equal(c.data.qvel, before[1])
        self.assertEqual(c.data.time, before[2])
        c.step()
        self.assertAlmostEqual(c.data.xfrc_applied[c.root, 0], 0)
        self.advance(c, .2)
        self.assertAlmostEqual(c.data.xfrc_applied[c.root, 0], 20, delta=.02)
        self.advance(c, .4)
        self.assertEqual(c.data.xfrc_applied[c.root, 0], 0)
        self.assertFalse(c.state()["fallen"])
        c.reset()
        self.assertEqual(c.data.time, 0)
        self.assertEqual(c.model.body_mass[c.root], c.initial_mass)
        np.testing.assert_array_equal(c.data.qpos[7:], HOME)
        np.testing.assert_array_equal(c.policy.hidden, 0)

    def test_invalid_settings_are_atomic_and_api_returns_422(self):
        cases = [{"squat": None}, {"duration": 0}, {"lean": float("nan")},
                 {"command": [1, 0, 0]}, {"command": {}}, {"unknown": 0},
                 {"friction": .5, "payload": -1}]
        c = self.controller()
        for values in cases:
            before = c.settings.copy()
            with self.assertRaises(ValueError):
                c.configure(values)
            self.assertEqual(before, c.settings)
            self.assertEqual(c.model.geom_friction[c.floor, 0], 1)
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            response = client.post("/api/runs", json={"experiment_id": "g1-structure", "duration": .002,
                                                      "settings": {"squat": None}})
            self.assertEqual(response.status_code, 422)
            result = client.post("/api/runs", json={"experiment_id": "g1-structure", "duration": .004}).json()
            self.assertEqual(result["state"]["robot"], "g1")
            self.assertEqual(len(result["initial_qpos"]), 19)
            self.assertEqual(len(result["state"]["joints"]), 12)

    def test_all_lessons_simulate_and_recovery_has_real_force(self):
        for mode in ("g1-structure", "g1-contact", "g1-balance", "g1-walking", "g1-recovery"):
            with self.subTest(mode=mode):
                result = simulate(get_experiment(mode), duration=6)
                self.assertEqual(result["state"]["robot"], "g1")
                self.assertEqual(result["metrics"]["fallen_samples"], 0)
                if mode == "g1-recovery":
                    self.assertGreater(max(s["push_force_N"] for s in result["samples"]), 19)

    def test_studio_commands_work_for_humanoid_and_reject_panda_actions(self):
        from robotics_lab.studio import CourseStudio
        from mujoco.experimental.studio import sim
        with tempfile.TemporaryDirectory() as directory:
            m,d = load_model(get_experiment("g1-walking"))
            plugin = CourseStudio(m,d,"g1-walking",Path(directory)/"bridge",adapter="humanoid")
            plugin.step_control.set_pause_state(sim.PauseState.NORMAL_PAUSED)
            path = plugin.bridge.with_suffix(".command.json")
            for index, action in enumerate(["configure", "step", "walk", "walk-stop", "grasp", "reset"]):
                path.write_text(json.dumps({"id": str(index), "action": action,
                                            "settings": {"command": [.2, 0, 0]}}), encoding="utf-8")
                plugin._command()
                if action == "grasp":
                    self.assertIsNotNone(plugin.command_error)
                else:
                    self.assertIsNone(plugin.command_error)
                if action == "configure":
                    self.assertEqual(d.time, 0)
                if action == "step":
                    self.assertAlmostEqual(d.time, .002)


if __name__ == "__main__":
    unittest.main()
