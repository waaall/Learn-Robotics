"""执行物理算例并保存版本、配置、模型摘要与数值验收报告。"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

import mujoco
import numpy as np

from .common import DEFAULT_CONFIG, load_config, sha256
from .experiments import run_case


def run_suite(config_path: Path) -> dict:
    config_path = config_path.resolve()
    config = load_config(config_path)
    expected = config["runtime"]["expected_version"]
    if mujoco.__version__ != expected or mujoco.mj_versionString() != expected:
        raise RuntimeError(f"Python 包和运行库必须同时为 {expected}")
    manifest_path = config_path.parent / config["runtime"]["source_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkout = (manifest_path.parent / manifest["checkout"]).resolve()
    # 只读取本地 Git 元数据，不联网，也不把个人安装路径写进报告。
    source_state = {"available": False}
    if (checkout / ".git").exists():
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True))
        source_state = {"available": True, "commit": commit, "dirty": dirty}
        if commit != manifest["commit"] or dirty:
            raise RuntimeError("本地参考源码偏离固定提交或存在修改，请先核对来源")
    results = [run_case(name, case, config_path.parent) for name, case in config["cases"].items()]
    if not results:
        raise ValueError("至少需要一个实验算例")
    return {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": platform.python_version(), "system": platform.system(),
                    "machine": platform.machine(), "numpy": np.__version__,
                    "python_package": mujoco.__version__, "native_library": mujoco.mj_versionString()},
        "source": manifest, "source_checkout": source_state,
        "config_sha256": sha256(config_path), "config": config,
        "results": results, "passed": all(item["passed"] for item in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="核对 MuJoCo 关节动力学与接触计算")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="报告路径；省略时只输出 JSON")
    args = parser.parse_args()
    report = run_suite(args.config)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        for result in report["results"]:
            print(f"{result['name']}: {'PASS' if result['passed'] else 'FAIL'}")
        print(f"报告：{args.output.resolve()}")
    else:
        print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
