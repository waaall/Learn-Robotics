"""验证三个实验的环境和导入边界；不安装依赖、不联网、不打开硬件。"""

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


class ProjectBoundaryTests(unittest.TestCase):
    def test_separate_locks_and_local_common_dependency(self):
        for name in ("lerobot", "training", "inference"):
            folder = REPO / "experiments" / name
            for file in ("pyproject.toml", "uv.lock", "setup.ps1", "run.ps1", "check_environment.py"):
                self.assertTrue((folder / file).is_file(), folder / file)
            pyproject = tomllib.loads((folder / "pyproject.toml").read_text())
            self.assertNotIn("workspace", pyproject["tool"]["uv"])
            if name != "lerobot":
                self.assertEqual(pyproject["tool"]["uv"]["sources"]["smolvla-common"]["path"], "../../packages/smolvla_common")
                lock = tomllib.loads((folder / "uv.lock").read_text())
                packages = {package["name"] for package in lock["package"]}
                self.assertTrue({"smolvla-common", "lerobot", "torch", "transformers"} <= packages)
                self.assertFalse({"scservo-sdk", "rerun-sdk", "dynamixel-sdk"} & packages)
                if name == "training":
                    self.assertNotIn("feetech-servo-sdk", packages)
                if name == "inference":
                    self.assertNotIn("wandb", packages)
                    # 默认离线环境无舵机依赖；显式 live extra 才安装只读适配所需 SDK。
                    self.assertEqual(pyproject["project"]["optional-dependencies"]["live"],
                                     ["lerobot[feetech]==0.6.1"])
                    project_package = next(p for p in lock["package"] if p["name"] == "robot-policy-inference")
                    defaults = {p["name"] for p in project_package["dependencies"]}
                    self.assertFalse({"feetech-servo-sdk", "pyserial"} & defaults)

    def test_production_code_does_not_import_peer_projects_or_hardware(self):
        targets = [(REPO / "experiments/training/smolvla_training", {"smolvla_inference", "remote_lab"}),
                   (REPO / "experiments/inference/smolvla_inference", {"smolvla_training", "remote_lab"}),
                   (REPO / "packages/smolvla_common/src/smolvla_common", {"smolvla_training", "smolvla_inference", "remote_lab"})]
        for directory, forbidden in targets:
            for file in directory.glob("*.py"):
                tree = ast.parse(file.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    imported = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                                else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                    for module in imported:
                        self.assertNotIn(module.split(".")[0], forbidden, file)
                        self.assertFalse(module.startswith(("lerobot.robots", "lerobot.teleoperators", "lerobot.cameras", "scservo_sdk")), file)
        source = (REPO / "experiments/inference/smolvla_inference/engine.py").read_text()
        self.assertNotIn("latest_checkpoint", source)
        self.assertNotIn("smolvla_training", source)
        self.assertNotIn("checkpoints/", source)

    def test_each_project_plan_works_without_the_other_experiments(self):
        for name, module, config in (("training", "smolvla_training", "smolvla-so100.toml"),
                                     ("inference", "smolvla_inference", "smolvla-offline.toml")):
            with self.subTest(project=name), tempfile.TemporaryDirectory() as temporary:
                copied = Path(temporary) / "project"
                shutil.copytree(REPO / "experiments" / name, copied,
                                ignore=shutil.ignore_patterns(".venv", "outputs", "__pycache__"))
                common = Path(temporary) / "common"
                shutil.copytree(REPO / "packages/smolvla_common/src", common, ignore=shutil.ignore_patterns("__pycache__"))
                code = (f"import sys; from {module}.__main__ import main; "
                        "main(['--config',sys.argv[1],'plan']); "
                        "assert not {'torch','lerobot','huggingface_hub','numpy'} & sys.modules.keys()")
                env = {**os.environ, "PYTHONPATH": str(common)}
                result = subprocess.run([sys.executable, "-c", code, str(copied / "configs" / config)],
                                        cwd=copied, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(result.stdout)
                self.assertIn("training" if name == "training" else "prepared_manifest", plan)
                rejected = "infer" if name == "training" else "train"
                result = subprocess.run([sys.executable, "-m", module, "--config", str(copied / "configs" / config), rejected],
                                        cwd=copied, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_failed_environment_preflight_replaces_old_success(self):
        from smolvla_common import environment
        from smolvla_common.protocol import read_json, write_json
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "environment.json"
            write_json(output, {"status": "completed", "old_success": True})
            with patch.object(environment, "require_runtime", side_effect=RuntimeError("缺少 CUDA")):
                with self.assertRaises(RuntimeError):
                    environment.check(output)
            self.assertEqual(read_json(output)["status"], "failed")
            self.assertNotIn("old_success", read_json(output))


if __name__ == "__main__":
    unittest.main()
