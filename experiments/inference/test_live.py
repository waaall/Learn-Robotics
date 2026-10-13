"""实时适配边界：RGB／状态格式、只读清理与失败记录；不打开硬件。"""

from dataclasses import replace
import json
import hashlib
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from smolvla_inference import live
from smolvla_inference.live_hardware import JOINTS, ReadOnlyFollower, validate_raw


class LiveAdapterTests(unittest.TestCase):
    def test_manual_weights_are_verified_before_replacing_existing_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, target = folder / "download", folder / "model.safetensors"
            source.write_bytes(b"downloaded model")
            target.write_bytes(b"existing model")
            with self.assertRaises(ValueError):
                live.import_weights(source, target, source.stat().st_size, "0" * 64)
            self.assertEqual(target.read_bytes(), b"existing model")
            self.assertFalse(list(folder.glob("*.partial")))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            live.import_weights(source, target, source.stat().st_size, digest)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_config_resolves_paths_without_current_directory(self):
        cfg = live.load_config(live.DEFAULT_CONFIG)
        self.assertTrue(cfg.calibration.is_absolute())
        self.assertEqual(cfg.follower_serial, "5C82109737")
        self.assertEqual(cfg.cache_dir.name, "smolvla-live")

    def test_image_is_single_rgb_chw_and_state_preserves_joint_order(self):
        frame = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)
        observation = live.build_observation(frame, [1, 2, 3, 4, 5, 6], "pick")
        self.assertEqual(set(observation), {live.IMAGE_KEY, "observation.state", "task"})
        np.testing.assert_allclose(observation[live.IMAGE_KEY][:, 0, 0].numpy(), [30/255, 20/255, 10/255])
        self.assertEqual(tuple(observation[live.IMAGE_KEY].shape), (3, 1, 2))
        np.testing.assert_equal(observation["observation.state"].numpy(), [1, 2, 3, 4, 5, 6])
        with self.assertRaises(ValueError):
            live.build_observation(frame, [1, 2, 3, 4, 5, np.nan], "pick")

    def test_invalid_action_dimensions_and_nonfinite_values_stop(self):
        live.validate_prediction(np.zeros((1, 50, 6)), 50)
        for prediction in (np.zeros((1, 50, 32)), np.full((1, 50, 6), np.inf)):
            with self.assertRaises(ValueError):
                live.validate_prediction(prediction, 50)

    def test_encoder_fault_stops_and_calibration_excursion_is_visible(self):
        calibration = {joint: SimpleNamespace(range_min=100, range_max=4000) for joint in JOINTS}
        raw = dict.fromkeys(JOINTS, 2000)
        raw["elbow_flex"] = 4087
        self.assertTrue(validate_raw(raw, calibration)["elbow_flex"]["input_clipped"])
        raw["elbow_flex"] = 4150
        with self.assertRaises(ValueError):
            validate_raw(raw, calibration)

    def test_close_explicitly_does_not_disable_torque(self):
        follower = ReadOnlyFollower.__new__(ReadOnlyFollower)
        follower.bus = Mock(is_connected=True)
        follower.close()
        follower.bus.disconnect.assert_called_once_with(disable_torque=False)
        follower.bus.write.assert_not_called()
        follower.bus.disable_torque.assert_not_called()

    def test_calibration_mismatch_closes_without_rewriting_it(self):
        follower = ReadOnlyFollower.__new__(ReadOnlyFollower)
        expected = SimpleNamespace(range_min=100, range_max=4000, homing_offset=20)
        actual = SimpleNamespace(range_min=100, range_max=4000, homing_offset=21)
        follower.calibration = dict.fromkeys(JOINTS, expected)
        follower.bus = Mock(is_connected=True)
        follower.bus.read_calibration.return_value = dict.fromkeys(JOINTS, actual)
        with self.assertRaises(ValueError):
            follower.open()
        follower.bus.disconnect.assert_called_once_with(disable_torque=False)
        follower.bus.write_calibration.assert_not_called()
        follower.bus.write.assert_not_called()

    def test_torque_enabled_aborts_read(self):
        follower = ReadOnlyFollower.__new__(ReadOnlyFollower)
        follower.bus = Mock()
        follower.bus.read.return_value = 1
        with self.assertRaises(RuntimeError):
            follower.read()
        follower.bus.read.assert_called_once_with("Torque_Enable", JOINTS[0], normalize=False, num_retry=2)
        follower.bus.write.assert_not_called()

    def test_hardware_failure_is_recorded_and_both_resources_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = replace(live.load_config(live.DEFAULT_CONFIG), output_dir=Path(temporary), samples=1)
            camera, follower = Mock(), Mock()
            camera.open.side_effect = RuntimeError("camera unavailable")
            with patch.object(live, "LatestCamera", return_value=camera), \
                    patch.object(live, "ReadOnlyFollower", return_value=follower):
                with self.assertRaisesRegex(RuntimeError, "camera unavailable"):
                    live.run(cfg, capture_only=True)
            reports = list(Path(temporary).glob("*/report.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["samples"], 0)
            self.assertEqual(report["robot_actions_sent"], 0)
            camera.close.assert_called_once()
            follower.close.assert_called_once()

    def test_continuous_prediction_resets_once_and_saves_new_observations(self):
        import torch
        import smolvla_inference.engine as engine
        with tempfile.TemporaryDirectory() as temporary:
            cfg = replace(live.load_config(live.DEFAULT_CONFIG), output_dir=Path(temporary),
                          samples=2, warmup_runs=1)
            camera, follower = Mock(metadata={}), Mock(metadata={})
            frame = np.zeros((2, 3, 3), dtype=np.uint8)
            camera.after.side_effect = lambda sequence: (sequence + 1, time.perf_counter(), frame)
            follower.read.side_effect = lambda: {"raw": dict.fromkeys(JOINTS, 2048),
                "state": [1, 2, 3, 4, 5, 6], "warnings": {},
                "read_start_monotonic": time.perf_counter(), "read_end_monotonic": time.perf_counter()}
            policy = Mock(config=SimpleNamespace(chunk_size=50, num_steps=10, max_action_dim=32, use_amp=False))
            def predict(batch, noise):
                self.assertNotIn("action", batch)
                self.assertEqual(set(k for k in batch if k.startswith("observation.images.")), {live.IMAGE_KEY})
                self.assertFalse(torch.is_grad_enabled())
                return torch.ones(1, 50, 6)
            policy.predict_action_chunk.side_effect = predict
            with patch.object(live, "LatestCamera", return_value=camera), \
                    patch.object(live, "ReadOnlyFollower", return_value=follower), \
                    patch.object(live, "load_model", return_value=(policy, lambda x:x, lambda x:x * 3, {}, {})), \
                    patch.object(engine, "sample_noise", return_value=torch.zeros(1, 50, 32)), \
                    patch.object(torch.cuda, "synchronize"), patch.object(torch.cuda, "reset_peak_memory_stats"), \
                    patch.object(torch.cuda, "max_memory_allocated", return_value=0), \
                    patch.object(torch.cuda, "max_memory_reserved", return_value=0):
                report_path = live.run(cfg)
            policy.reset.assert_called_once()
            policy.select_action.assert_not_called()
            self.assertEqual(policy.predict_action_chunk.call_count, 3)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["samples"], 2)
            self.assertEqual(report["robot_actions_sent"], 0)
            with np.load(report_path.parent / "actions.npz") as output:
                np.testing.assert_equal(output["predicted"], np.full((2, 50, 6), 3))
                np.testing.assert_equal(output["frame_sequence"], [2, 3])
            camera.close.assert_called_once()
            follower.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
