"""用可搬运文件和 CPU 替身验证离线推理，测试不依赖训练目录或真实模型下载。"""

from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import numpy as np

from smolvla_common.config import DatasetConfig, ExperimentConfig, InferenceConfig, PolicyConfig
from smolvla_common.prepared import read_prepared
from smolvla_common.protocol import compare_reports, read_json, validate_checkpoint, validate_schema, write_json
from smolvla_inference.config import InferenceJob, load_config
from smolvla_inference import engine
from smolvla_inference.__main__ import main

CONFIG = Path(__file__).parent / "configs/smolvla-offline.toml"


def artifacts(root):
    """故意保留不存在的历史路径；新机器通过显式资产覆盖定位完整副本。"""
    cfg = ExperimentConfig(root / "old-cache", root / "old-run", DatasetConfig("fixture/data"),
                           PolicyConfig("fixture/model", chunk_size=3, num_steps=2))
    info = {"codebase_version": "v3.0", "fps": 10, "features": {
        "observation.state": {"shape": [2], "dtype": "float32", "names": ["joint", "gripper"]},
        "action": {"shape": [2], "dtype": "float32", "names": ["joint", "gripper"]},
        "observation.images.top": {"shape": [8, 8, 3], "dtype": "video"},
    }}
    dataset, backbone, base = (root / name for name in ("copied-data", "copied-backbone", "copied-base"))
    for folder in (dataset, backbone, base):
        folder.mkdir()
    write_json(dataset / "meta/info.json", info)
    manifest = {"manifest_version": 1, "config": cfg.to_dict(), "config_fingerprint": cfg.fingerprint,
                "dataset_info": info, "schema": validate_schema(info), "split": {"train": [0], "validation": [1, 2]},
                "dataset_path": str(root / "missing-data"), "backbone_path": str(root / "missing-backbone"),
                "model_path": str(root / "missing-base"), "training_stats": {}, "limitations": ["测试替身，不是真实模型"],
                "revisions": {"dataset": "a" * 40, "model": "b" * 40, "backbone": "c" * 40}}
    prepared = root / "inputs/prepared.json"
    write_json(prepared, manifest)
    model = root / "copied-renamed-policy"
    model.mkdir()
    write_json(model / "config.json", {})
    (model / "model.safetensors").write_bytes(b"fixture")
    for name, registry in (("policy_preprocessor.json", "normalizer_processor"),
                           ("policy_postprocessor.json", "unnormalizer_processor")):
        write_json(model / name, {"steps": [{"registry_name": registry, "state_file": "stats.safetensors"}]})
    (model / "stats.safetensors").write_bytes(b"fixture")
    write_json(model / "experiment.json", {"config_fingerprint": cfg.fingerprint, "revisions": manifest["revisions"]})
    job = InferenceJob(prepared, root / "new-cache", root / "new-results", model,
                       dataset, base, backbone, InferenceConfig(max_samples=4, warmup_runs=2, noise_seed=7))
    return job, manifest


