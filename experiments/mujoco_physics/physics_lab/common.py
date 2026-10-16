"""加载独立实验配置，并封装模型初始化与一致时刻的动力学采样。"""

from collections.abc import Iterator
from pathlib import Path
import hashlib
import math
import tomllib

import mujoco
import numpy as np


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "default.toml"


def load_config(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model(case: dict, base: Path) -> tuple[mujoco.MjModel, mujoco.MjData]:
    model = mujoco.MjModel.from_xml_path(str((base / case["model"]).resolve()))
    if "timestep" in case:
        model.opt.timestep = float(case["timestep"])
    if not math.isfinite(model.opt.timestep) or model.opt.timestep <= 0:
        raise ValueError("timestep 必须是有限正数")
    if model.opt.integrator == mujoco.mjtIntegrator.mjINT_DISCRETE:
        raise ValueError("本实验的连续时间方程检查尚未适配 discrete 积分器")
    data = mujoco.MjData(model)
    for field in ("qpos", "qvel", "ctrl"):
        if field in case:
            values = np.asarray(case[field], dtype=float)
            target = getattr(data, field)
            if values.shape != target.shape or not np.all(np.isfinite(values)):
                raise ValueError(f"{field} 需要 {target.shape} 维有限数值，收到 {values.shape}")
            target[:] = values
    mujoco.mj_forward(model, data)
    return model, data


def mass_matrix(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    # 3.16.0 的第二个参数是 mjData；旧教程传入 qM 的签名不能直接复用。
    matrix = np.empty((model.nv, model.nv))
    mujoco.mj_fullM(model, data, matrix)
    return matrix


def residual(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    error = mass_matrix(model, data) @ data.qacc - data.qfrc_smooth - data.qfrc_constraint
    return float(np.linalg.norm(error, ord=np.inf))


def rollout(model: mujoco.MjModel, data: mujoco.MjData, duration: float) -> Iterator[None]:
    ratio = duration / model.opt.timestep
    if not math.isfinite(ratio) or ratio <= 0 or not math.isclose(ratio, round(ratio)):
        raise ValueError("duration 必须是 timestep 的正整数倍")
    yield None
    for _ in range(round(ratio)):
        mujoco.mj_step(model, data)
        # 步进已更新 qpos/qvel；重新计算派生量，避免把上一步接触力配到新位姿。
        mujoco.mj_forward(model, data)
        yield None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
