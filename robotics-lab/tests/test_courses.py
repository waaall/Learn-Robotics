import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from unittest.mock import Mock

import mujoco
import numpy as np
from fastapi.testclient import TestClient

from robotics_lab.catalog import catalog, get_experiment
from robotics_lab.curriculum import courses
from robotics_lab.panda import HOME, PandaController, solve_ik
from robotics_lab.physics import load_model, simulate


class CourseTests(unittest.TestCase):
    def test_course_lessons_resolve_and_have_complete_content(self):
        items = courses()
        self.assertEqual([len(c["lessons"]) for c in items], [8, 2])
        identifiers = []
        for course in items:
            for lesson in course["lessons"]:
                identifiers.append(lesson["id"])
                self.assertIn(lesson["experiment_id"], catalog())
                for key in ("question", "concepts", "steps", "observations", "exercise", "sources"):
                    self.assertTrue(lesson[key])
        self.assertEqual(len(set(identifiers)), len(identifiers))

    def test_lesson_and_numeric_record_api(self):
        from robotics_lab.api import create_app
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            self.assertEqual(client.get("/api/courses").status_code, 200)
            self.assertEqual(client.get("/api/lessons/panda-ik").json()["number"], 6)
            self.assertEqual(client.get("/api/lessons/missing").status_code, 404)
            response = client.post("/api/runs", json={"experiment_id": "panda-ik", "duration": 0.01,
                                                       "settings": {"target": [0.45, 0.12, 0.42]}})
            self.assertEqual(response.status_code, 201)
            result = response.json()
            self.assertTrue(result["state"]["ik"]["converged"])
            self.assertEqual(client.get(f'/api/runs/{result["id"]}').json(), result)
            self.assertEqual(client.post("/api/runs", json={"experiment_id": "panda-fk", "duration": 0.01,
                                                            "settings": {"joints": [99] * 7}}).status_code, 422)

    def test_invalid_setting_types_return_validation_errors(self):
        from robotics_lab.api import create_app
        cases = [
            ({"gripper_width": None}, "夹爪开口"),
            ({"gain_scale": None}, "增益倍率"),
            ({"profile": []}, "轨迹类型"),
            ({"friction": {}}, "滑动摩擦系数"),
            ({"joints": [{}] * 7}, "关节目标"),
            ({"target": {}}, "末端目标"),
            ({"velocity": [None] * 7}, "关节速度"),
        ]
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            for settings, field in cases:
                with self.subTest(settings=settings):
                    response = client.post("/api/runs", json={
                        "experiment_id": "panda-fk", "duration": 0.001, "settings": settings})
                    self.assertEqual(response.status_code, 422)
                    self.assertIn(field, response.json()["detail"])
            # 校验失败后仍能正常计算和保存记录。
            self.assertEqual(client.post("/api/runs", json={
                "experiment_id": "panda-fk", "duration": 0.001,
                "settings": {"gripper_width": 0.04}}).status_code, 201)

    def test_temporarily_unreadable_state_retains_last_valid_observation(self):
        from robotics_lab.sessions import Session, SessionManager
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.log"
            process = Mock()
            process.poll.return_value = None
            manager = SessionManager(Path(directory))
            manager.session = Session("session", "panda-fk", 1234, process, 0, path, True)
            state_path = path.with_suffix(".state.json")
            self.assertIsNone(manager.state())
            state_path.write_text(json.dumps({"time": 1.0, "written_at": 0}), encoding="utf-8")
            self.assertEqual(manager.state()["time"], 1)
            state_path.write_text("{", encoding="utf-8")
            self.assertEqual(manager.state()["time"], 1)


