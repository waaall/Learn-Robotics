from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from robotics_lab.api import create_app
from robotics_lab.catalog import get_experiment
from robotics_lab.physics import load_model, simulate
from robotics_lab.sessions import Session, SessionManager


class PhysicsTests(unittest.TestCase):
    def test_initial_keyframe_restores_configured_state(self):
        import mujoco
        model, data = load_model(get_experiment("pendulum"))
        data.qpos[0] = -0.9
        mujoco.mj_resetDataKeyframe(model, data, 0)
        self.assertAlmostEqual(data.qpos[0], 0.4)

    def test_pendulum_energy_and_motion(self):
        result = simulate(get_experiment("pendulum"))
        self.assertLess(result["metrics"]["max_energy_drift_J"], 1e-9)
        self.assertLess(min(point["value"] for point in result["samples"]), -0.35)
        self.assertAlmostEqual(result["samples"][-1]["time"], 2.0)

    def test_contact_support_and_soft_penetration(self):
        result = simulate(get_experiment("drop-ball"))
        self.assertAlmostEqual(result["metrics"]["mean_support_N"], 9.81, places=5)
        self.assertAlmostEqual(result["final_qpos"][2], 0.1, delta=0.001)
        self.assertGreater(result["metrics"]["max_penetration_m"], 0)

    def test_nonintegral_step_count_rejected(self):
        with self.assertRaises(ValueError):
            simulate(get_experiment("pendulum"), 0.0105)


class SessionTests(unittest.TestCase):
    def test_running_viewer_is_not_subject_to_startup_deadline(self):
        process = Mock()
        process.poll.return_value = None
        manager = SessionManager(Path("unused"))
        manager.session = Session("test", "pendulum", 12345, process,
                                  time.monotonic() - 60, Path("unused.log"), ready=True)
        with patch("robotics_lab.sessions.urlopen", side_effect=TimeoutError):
            self.assertEqual(manager.status()["status"], "ready")
        process.terminate.assert_not_called()

    def test_unready_viewer_is_terminated_after_startup_deadline(self):
        process = Mock()
        process.poll.return_value = None
        manager = SessionManager(Path("unused"))
        manager.session = Session("test", "pendulum", 12345, process,
                                  time.monotonic() - 60, Path("unused.log"))
        with patch("robotics_lab.sessions.urlopen", side_effect=TimeoutError):
            self.assertEqual(manager.status()["status"], "failed")
        process.terminate.assert_called_once()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.directory.name)))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def test_run_saved_and_read_back(self):
        response = self.client.post("/api/runs", json={"experiment_id": "drop-ball"})
        self.assertEqual(response.status_code, 201)
        result = response.json()
        restored = self.client.get(f'/api/runs/{result["id"]}')
        self.assertEqual(restored.json(), result)
        self.assertEqual(len(result["model_sha256"]), 64)

    def test_missing_experiment_and_bad_duration_are_errors(self):
        for payload in ({"experiment_id": "missing"}, {"experiment_id": "pendulum", "duration": 11}):
            self.assertEqual(self.client.post("/api/runs", json=payload).status_code, 422)

    def test_missing_viewer_is_reported_without_starting_a_process(self):
        with patch("robotics_lab.sessions.viewer_capability", return_value={"available": False, "reason": "组件缺失"}):
            response = self.client.post("/api/sessions", json={"experiment_id": "pendulum"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "组件缺失")
        self.assertIsNone(self.client.get("/api/sessions/current").json())

    def test_invalid_run_identifier_cannot_read_other_files(self):
        self.assertEqual(self.client.get("/api/runs/not-a-uuid").status_code, 422)


if __name__ == "__main__":
    unittest.main()
