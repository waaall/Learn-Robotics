"""课时预设的 API 一致性、轨迹待执行行为与交互重置回归。"""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from fastapi.testclient import TestClient

from robotics_lab.api import create_app
from robotics_lab.catalog import get_experiment
from robotics_lab.curriculum import courses
from robotics_lab.panda import HOME, PandaController, default_settings
from robotics_lab.physics import load_model, simulate
from robotics_lab.studio import CourseStudio


class LessonPresetTests(unittest.TestCase):
    def test_short_push_trace_survives_reads_after_pulse_ends(self):
        from robotics_lab.humanoid import HumanoidController
        model, data = load_model(get_experiment("g1-recovery"))
        c = HumanoidController(model, data, "g1-recovery")
        c.push()
        for _ in range(500):
            c.step()
        state = c.state()
        self.assertEqual(state["push_force_N"], 0)
        self.assertGreater(max(force for _,force in state["push_trace"]), 19.9)
        self.assertEqual(state["push_trace"][-1][1], 0)
        c.reset()
        self.assertEqual(c.state()["push_trace"], [])

    def test_course_api_and_omitted_run_settings_use_same_presets(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            items = client.get("/api/courses").json()
            for course in items:
                for lesson in course["lessons"]:
                    if lesson["adapter"] == "basic":
                        continue
                    preset = lesson["default_settings"]
                    expected = preset.get(lesson["adapter"], preset)
                    record = client.post("/api/runs", json={
                        "experiment_id": lesson["id"], "duration": .01}).json()
                    self.assertEqual(record["settings"], expected, lesson["id"])

    def test_trajectory_waits_for_start_and_finishes_at_selected_endpoint(self):
        model, data = load_model(get_experiment("panda-trajectory"))
        c = PandaController(model, data, "trajectory")
        c.configure(default_settings("trajectory"))
        for _ in range(500):
            c.step()
        np.testing.assert_allclose(data.qpos[:7], HOME, atol=.001)
        self.assertGreater(np.linalg.norm(c.target_q-HOME), .3)
        c.start_motion()
        for _ in range(4000):
            c.step()
        np.testing.assert_allclose(data.qpos[:7], c.target_q, atol=.001)
        previous = data.qpos[:7].copy()
        c.configure({"joints": HOME.tolist()})
        # 已执行的轨迹终点保留，编辑下一次终点不会立即移动。
        for _ in range(100):
            c.step()
        np.testing.assert_allclose(data.qpos[:7], previous, atol=.001)
        c.start_motion()
        for _ in range(4000):
            c.step()
        np.testing.assert_allclose(data.qpos[:7], HOME, atol=.001)

    def test_studio_reset_reapplies_visible_lesson_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            for course in courses():
                for lesson in course["lessons"]:
                    if lesson["adapter"] == "basic":
                        continue
                    model, data = load_model(get_experiment(lesson["id"]))
                    bridge = Path(directory)/lesson["id"]
                    studio = CourseStudio(model, data, lesson["mode"], bridge, adapter=lesson["adapter"])
                    studio.controller.step()
                    bridge.with_suffix(".command.json").write_text(json.dumps({"id":"reset", "action":"reset"}))
                    studio._command()
                    self.assertIsNone(studio.command_error)
                    self.assertEqual(data.time, 0)
                    preset = lesson["default_settings"]
                    if lesson["adapter"] == "humanoid":
                        self.assertEqual(studio.controller.settings, preset["humanoid"])
                    elif lesson["adapter"] == "microduck":
                        self.assertEqual(studio.controller.settings, preset["microduck"])
                    elif lesson["mode"] != "ik":
                        np.testing.assert_allclose(studio.controller.target_q, preset["joints"])
                    else:
                        np.testing.assert_allclose(studio.controller.target, preset["target"])


if __name__ == "__main__":
    unittest.main()