class PandaTests(unittest.TestCase):
    def make_controller(self, mode="fk"):
        model, data = load_model(get_experiment("panda-" + mode))
        return PandaController(model, data, mode)

    def test_model_keyframe_restores_state_and_actuator_targets(self):
        c = self.make_controller()
        self.assertEqual((c.model.nq, c.model.nv, c.model.nu), (16, 15, 8))
        np.testing.assert_allclose(c.data.qpos[:7], HOME)
        np.testing.assert_allclose(c.data.ctrl[:7], HOME)
        self.assertEqual(c.data.ctrl[7], 255)
        c.configure({"joints": (HOME + [0.2, 0, 0, 0, 0, 0, 0]).tolist()})
        c.reset()
        np.testing.assert_allclose(c.data.qpos[:7], HOME)

    def test_jacobian_matches_finite_difference(self):
        c = self.make_controller("jacobian")
        state = c.state()
        initial = c.data.site_xpos[c.tool].copy()
        c.data.qpos[1] += 1e-6
        mujoco.mj_forward(c.model, c.data)
        difference = (c.data.site_xpos[c.tool] - initial) / 1e-6
        np.testing.assert_allclose(difference, np.array(state["jacobian"])[:, 1], atol=1e-5)

    def test_ik_reports_reachable_and_unreachable_targets(self):
        c = self.make_controller("ik")
        c.configure({"target": [0.45, 0.12, 0.42]})
        self.assertTrue(c.state()["ik"]["converged"])
        self.assertLess(c.state()["ik"]["position_error_m"], 1e-4)
        _, result = solve_ik(c.model, c.data.qpos, [2, 2, 2])
        self.assertFalse(result["converged"])
        self.assertGreater(result["position_error_m"], 1)

    def test_pd_moves_through_dynamics_and_tracks_goal(self):
        c = self.make_controller("joint-control")
        target = HOME.copy()
        target[0] += 0.2
        c.configure({"joints": target.tolist()})
        np.testing.assert_allclose(c.data.qpos[:7], HOME)
        for _ in range(2000):
            c.step()
        self.assertLess(np.linalg.norm(c.data.qpos[:7] - target), 0.01)

    def test_gravity_compensation_changes_physical_response(self):
        c = self.make_controller("gravity")
        for _ in range(500):
            c.step()
        held_error = np.linalg.norm(c.data.qpos[:7] - HOME)
        c.reset()
        c.configure({"compensation": False})
        for _ in range(500):
            c.step()
        falling_error = np.linalg.norm(c.data.qpos[:7] - HOME)
        self.assertLess(held_error, 0.01)
        self.assertGreater(falling_error, 0.1)

    def test_trajectory_updates_reference_and_converges(self):
        c = self.make_controller("trajectory")
        target = HOME.copy()
        target[0] = 0.2
        c.configure({"joints": target.tolist()})
        c.start_motion()
        for _ in range(4000):
            c.step()
        np.testing.assert_allclose(c.reference_q, target, atol=1e-8)
        self.assertLess(np.linalg.norm(c.data.qpos[:7] - target), 0.01)

    def test_grasp_lifts_and_places_through_contacts(self):
        result = simulate(get_experiment("panda-grasp"))
        print("grasp validation:", result["state"]["cube_position"], result["state"]["max_cube_height"],
              result["state"]["place_success"], flush=True)
        self.assertTrue(result["state"]["grasp_lifted"])
        self.assertTrue(result["state"]["place_success"])

    def test_applying_parameters_during_grasp_preserves_motion_and_success(self):
        c = self.make_controller("grasp")
        c.start_grasp()
        settings = {"joints": HOME.tolist(), "target": [0.45, 0.12, 0.42],
                    "gripper_width": 0.08, "gain_scale": 1.0, "compensation": True,
                    "velocity": [0] * 7, "profile": "quintic", "friction": 1.0}
        for step in range(18000):
            c.step()
            # 同时覆盖下降阶段的关节目标与抬升阶段的闭合夹爪。
            if step + 1 in {2500, 6000}:
                target_q, target, reference = c.target_q.copy(), c.target.copy(), c.reference_q.copy()
                width, phase = c.width, c.phase
                c.configure({**settings, "friction": 0.8})
                self.assertEqual(c.friction, 0.8)
                c.configure(settings)
                np.testing.assert_array_equal(c.target_q, target_q)
                np.testing.assert_array_equal(c.target, target)
                np.testing.assert_array_equal(c.reference_q, reference)
                self.assertEqual(c.width, width)
                self.assertEqual(c.phase, phase)
        state = c.state()
        self.assertTrue(state["grasp_lifted"])
        self.assertTrue(state["place_success"])

    def test_studio_percent_speed_and_single_step(self):
        from mujoco.experimental.studio import messages, sim
        from robotics_lab.studio import PandaStudio
        c = self.make_controller()
        with tempfile.TemporaryDirectory() as directory:
            plugin = PandaStudio(c.model, c.data, "fk", Path(directory) / "bridge")
            event = messages.StepEvent(c.model, c.data)
            plugin.last_tick = 10
            with patch("robotics_lab.studio.time.monotonic", return_value=10.01), patch("robotics_lab.studio.time.sleep"):
                plugin._on_step(event)
            self.assertGreater(c.data.time, 0.008)
            self.assertLessEqual(c.data.time, 0.011)
            plugin.step_control.set_pause_state(sim.PauseState.NORMAL_PAUSED)
            before = c.data.time
            plugin.step_control.request_single_step()
            with patch("robotics_lab.studio.time.monotonic", return_value=10.02), patch("robotics_lab.studio.time.sleep"):
                plugin._on_step(event)
            self.assertAlmostEqual(c.data.time - before, 0.001)
            # 命令在被替换时短暂不可见，下一轮仍应执行并确认同一请求。
            path = plugin.bridge.with_suffix(".command.json")
            path.write_text(json.dumps({"id": "command-test", "action": "reset"}), encoding="utf-8")
            with patch("robotics_lab.studio.Path.read_text", side_effect=FileNotFoundError):
                plugin._command()
            self.assertIsNone(plugin.command_id)
            plugin._command()
            self.assertEqual(plugin.command_id, "command-test")
            self.assertAlmostEqual(c.data.time, 0)


if __name__ == "__main__":
    unittest.main()
