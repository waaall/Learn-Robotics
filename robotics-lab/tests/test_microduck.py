"""官方策略等价性、接触与执行器摩擦、物理任务结果及跨课程操作隔离。"""
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
from robotics_lab.microduck_actuator import friction_budget
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

    def test_actuator_removes_own_dof_friction_from_external_load(self):
        c = self.controller("microduck-contact")
        self.advance(c, .2)
        m, d = c.model, c.data
        self.assertTrue(np.any(c.joint_ids != c.vadr))
        # 用约束雅可比投影取得独立对照，避免测试重复关节编号匹配错误。
        friction_rows = d.efc_type == mujoco.mjtConstraint.mjCNSTR_FRICTION_DOF
        constraint_forces = np.where(friction_rows, d.efc_force, 0.)
        friction_forces = np.zeros(m.nv)
        mujoco.mj_mulJacTVec(m, d, friction_forces, constraint_forces)
        self.assertGreater(np.linalg.norm(friction_forces[c.vadr]), 1e-6)
        external = -d.qfrc_bias[c.vadr] + d.qfrc_constraint[c.vadr] - friction_forces[c.vadr]
        expected_friction, expected_damping = friction_budget(
            d.qfrc_actuator[c.vadr], external, d.qvel[c.vadr])

        c.actuator.update(c.reference_q)

        np.testing.assert_allclose(m.dof_frictionloss[c.vadr], expected_friction, atol=1e-12, rtol=1e-12)
        np.testing.assert_allclose(m.dof_damping[c.vadr], expected_damping, atol=1e-12, rtol=1e-12)

    def test_ground_contact_friction_tracks_configuration_and_reset(self):
        for mode in ("microduck-contact", "microduck-robustness"):
            with self.subTest(mode=mode):
                c = self.controller(mode)
                self.advance(c, .2)
                robot_geoms = np.arange(c.model.ngeom) != c.floor
                original_friction = c.model.geom_friction[robot_geoms].copy()

                def assert_contact_friction(expected):
                    contacts = [contact for contact in c.data.contact
                                if c.floor in (contact.geom1, contact.geom2)]
                    self.assertTrue(contacts)
                    # 验证求解器实际使用的两个切向系数，不能只检查地面配置。
                    np.testing.assert_allclose([contact.friction[:2] for contact in contacts], expected)
                    np.testing.assert_array_equal(c.model.geom_friction[robot_geoms], original_friction)

                for coefficient in (.1, .5, 1., 2.):
                    with self.subTest(coefficient=coefficient):
                        before = c.data.qpos.copy(), c.data.qvel.copy(), c.data.time
                        c.configure({"friction": coefficient})
                        np.testing.assert_array_equal(c.data.qpos, before[0])
                        np.testing.assert_array_equal(c.data.qvel, before[1])
                        self.assertEqual(c.data.time, before[2])
                        mujoco.mj_forward(c.model, c.data)
                        assert_contact_friction(coefficient)
                        self.advance(c, .02)
                        assert_contact_friction(coefficient)

                c.reset()
                self.advance(c, .2)
                assert_contact_friction(default_settings(mode)["friction"])

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
