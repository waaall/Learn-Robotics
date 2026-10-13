"""独立推理测试：观测筛选、固定噪声、处理器与失败报告，不导入训练项目。"""

from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from smolvla_common.config import DatasetConfig, ExperimentConfig, PolicyConfig
from smolvla_common.protocol import read_json, write_json
from smolvla_inference.config import load_config as load_job
from smolvla_inference.engine import observation_only, predict_chunk, sample_noise
CONFIG = Path(__file__).parent / "configs/smolvla-offline.toml"


class AdapterTests(unittest.TestCase):
    def test_failed_inference_replaces_previous_success_status(self):
        import smolvla_inference.engine as inference
        with tempfile.TemporaryDirectory() as temporary:
            cfg = replace(load_job(CONFIG), output_dir=Path(temporary))
            report = cfg.output_dir / "baseline" / "report.json"
            write_json(report, {"status": "completed", "old_metric": 1})
            frozen = ExperimentConfig(Path(temporary), Path(temporary), DatasetConfig("fixture/data"), PolicyConfig("fixture/model"))
            with patch.object(inference, "configure_cache"), patch.object(inference, "read_prepared", return_value={"config": frozen.to_dict()}), \
                    patch.object(inference, "_infer_prepared", side_effect=RuntimeError("模拟 OOM")):
                with self.assertRaises(RuntimeError):
                    inference.infer(cfg, baseline=True)
            self.assertEqual(read_json(report)["status"], "failed")
            self.assertNotIn("old_metric", read_json(report))

    def test_future_actions_are_removed_from_inference(self):
        result = observation_only({"observation.state": [1], "observation.images.top": [2],
                                   "task": "pick", "action": [999], "action_is_pad": [False], "next.state": [3]})
        self.assertEqual(set(result), {"observation.state", "observation.images.top", "task"})


    def test_noise_is_repeatable_and_has_action_shape_not_state_shape(self):
        import torch
        cfg = SimpleNamespace(chunk_size=4, max_action_dim=8)
        first = sample_noise(cfg, 123, 7, "cpu")
        torch.testing.assert_close(first, sample_noise(cfg, 123, 7, "cpu"))
        self.assertEqual(tuple(first.shape), (1, 4, 8))
        self.assertFalse(torch.equal(first, sample_noise(cfg, 123, 8, "cpu")))

    def test_cpu_prediction_uses_processors_reset_and_no_future_labels(self):
        import torch
        calls = []
        class Policy:
            config = SimpleNamespace(use_amp=False)
            def reset(self):
                calls.append("reset")
            def predict_action_chunk(self, batch, noise):
                self_outer.assertNotIn("action", batch)
                self_outer.assertFalse(torch.is_grad_enabled())
                calls.append("predict")
                return noise[:, :, :2] + batch["observation.state"].unsqueeze(1)
        self_outer = self
        def preprocess(batch):
            calls.append("preprocess")
            return batch
        def postprocess(action):
            calls.append("postprocess")
            return action * 2
        noise = torch.zeros(1, 3, 4)
        result, timing = predict_chunk(Policy(), preprocess, postprocess,
                                      {"observation.state": torch.tensor([[1., 2.]]), "action": torch.ones(1, 3, 2)},
                                      noise, lambda: None)
        self.assertEqual(calls, ["reset", "preprocess", "predict", "postprocess"])
        np.testing.assert_equal(result, [[[2, 4]] * 3])
        self.assertEqual(set(timing), {"preprocess_ms", "inference_ms", "postprocess_ms"})

if __name__ == "__main__":
    unittest.main()
