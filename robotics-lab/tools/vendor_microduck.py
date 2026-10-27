"""从已下载的固定上游导入模型，将官方 ONNX MLP 导出为纯 NumPy 权重。

仅资源维护时需要 onnx / onnxruntime；课程运行只依赖 NumPy 和 MuJoCo。
用法：python tools/vendor_microduck.py --rl ../.cache/microduck_rl --bam ../.cache/bam --policies ../.cache
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort

RL_REV = "b02fdea4902c2b93b7d34a83a6f05da4ececb7d3"
BAM_REV = "62bd8ce12154340be97e06f7f41a0ca8f116d967"
POLICY_REV = "665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448"
DEST = Path(__file__).resolve().parents[1] / "src/robotics_lab/assets/models/microduck"


def revision(path):
    return subprocess.check_output(["git", "-c", f"safe.directory={path.resolve().as_posix()}",
                                    "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rl", "bam", "policies"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if revision(args.rl) != RL_REV or revision(args.bam) != BAM_REV:
        raise ValueError("上游版本与课程固定版本不符")
    DEST.mkdir(parents=True, exist_ok=True)
    model_dir = args.rl / "src/mjlab_microduck/robot/microduck"
    shutil.copy2(model_dir / "robot_groundcontact.xml", DEST)
    shutil.copytree(model_dir / "assets", DEST / "assets", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.part"))
    for name in ("LICENSE", "LICENSE-MODELS.md"):
        shutil.copy2(args.rl / name, DEST / name)
    shutil.copy2(args.bam / "LICENSE", DEST / "LICENSE-BAM")
    shutil.copy2(args.bam / "bam/params/xl330/m6.json", DEST / "xl330_m6.json")
    shutil.copy2(args.policies / "microduck-manifest.json", DEST / "policy_manifest.json")
    policy_info = {}
    for name in ("velstand", "walking", "sitstand"):
        source = args.policies / (name + ".onnx")
        graph = onnx.load(str(source))
        expected = ["Sub", "Div", "Gemm", "Elu", "Gemm", "Elu", "Gemm", "Elu", "Gemm"]
        if [node.op_type for node in graph.graph.node] != expected:
            raise ValueError("策略网络结构变化，需要重新审查导出器")
        weights = {v.name: numpy_helper.to_array(v).copy() for v in graph.graph.initializer}
        np.savez_compressed(DEST / (name + ".npz"), **weights)
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(source), options, providers=["CPUExecutionProvider"])
        rng = np.random.default_rng(2710)
        observations = rng.normal(0, .25, (32, 61)).astype(np.float32)
        observations[:, 3:6] = [0, 0, -1]
        actions = np.stack([session.run(None, {session.get_inputs()[0].name: x[None]})[0][0]
                            for x in observations])
        np.savez_compressed(DEST / (name + "_reference.npz"), observations=observations, actions=actions)
        policy_info[name] = {"file": {"sitstand": "alpha_sitstand.onnx", "walking": "alpha_walking.onnx", "velstand": "velstand.onnx"}[name],
                             "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                             "metadata": {p.key: p.value for p in graph.metadata_props}}
    provenance = {"model_repo": "https://github.com/pollen-robotics/microduck_rl", "model_revision": RL_REV,
                  "bam_repo": "https://github.com/Rhoban/bam", "bam_revision": BAM_REV,
                  "policy_repo": "https://huggingface.co/pollen-robotics/microduck-policies",
                  "policy_revision": POLICY_REV, "policies": policy_info,
                  "adaptation": "官方网格与 MJCF 原样保留；课程场景、BAM NumPy 执行器与观测接口独立适配；ONNX 归一化与 MLP 权重导出为 NPZ。"}
    (DEST / "upstream.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(DEST)


if __name__ == "__main__":
    main()
