"""独立训练测试：配置、官方循环适配和状态恢复，不加载推理项目。"""

from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from smolvla_common.config import load_config, validate_config
from smolvla_common.protocol import read_json, validate_checkpoint_protocol, write_json
from smolvla_training.__main__ import main
from smolvla_training.training import trainer_arguments
CONFIG = Path(__file__).parent / "configs/smolvla-so100.toml"


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

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(CONFIG)

    def test_full_finetuning_default(self):
        self.assertEqual(self.cfg.training.steps, 20000)
        self.assertEqual(self.cfg.training.batch_size, 8)
        self.assertTrue(self.cfg.policy.train_expert_only)
        self.assertFalse(self.cfg.policy.use_amp)

    def test_paths_resolve_from_config_not_working_directory(self):
        self.assertEqual(self.cfg.run_dir, CONFIG.parent.parent / "outputs" / "smolvla" / "so100-pickplace")
        self.assertTrue(self.cfg.cache_dir.is_absolute())

    def test_invalid_steps_batches_and_workers(self):
        for key, value in (("steps", 0), ("batch_size", -1), ("num_workers", -1), ("steps", True), ("learning_rate", float('nan'))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(replace(self.cfg, training=replace(self.cfg.training, **{key: value})))

    def test_warmup_must_be_shorter_than_training(self):
        with self.assertRaises(ValueError):
            validate_config(replace(self.cfg, training=replace(self.cfg.training, steps=100)))

    def test_invalid_policy(self):
        for key, value in (("chunk_size", 0), ("num_steps", -1), ("train_expert_only", "true")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(replace(self.cfg, policy=replace(self.cfg.policy, **{key: value})))

    def test_invalid_dataset(self):
        for key, value in (("validation_fraction", 0), ("validation_fraction", 1), ("repo_id", "bad"), ("video_backend", "unknown")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(replace(self.cfg, dataset=replace(self.cfg.dataset, **{key: value})))


    def test_fingerprint_changes_with_settings(self):
        changed = replace(self.cfg, training=replace(self.cfg.training, batch_size=4))
        self.assertNotEqual(changed.fingerprint, self.cfg.fingerprint)

    def test_plan_is_dependency_free(self):
        code = "import sys; from smolvla_training.__main__ import main; main(['--config',sys.argv[1],'plan']); assert 'torch' not in sys.modules; assert 'lerobot' not in sys.modules; assert 'huggingface_hub' not in sys.modules"
        env = {**os.environ, "PYTHONPATH": str(CONFIG.parents[3] / "packages/smolvla_common/src")}
        result = subprocess.run([sys.executable, "-c", code, str(CONFIG)], cwd=CONFIG.parent.parent,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["training"]["steps"], 20000)

    def test_cli_plan(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main(["--config", str(CONFIG), "plan"])
        self.assertEqual(json.loads(output.getvalue())["dataset"]["repo_id"], self.cfg.dataset.repo_id)

class TrainingAdapterTests(unittest.TestCase):
    def exercise(self, *, fail=False):
        import smolvla_training.training as training
        with tempfile.TemporaryDirectory() as temporary:
            cfg = replace(load_config(CONFIG), run_dir=Path(temporary) / "run")
            manifest = {"dataset_path": "dataset", "backbone_path": "backbone",
                        "revisions": {"dataset": "sha"}, "split": {"train": [0], "validation": [1]}}
            policy_cfg = SimpleNamespace()
            trainer = ModuleType("lerobot.scripts.lerobot_train")
            calls = []
            def original_processors(*args, **kwargs):
                overrides = kwargs["preprocessor_overrides"]
                self.assertEqual(overrides["tokenizer_processor"]["tokenizer_name"], "backbone")
                self.assertEqual(overrides["normalizer_processor"], {"stats": "train-only"})
                return "processors"
            def original_policy(**kwargs):
                raise AssertionError("没有使用严格模型加载适配")
            def original_datasets(active):
                raise AssertionError("没有使用冻结的数据划分适配")
            def original_pointer(path):
                raise AssertionError("不应调用 symlink 更新")
            trainer.make_pre_post_processors = original_processors
            trainer.make_policy = original_policy
            trainer.make_train_eval_datasets = original_datasets
            trainer.update_last_checkpoint = original_pointer
            def loop(active):
                self.assertEqual(active.steps, 20000)
                self.assertEqual(active.env_eval_freq, 0)
                self.assertEqual(trainer.make_train_eval_datasets(active), ("train-data", "validation-data"))
                self.assertEqual(trainer.make_policy(cfg=active.policy, ds_meta=None, rename_map={}), "strict-policy")
                trainer.make_pre_post_processors(preprocessor_overrides={"normalizer_processor": {"stats": "train-only"}})
                if fail:
                    raise RuntimeError("模拟训练失败")
                model = checkpoint(active.output_dir, active.steps)
                trainer.update_last_checkpoint(model.parent)
            trainer.train = loop
            scripts = ModuleType("lerobot.scripts"); scripts.lerobot_train = trainer
            defaults = ModuleType("lerobot.configs.default"); defaults.DatasetConfig = SimpleNamespace
            configs = ModuleType("lerobot.configs.train"); configs.TrainPipelineConfig = SimpleNamespace
            modules = {"lerobot": ModuleType("lerobot"), "lerobot.configs": ModuleType("lerobot.configs"),
                       "lerobot.configs.default": defaults, "lerobot.configs.train": configs,
                       "lerobot.scripts": scripts, "lerobot.scripts.lerobot_train": trainer}
            def dataset_opener(cfg, manifest, episodes, policy):
                calls.append(episodes)
                return "train-data" if episodes == [0] else "validation-data"
            with patch.dict(sys.modules, modules), patch.object(training, "configure_cache"), \
                    patch.object(training, "require_runtime", return_value={"gpu": "fixture"}), \
                    patch.object(training, "load_manifest", return_value=manifest), \
                    patch.object(training, "make_policy_config", return_value=policy_cfg), \
                    patch.object(training, "load_policy", return_value="strict-policy"), \
                    patch.object(training, "open_dataset", side_effect=dataset_opener):
                if fail:
                    with self.assertRaises(RuntimeError):
                        training.train(cfg)
                else:
                    model = training.train(cfg)
                    validate_checkpoint_protocol(model, cfg.fingerprint, manifest["revisions"])
            self.assertEqual(calls, [[0], [1]])
            self.assertIs(trainer.make_pre_post_processors, original_processors)
            self.assertIs(trainer.make_policy, original_policy)
            self.assertIs(trainer.make_train_eval_datasets, original_datasets)
            self.assertIs(trainer.update_last_checkpoint, original_pointer)
            result = read_json(cfg.run_dir / "training-result.json")
            self.assertEqual(result["status"], "failed" if fail else "completed")

    def test_official_loop_adapters_checkpoint_and_restoration(self):
        self.exercise()

    def test_failed_loop_records_failure_and_restores_adapters(self):
        self.exercise(fail=True)

class TrainingArgumentTests(unittest.TestCase):
    def test_official_argument_context_restores_on_error(self):
        before = sys.argv
        with self.assertRaises(RuntimeError):
            with trainer_arguments(["--config_path=checkpoint.json"]):
                self.assertEqual(sys.argv, ["lerobot-train", "--config_path=checkpoint.json"])
                raise RuntimeError("fixture")
        self.assertIs(sys.argv, before)

if __name__ == "__main__":
    unittest.main()
