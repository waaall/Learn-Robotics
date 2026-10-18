"""固定 Unitree G1 课程资源；导出时需要 torch，课程运行仅需要 NumPy。"""

import hashlib
import json
from pathlib import Path
import urllib.request
import time
import xml.etree.ElementTree as ET

import numpy as np

REVISION = "276801e46c5d433564f24658bac64f254b7d2d4b"
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src/robotics_lab/assets/models/g1"
BASE = f"https://raw.githubusercontent.com/unitreerobotics/unitree_rl_gym/{REVISION}/"


def download(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        for attempt in range(4):
            try:
                with urllib.request.urlopen(BASE + source, timeout=60) as response:
                    content = response.read()
                target.write_bytes(content)
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)


def main():
    import torch
    files = {
        "resources/robots/g1_description/g1_12dof.xml": "g1_12dof.xml",
        "resources/robots/g1_description/README.md": "UPSTREAM_README.md",
        "LICENSE": "LICENSE",
        "deploy/deploy_mujoco/configs/g1.yaml": "source_config.yaml",
        "deploy/deploy_mujoco/deploy_mujoco.py": "source_deploy.py",
        "deploy/pre_train/g1/motion.pt": "motion.pt",
    }
    for source, name in files.items():
        download(source, DEST / name)
    for mesh in ET.parse(DEST / "g1_12dof.xml").getroot().findall("asset/mesh"):
        name = mesh.attrib["file"]
        download("resources/robots/g1_description/meshes/" + name, DEST / "meshes" / name)
    policy = torch.jit.load(str(DEST / "motion.pt"), map_location="cpu").eval()
    tensors = {key: value.detach().numpy() for key, value in policy.state_dict().items()}
    np.savez_compressed(DEST / "policy.npz", **tensors)
    rng = np.random.default_rng(20261018)
    observations = rng.normal(0, 0.3, (128, 47)).astype(np.float32)
    policy.reset_memory()
    with torch.no_grad():
        outputs = np.stack([policy(torch.from_numpy(x[None])).numpy()[0] for x in observations])
    np.savez_compressed(DEST / "policy_reference.npz", observations=observations, actions=outputs)
    hashes = {p.relative_to(DEST).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(DEST.rglob("*")) if p.is_file() and p.name != "upstream.json"}
    (DEST / "upstream.json").write_text(json.dumps({
        "repository": "https://github.com/unitreerobotics/unitree_rl_gym",
        "revision": REVISION, "model": "g1_12dof.xml", "license": "BSD-3-Clause",
        "policy": "motion.pt", "architecture": "LSTM(47,64) -> Linear(64,32) -> ELU -> Linear(32,12)",
        "adaptation": "原模型与策略原样保留；NumPy 权重和 128 步参考序列由 TorchScript 导出。课程场景及控制另行实现。",
        "sha256": hashes,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("G1 resources ready", {key: value.shape for key, value in tensors.items()})


if __name__ == "__main__":
    main()
