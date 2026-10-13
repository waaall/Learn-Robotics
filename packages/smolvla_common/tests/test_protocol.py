"""共享协议无网络测试：保留原轨迹隔离、掩码、checkpoint 和统计量覆盖。"""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from smolvla_common.config import DatasetConfig, ExperimentConfig, PolicyConfig
from smolvla_common.protocol import compare_reports, latest_checkpoint, read_json, select_frame_indices, split_episodes, update_checkpoint_pointer, validate_checkpoint, validate_checkpoint_protocol, validate_schema, write_json
from smolvla_common.metrics import ActionMetrics, feature_stats, latency_summary
from smolvla_common.runtime import load_manifest


def schema():
    return {"codebase_version": "v3.0", "fps": 30, "features": {
        "observation.state": {"shape": [2], "dtype": "float32", "names": ["joint", "gripper"]},
        "action": {"shape": [2], "dtype": "float32", "names": ["joint", "gripper"]},
        "observation.images.top": {"shape": [48, 64, 3], "dtype": "video"},
    }}

def checkpoint(root, step, *, complete=True):
    path = root / "checkpoints" / f"{step:06d}"
    model = path / "pretrained_model"
    model.mkdir(parents=True)
    for name in ("config.json", "train_config.json"):
        write_json(model / name, {})
    (model / "model.safetensors").write_bytes(b"fixture")
    for name in ("policy_preprocessor.json", "policy_postprocessor.json"):
        registry = "normalizer_processor" if name == "policy_preprocessor.json" else "unnormalizer_processor"
        write_json(model / name, {"steps": [{"registry_name": registry, "state_file": "stats.safetensors"}]})
    (model / "stats.safetensors").write_bytes(b"fixture")
    state = path / "training_state"
    state.mkdir()
    for name in ("rng_state.safetensors", "optimizer_state.safetensors", "optimizer_param_groups.json", "scheduler_state.json"):
        (state / name).write_bytes(b"fixture")
    if complete:
        write_json(state / "training_step.json", {"step": step})
    return model