class ConfigurationTests(unittest.TestCase):
    def test_invalid_inference_limits_and_types(self):
        from smolvla_common.config import validate_inference
        for key, value in (("max_samples", 0), ("max_samples", True), ("max_samples", 1.5),
                           ("warmup_runs", -1), ("noise_seed", False)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_inference(replace(InferenceConfig(), **{key: value}))

    def test_paths_and_parameters_are_inference_only(self):
        job = load_config(CONFIG)
        self.assertEqual(job.output_dir, CONFIG.parent.parent / "outputs/smolvla/so100-pickplace")
        self.assertIsNone(job.checkpoint)
        self.assertNotIn("training", job.to_dict())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_text(CONFIG.read_text() + "\n[training]\nsteps = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "推理配置"):
                load_config(path)

    def test_missing_explicit_checkpoint_fails_without_scanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            job, _ = artifacts(Path(temporary))
            with patch.object(Path, "glob", side_effect=AssertionError("不应扫描训练目录")):
                with self.assertRaisesRegex(ValueError, "必须显式"):
                    engine.infer(replace(job, checkpoint=None))
            self.assertEqual(read_json(job.output_dir / "checkpoint/report.json")["status"], "failed")

    def test_invalid_input_clears_previous_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            job, _ = artifacts(Path(temporary))
            write_json(job.output_dir / "baseline/report.json", {"status": "completed", "old_metric": 1})
            with self.assertRaises(FileNotFoundError):
                engine.infer(replace(job, prepared_manifest=Path(temporary) / "absent.json"), baseline=True)
            failed = read_json(job.output_dir / "baseline/report.json")
            self.assertEqual(failed["status"], "failed")
            self.assertNotIn("old_metric", failed)

    def test_compare_cli_needs_explicit_reports_but_no_models_or_prepared_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "offline.toml"
            config.write_text('''[paths]
base_dir = "."
prepared_manifest = "missing.json"
cache_dir = "cache"
output_dir = "results"
[assets]
dataset_dir = ""
base_model_dir = ""
backbone_dir = ""
[model]
checkpoint = ""
[inference]
max_samples = 1
''', encoding="utf-8")
            report = {"status": "completed", "config_fingerprint": "fixture", "revisions": {}, "schema": {},
                      "validation_episodes": [1], "global_indices": [2], "chunk_size": 3, "flow_steps": 2,
                      "noise_seed": 123, "precision": "float32", "metrics": {"per_axis": {"joint": {"mae": 2}}},
                      "latency": {}}
            baseline, trained = root / "before.json", root / "after.json"
            write_json(baseline, report)
            write_json(trained, {**report, "metrics": {"per_axis": {"joint": {"mae": 1}}}})
            with redirect_stdout(io.StringIO()), patch.object(engine, "infer", side_effect=AssertionError("只比较文件")):
                main(["--config", str(config), "compare", "--baseline-report", str(baseline),
                      "--trained-report", str(trained)])
            result = read_json(root / "results/comparison.json")
            self.assertEqual(result["per_axis_delta_after_minus_before"]["joint"]["mae"], -1)
            self.assertEqual(result["report_sources"]["trained"], str(trained.resolve()))
            self.assertFalse((root / "missing.json").exists())


class PortableArtifactsTests(unittest.TestCase):
    def test_assets_relocate_without_changing_frozen_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            job, original = artifacts(Path(temporary))
            overrides = {**job.asset_overrides, "model_path": None}
            relocated = read_prepared(job.prepared_manifest, asset_overrides=overrides, require_base=False)
            self.assertEqual(relocated["config_fingerprint"], original["config_fingerprint"])
            self.assertEqual(relocated["config"], original["config"])
            self.assertEqual(relocated["dataset_path"], str(job.dataset_dir))
            self.assertFalse(Path(relocated["model_path"]).exists())
            self.assertEqual(validate_checkpoint(job.checkpoint), job.checkpoint)
            self.assertFalse((job.checkpoint / "train_config.json").exists())
            with self.assertRaises(ValueError):
                validate_checkpoint(job.checkpoint, resume=True)
            with self.assertRaises(ValueError):
                read_prepared(job.prepared_manifest, asset_overrides=overrides, require_base=True)

    def test_metadata_tampering_split_and_old_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            job, original = artifacts(Path(temporary))
            mutations = [dict(original, manifest_version=0), dict(original, manifest_version=True),
                         dict(original, config_fingerprint="wrong"),
                         dict(original, split={"train": [0, 0], "validation": [1]}),
                         dict(original, split={"train": [0], "validation": [0]}),
                         dict(original, split={"train": [True], "validation": [1]})]
            for payload in mutations:
                with self.subTest(payload=payload):
                    write_json(job.prepared_manifest, payload)
                    with self.assertRaises(ValueError):
                        read_prepared(job.prepared_manifest, asset_overrides=job.asset_overrides)
            write_json(job.prepared_manifest, original)
            write_json(job.dataset_dir / "meta/info.json", {**original["dataset_info"], "fps": 99})
            with self.assertRaisesRegex(ValueError, "metadata"):
                read_prepared(job.prepared_manifest, asset_overrides=job.asset_overrides)

    def test_complete_cpu_adapter_flow_and_comparison_from_copied_artifacts(self):
        import torch
        calls, processor_calls = [], []
        outer = self

        class Policy:
            config = SimpleNamespace(use_amp=False)

            def reset(self):
                calls.append("reset")

            def predict_action_chunk(self, batch, noise):
                outer.assertNotIn("action", batch)
                outer.assertNotIn("action_is_pad", batch)
                outer.assertFalse(torch.is_grad_enabled())
                calls.append("predict")
                return noise[:, :, :2] + batch["observation.state"].unsqueeze(1)

        class Dataset:
            hf_dataset = {"episode_index": [1, 1, 2, 2]}

            def __getitem__(self, index):
                return {"observation.state": torch.tensor([1., 2.]), "task": "pick",
                        "action": torch.tensor([[1., 2.], [1., 2.], [999., 999.]]),
                        "action_is_pad": torch.tensor([False, False, True]),
                        "index": torch.tensor(100 + index), "episode_index": torch.tensor(1 + index // 2)}

        def processors(cfg, **kwargs):
            processor_calls.append(kwargs)
            return (lambda batch: batch), (lambda action: action)

        factory = ModuleType("lerobot.policies.factory")
        factory.make_pre_post_processors = processors
        modules = {"lerobot": ModuleType("lerobot"), "lerobot.policies": ModuleType("lerobot.policies"),
                   "lerobot.policies.factory": factory}
        real_noise = engine.sample_noise
        with tempfile.TemporaryDirectory() as temporary:
            job, manifest = artifacts(Path(temporary))
            def policy_config(cfg, active, checkpoint=None):
                self.assertEqual(cfg.cache_dir, job.cache_dir)
                self.assertEqual(cfg.run_dir, job.output_dir)
                return SimpleNamespace(chunk_size=3, max_action_dim=4, action_feature=SimpleNamespace(shape=(2,)),
                                       num_steps=2, use_amp=False, pretrained_path=checkpoint or active["model_path"])
            # 替换仅限框架／CUDA边界，文件校验、预测适配、掩码与报告均走真实实现。
            with ExitStack() as stack:
                stack.enter_context(patch.dict(sys.modules, modules))
                stack.enter_context(patch.object(engine, "configure_cache"))
                stack.enter_context(patch.object(engine, "require_runtime", return_value={"gpu": "CPU 测试替身"}))
                stack.enter_context(patch.object(engine, "make_policy_config", side_effect=policy_config))
                stack.enter_context(patch.object(engine, "load_policy", return_value=Policy()))
                opener = stack.enter_context(patch.object(engine, "open_dataset", return_value=Dataset()))
                stack.enter_context(patch.object(engine, "sample_noise", side_effect=lambda c, s, i, d: real_noise(c, s, i, "cpu")))
                for name in ("synchronize", "reset_peak_memory_stats", "max_memory_allocated", "max_memory_reserved"):
                    stack.enter_context(patch.object(torch.cuda, name, return_value=0))
                baseline = read_json(engine.infer(job, baseline=True))
                trained = read_json(engine.infer(replace(job, base_model_dir=None)))
            self.assertEqual(baseline["config_fingerprint"], manifest["config_fingerprint"])
            self.assertEqual(trained["config_fingerprint"], manifest["config_fingerprint"])
            self.assertEqual(opener.call_args.args[2], [1, 2])
            self.assertEqual(baseline["global_indices"], [100, 101, 102, 103])
            self.assertEqual(trained["metrics"]["valid_action_steps"], 8)
            self.assertEqual(calls.count("predict"), 12)  # 每侧四个样本，另有两轮预热。
            self.assertIn("dataset_stats", processor_calls[0])
            self.assertNotIn("dataset_stats", processor_calls[1])
            self.assertEqual(processor_calls[1]["pretrained_path"], str(job.checkpoint.resolve()))
            self.assertFalse(trained["hardware_connected"])
            comparison = compare_reports(baseline, trained)
            self.assertEqual(comparison["per_axis_delta_after_minus_before"]["joint"]["mae"], 0)
            with np.load(job.output_dir / "checkpoint/actions.npz") as saved:
                self.assertEqual(saved["predicted"].shape, (4, 3, 2))
                self.assertTrue(saved["is_pad"][:, -1].all())
            self.assertTrue((job.output_dir / "checkpoint/samples.csv").is_file())
            self.assertEqual(read_json(job.prepared_manifest), manifest)
            self.assertFalse(Path(manifest["config"]["run_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
