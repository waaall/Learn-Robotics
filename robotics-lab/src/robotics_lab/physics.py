"""可独立运行的物理实验；与查看器和网页生命周期解耦。"""

from datetime import datetime, timezone
import hashlib
import math
import platform
from pathlib import Path

import mujoco
import numpy as np

from . import MUJOCO_VERSION
from .catalog import Experiment


def load_model(experiment: Experiment):
    if mujoco.__version__ != MUJOCO_VERSION or mujoco.mj_versionString() != MUJOCO_VERSION:
        raise RuntimeError(f"物理实验要求 MuJoCo {MUJOCO_VERSION}")
    spec = mujoco.MjSpec.from_file(str(experiment.model_path))
    if experiment.adapter == "panda":
        # MjSpec 中显式解析 include 内的网格资源，保持上游模型文件原样。
        for mesh in spec.meshes:
            mesh.file = str(experiment.model_path.parent / "panda" / "assets" / Path(mesh.file).name)
        hand = spec.body("hand")
        hand.add_site(name="tool", pos=[0, 0, 0.1034], size=[0.009]*3, rgba=[0.15, 0.4, 0.85, 1])
        for axis, color in enumerate(([0.85, 0.2, 0.2, 1], [0.2, 0.7, 0.3, 1], [0.2, 0.4, 0.9, 1])):
            start, end = [0, 0, 0.1034], [0, 0, 0.1034]
            end[axis] += 0.065
            hand.add_site(name=f"tool_axis_{axis}", type=mujoco.mjtGeom.mjGEOM_CAPSULE,
                          fromto=start + end, size=[0.002]*3, rgba=color)
    spec.add_key(name="experiment_initial", time=0, qpos=list(experiment.qpos), ctrl=list(experiment.initial_ctrl))
    model = spec.compile()
    data = mujoco.MjData(model)
    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "experiment_initial")
    mujoco.mj_resetDataKeyframe(model, data, key)
    mujoco.mj_forward(model, data)
    return model, data


def simulate(experiment: Experiment, duration: float | None = None, settings: dict | None = None) -> dict:
    model, data = load_model(experiment)
    duration = experiment.duration if duration is None else duration
    if experiment.adapter == "panda":
        from .panda import simulate_panda
        result = simulate_panda(experiment, model, data, duration, settings)
        result.update(experiment=experiment.public(), duration=duration,
                      created_at=datetime.now(timezone.utc).isoformat(),
                      runtime={"mujoco": mujoco.__version__, "system": platform.system(), "timestep": model.opt.timestep},
                      initial_qpos=list(experiment.qpos), final_qpos=data.qpos.tolist())
        return result
    ratio = duration / model.opt.timestep
    if not math.isfinite(duration) or not 0 < duration <= 10 or not math.isclose(ratio, round(ratio)):
        raise ValueError("时长需在 (0, 10] 秒内，且为仿真步长的整数倍")
    steps = round(ratio)
    stride = max(1, math.ceil(steps / 400))
    samples, energies, supports = [], [], []
    min_gap = float("inf")
    for step in range(steps + 1):
        if step:
            mujoco.mj_step(model, data)
        # 将派生量刷新到当前状态，避免混合前后时刻的数据；不是性能基准。
        mujoco.mj_forward(model, data)
        mujoco.mj_energyPos(model, data)
        mujoco.mj_energyVel(model, data)
        energies.append(float(sum(data.energy)))
        if experiment.id == "drop-ball":
            min_gap = min(min_gap, float(data.qpos[2] - 0.1))
            support = 0.0
            for index in range(data.ncon):
                contact = data.contact[index]
                wrench = np.empty(6)
                mujoco.mj_contactForce(model, data, index, wrench)
                force = contact.frame.reshape(3, 3).T @ wrench[:3]
                ball = model.geom("ball_geom").id
                support += float(force[2]) * (1 if contact.geom2 == ball else -1)
            if data.time >= duration - min(0.25, duration / 4):
                supports.append(support)
        if step % stride == 0 or step == steps:
            samples.append({"time": float(data.time), "value": float(data.qpos[experiment.observable_index])})
    metrics = {"steps": steps, "final_time": float(data.time), "final_speed": float(np.linalg.norm(data.qvel))}
    if experiment.id == "pendulum":
        metrics["max_energy_drift_J"] = max(abs(value - energies[0]) for value in energies)
    if supports:
        metrics.update(mean_support_N=float(np.mean(supports)), max_penetration_m=max(0, -min_gap))
    return {
        "experiment": experiment.public(), "duration": duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {"mujoco": mujoco.__version__, "system": platform.system(), "timestep": model.opt.timestep},
        "model_sha256": hashlib.sha256(experiment.model_path.read_bytes()).hexdigest(),
        "initial_qpos": list(experiment.qpos), "final_qpos": data.qpos.tolist(),
        "metrics": metrics, "samples": samples,
    }
