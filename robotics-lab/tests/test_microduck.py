"""官方策略等价性、物理任务结果与跨课程操作隔离。"""
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
import mujoco
import numpy as np

from robotics_lab.api import create_app
from robotics_lab.catalog import get_experiment
from robotics_lab.microduck import ASSETS, HOME, MicroduckController, MicroduckPolicy, default_settings
from robotics_lab.physics import load_model, simulate
from robotics_lab.studio import CourseStudio


class MicroduckTests(unittest.TestCase):
    def controller(self, mode="microduck-structure"):
        m, d = load_model(get_experiment(mode))
        c = MicroduckController(m, d, mode)
        c.configure(default_settings(mode))
        return c

    def advance(self, c, seconds):
        for _ in range(round(seconds/c.model.opt.timestep)):
            c.step()

    def test_numpy_policies_match_official_onnx(self):
        for name in ("walking", "sitstand"):
            with np.load(ASSETS / (name + "_reference.npz"), allow_pickle=False) as reference:
                policy = MicroduckPolicy(name)
                outputs = np.array([policy(o) for o in reference["observations"]])
                np.testing.assert_allclose(outputs, reference["actions"], atol=5e-6, rtol=2e-5)

    def test_structure_reference_updates_preserve_physical_state(self):
        c = self.controller()
        self.assertEqual((c.model.nq, c.model.nv, c.model.nu), (21, 20, 14))
        self.assertEqual(c.model.vis.global_.cameraid, c.model.camera("course_follow").id)
        self.advance(c, 1)
        before = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
        reference = c.reference.sample(c.data.time)
        c.configure({"joint_index": 7, "joint_offset": -.1})
        np.testing.assert_array_equal(c.data.qpos, before[0])
        np.testing.assert_array_equal(c.data.qvel, before[1])
        self.assertEqual(c.data.time, before[2])
        for a, b in zip(reference, c.reference.sample(c.data.time)):
            np.testing.assert_allclose(a, b, atol=1e-12)
        self.advance(c, 4)
        self.assertAlmostEqual(c.state()["joints"][7], -.1, delta=.03)
        self.assertFalse(c.state()["fallen"])

    def test_contact_force_matches_weight_and_head_moves(self):
        c = self.controller("microduck-contact")
        self.advance(c, 4)
        state = c.state()
        self.assertGreater(len(state["support_polygon"]), 2)
        self.assertGreater(state["support_margin_m"], 0)
        self.assertAlmostEqual(sum(f[2] for f in state["foot_forces"]), state["weight_N"], delta=.1)
        c = self.controller("microduck-head")
        self.advance(c, 4)
        self.assertAlmostEqual(c.state()["joints"][7], .25, delta=.03)
        self.assertFalse(c.state()["fallen"])

    def test_walk_stop_and_real_push(self):
        c = self.controller("microduck-robustness")
        # 网页打开后可以停留观察，启动前的站姿保持不能提前倾倒。
        self.advance(c, 3)
        self.assertFalse(c.state()["fallen"])
        c.start_walk()
        self.advance(c, 4)
        self.assertEqual(c.observation.shape, (61,))
        self.assertEqual(c.action.shape, (14,))
        self.assertGreater(c.state()["displacement_m"], .1)
        previous = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
        c.push()
        c.stop_walk()
        np.testing.assert_array_equal(c.data.qpos, previous[0])
        np.testing.assert_array_equal(c.data.qvel, previous[1])
        self.assertEqual(c.data.time, previous[2])
        self.advance(c, 4)
        self.assertGreater(max(f for _, f in c.push_trace), .95)
        self.assertEqual(c.state()["push_force_N"], 0)
        np.testing.assert_allclose(c.state()["command"], 0, atol=1e-12)
        self.assertFalse(c.state()["fallen"])
        self.assertTrue(c.policy_active)
        c.reset()
        np.testing.assert_array_equal(c.data.qpos[7:], HOME)
        self.assertEqual(c.push_trace, [])
        self.assertEqual(c.data.time, 0)

    def test_sit_and_stand_complete_through_dynamics(self):
        r = simulate(get_experiment("microduck-sitstand"))
        self.assertEqual(r["metrics"]["fallen_samples"], 0)
        self.assertLess(min(s["base_position"][2] for s in r["samples"]), .075)
        self.assertGreater(r["state"]["base_position"][2], .105)
        self.assertEqual(r["state"]["posture_command"], 0)

    def test_invalid_parameters_do_not_mutate_and_api_records_are_readable(self):
        c = self.controller()
        for settings in ({"joint_index": 1.5}, {"voltage": None}, {"head": [0, 0]},
                         {"command": [float("nan"), 0, 0]}, {"friction": .2, "push_force": 10},
                         {"joint_offset": True}, {"unknown": 1}):
            before = c.settings.copy()
            with self.assertRaises(ValueError):
                c.configure(settings)
            self.assertEqual(c.settings, before)
            self.assertEqual(c.model.geom_friction[c.floor, 0], 1)
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            self.assertEqual(client.get("/api/lessons/microduck-walking").json()["course_id"], "microduck-basics")
            bad = client.post("/api/runs", json={"experiment_id": "microduck-head", "duration": .01, "settings": {"head": None}})
            self.assertEqual(bad.status_code, 422)
            response = client.post("/api/runs", json={"experiment_id": "microduck-head", "duration": .01})
            self.assertEqual(response.status_code, 201)
            result = response.json()
            self.assertEqual(result["state"]["robot"], "microduck")
            self.assertEqual(client.get('/api/runs/' + result["id"]).json(), result)

    def test_studio_pause_step_reset_and_action_isolation(self):
        from mujoco.experimental.studio import sim
        with tempfile.TemporaryDirectory() as directory:
            c = self.controller("microduck-sitstand")
            studio = CourseStudio(c.model, c.data, c.mode, Path(directory)/"bridge", adapter="microduck")
            studio.step_control.set_pause_state(sim.PauseState.NORMAL_PAUSED)
            for i, action in enumerate(("configure", "step", "sit", "stand", "grasp", "walk", "reset")):
                studio.bridge.with_suffix(".command.json").write_text(json.dumps({"id": str(i), "action": action}))
                studio._command()
                if action in {"grasp", "walk"}:
                    self.assertIsNotNone(studio.command_error)
                else:
                    self.assertIsNone(studio.command_error)
                if action == "step":
                    self.assertAlmostEqual(c.data.time, .002)
                if action == "reset":
                    self.assertEqual(c.data.time, 0)
                    self.assertFalse(studio.controller.sitting)


if __name__ == "__main__":
    unittest.main()