class ProtocolTests(unittest.TestCase):
    def test_split_is_complete_disjoint_and_deterministic(self):
        rows = [{"episode_index": i, "tasks": ["pick"]} for i in range(50)]
        split = split_episodes(rows, 0.2, 42)
        self.assertEqual(split, split_episodes(list(reversed(rows)), 0.2, 42))
        self.assertEqual((len(split["train"]), len(split["validation"])), (40, 10))
        self.assertFalse(set(split["train"]) & set(split["validation"]))
        self.assertEqual(sorted(split["train"] + split["validation"]), list(range(50)))

    def test_split_preserves_each_task(self):
        rows = [{"episode_index": i, "tasks": [str(i // 4)]} for i in range(8)]
        result = split_episodes(rows, 0.25, 2)
        self.assertEqual(len(result["validation"]), 2)
        self.assertEqual({i // 4 for i in result["validation"]}, {0, 1})

    def test_single_episode_task_and_duplicate_fail(self):
        for rows in ([{"episode_index": 0}], [{"episode_index": 0}, {"episode_index": 0}]):
            with self.assertRaises(ValueError):
                split_episodes(rows, 0.2, 42)

    def test_schema_dimensions_are_not_hardcoded(self):
        result = validate_schema(schema())
        self.assertEqual(result["action"]["shape"], [2])
        self.assertEqual(result["cameras"], ["observation.images.top"])

    def test_old_format_invalid_fps_missing_camera_fail(self):
        for change in ({"codebase_version": "v2.1"}, {"fps": 0}, {"fps": float('nan')}):
            with self.assertRaises(ValueError):
                validate_schema({**schema(), **change})
        info = schema(); del info["features"]["observation.images.top"]
        with self.assertRaises(ValueError):
            validate_schema(info)

    def test_duplicate_action_names_fail(self):
        info = schema(); info["features"]["action"]["names"] = ["joint", "joint"]
        with self.assertRaises(ValueError):
            validate_schema(info)

    def test_sampling_covers_episodes_and_respects_limit(self):
        episodes = [0] * 5 + [1] * 20 + [2] * 2
        indices = select_frame_indices(episodes, 9)
        self.assertEqual(len(indices), 9)
        self.assertEqual(len(set(indices)), 9)
        self.assertEqual({episodes[i] for i in indices}, {0, 1, 2})

    def test_sampling_short_data_and_too_small_budget(self):
        self.assertEqual(select_frame_indices([0, 0, 1], 100), [0, 1, 2])
        with self.assertRaises(ValueError):
            select_frame_indices([0, 1, 2], 2)

    def test_checkpoint_rejects_missing_processor_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = checkpoint(Path(temporary), 10)
            self.assertEqual(validate_checkpoint(model, resume=True), model)
            (model / "stats.safetensors").unlink()
            with self.assertRaises(ValueError):
                validate_checkpoint(model)

    def test_checkpoint_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = checkpoint(Path(temporary), 10)
            write_json(model / "policy_preprocessor.json", {"steps": [{"state_file": "../outside.safetensors"}]})
            with self.assertRaises(ValueError):
                validate_checkpoint(model)

    def test_latest_skips_partial_checkpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            complete = checkpoint(root, 10)
            checkpoint(root, 20, complete=False)
            self.assertEqual(latest_checkpoint(root), complete)

    def test_resume_requires_optimizer_rng_and_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = checkpoint(Path(temporary), 10)
            (model.parent / "training_state" / "rng_state.safetensors").unlink()
            validate_checkpoint(model)
            with self.assertRaises(ValueError):
                validate_checkpoint(model, resume=True)

    def test_checkpoint_pointer_does_not_require_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = checkpoint(Path(temporary), 10)
            with patch.object(Path, "symlink_to", side_effect=PermissionError("not permitted")):
                path = update_checkpoint_pointer(model.parent)
            self.assertEqual(read_json(path), {"checkpoint": "000010", "step": 10})

    def test_checkpoint_protocol_rejects_another_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = checkpoint(Path(temporary), 10)
            with self.assertRaises(ValueError):
                validate_checkpoint_protocol(model, "a", {"dataset": "sha"})
            write_json(model / "experiment.json", {"config_fingerprint": "a", "revisions": {"dataset": "sha"}})
            validate_checkpoint_protocol(model, "a", {"dataset": "sha"})
            with self.assertRaises(ValueError):
                validate_checkpoint_protocol(model, "b", {"dataset": "sha"})

    def test_compare_requires_same_protocol_and_completed_reports(self):
        baseline = {"status": "completed", "config_fingerprint": "fixture", "revisions": {}, "schema": {},
                    "validation_episodes": [1], "global_indices": [2], "chunk_size": 4, "flow_steps": 10,
                    "noise_seed": 123, "precision": "float32", "metrics": {"per_axis": {"joint": {"mae": 2}}},
                    "latency": {}}
        trained = {**baseline, "metrics": {"per_axis": {"joint": {"mae": 1}}}}
        result = compare_reports(baseline, trained)
        self.assertEqual(result["per_axis_delta_after_minus_before"]["joint"]["mae"], -1)
        for change in ({"global_indices": [3]}, {"status": "failed"}, {"noise_seed": 999}):
            with self.assertRaises(ValueError):
                compare_reports(baseline, {**trained, **change})

    def test_json_rejects_nonfinite_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                write_json(Path(temporary) / "report.json", {"loss": float('nan')})

    def test_manifest_rejects_config_changes_and_overlapping_splits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg = ExperimentConfig(root / "cache", root, DatasetConfig("fixture/data"), PolicyConfig("fixture/model"))
            payload = {"manifest_version": 1, "config": cfg.to_dict(), "config_fingerprint": cfg.fingerprint, "dataset_info": schema(), "schema": validate_schema(schema()),
                       "dataset_path": temporary, "model_path": temporary, "backbone_path": temporary,
                       "split": {"train": [0], "validation": [1]}}
            write_json(root / "meta" / "info.json", schema())
            write_json(root / "prepared.json", payload)
            self.assertEqual(load_manifest(cfg)["split"]["train"], [0])
            with self.assertRaises(ValueError):
                load_manifest(replace(cfg, training=replace(cfg.training, batch_size=4)))
            payload["split"]["validation"] = [0]
            write_json(root / "prepared.json", payload)
            with self.assertRaises(ValueError):
                load_manifest(cfg)

class MetricTests(unittest.TestCase):
    def test_only_training_values_determine_stats(self):
        result = feature_stats([[1, 2], [3, 4]])
        self.assertEqual(result["mean"], [2, 3])
        self.assertEqual(result["std"], [1, 1])
        self.assertEqual(result["count"], [2])

    def test_stats_rejects_nonfinite_and_empty(self):
        for values in ([], [[float('nan')]], [1, 2, 3]):
            with self.assertRaises(ValueError):
                feature_stats(values)

    def test_padding_never_contributes_to_error(self):
        metrics = ActionMetrics(2)
        metrics.update([[[1, 2], [999, 999]]], [[[0, 0], [0, 0]]], [[False, True]])
        result = metrics.summary(["joint", "gripper"])
        self.assertEqual(result["valid_action_steps"], 1)
        self.assertEqual(result["per_axis"]["joint"]["mae"], 1)
        self.assertEqual(result["per_axis"]["gripper"]["rmse"], 2)

    def test_batch_sizes_are_weighted_by_valid_steps(self):
        metrics = ActionMetrics(1)
        metrics.update([[[2], [0]]], [[[0], [0]]], [[False, True]])
        metrics.update([[[4], [6]]], [[[0], [0]]], [[False, False]])
        self.assertEqual(metrics.summary(["joint"])["per_axis"]["joint"]["mae"], 4)

    def test_wrong_shapes_and_nonfinite_fail(self):
        metrics = ActionMetrics(1)
        for pred, target, mask in (([[1]], [[0]], [False]), ([[[1]]], [[[0]]], [[False, True]]), ([[[float('nan')]]], [[[0]]], [[False]])):
            with self.assertRaises(ValueError):
                metrics.update(pred, target, mask)

    def test_fully_padded_data_fails(self):
        metrics = ActionMetrics(1)
        metrics.update([[[1]]], [[[0]]], [[True]])
        with self.assertRaises(ValueError):
            metrics.summary(["joint"])

    def test_latency_statistics(self):
        self.assertEqual(latency_summary([1, 2, 3])["p50_ms"], 2)
        self.assertEqual(latency_summary([1, 2, 3])["max_ms"], 3)
        with self.assertRaises(ValueError):
            latency_summary([-1])

if __name__ == "__main__":
    unittest.main()
