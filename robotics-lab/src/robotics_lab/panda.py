"""Panda 课程的运动学、位置伺服和接触任务。全部计算在 MuJoCo 中执行。"""

import hashlib
import math
from pathlib import Path

import mujoco
import numpy as np

HOME = np.array([0, 0, 0, -1.57079, 0, 1.57079, -0.7853])
KINEMATIC = {"structure", "fk", "jacobian", "ik"}


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    files = [path, *sorted((path.parent / "panda").rglob("*"))]
    for item in files:
        if item.is_file():
            digest.update(item.relative_to(path.parent).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


def solve_ik(model, seed, target, rotation=None, iterations=160):
    """关节限位内的阻尼最小二乘。位置目标以 m 表示；可选固定末端姿态。"""
    scratch = mujoco.MjData(model)
    scratch.qpos[:] = seed
    tool = model.site("tool").id
    jp, jr = np.zeros((3, model.nv)), np.zeros((3, model.nv))
    converged = False
    for count in range(iterations):
        mujoco.mj_forward(model, scratch)
        position_error = np.asarray(target) - scratch.site_xpos[tool]
        mujoco.mj_jacSite(model, scratch, jp, jr, tool)
        error, jac = position_error, jp[:, :7]
        if rotation is not None:
            current = scratch.site_xmat[tool].reshape(3, 3)
            angular_error = sum(np.cross(current[:, i], rotation[:, i]) for i in range(3)) / 2
            error = np.r_[position_error, angular_error]
            jac = np.vstack((jp[:, :7], jr[:, :7]))
        if np.linalg.norm(error) < 1e-4:
            converged = True
            break
        delta = jac.T @ np.linalg.solve(jac @ jac.T + 0.02**2 * np.eye(len(error)), error)
        delta *= min(1, 0.12 / max(np.linalg.norm(delta), 1e-12))
        scratch.qpos[:7] = np.clip(scratch.qpos[:7] + delta,
                                   model.jnt_range[:7, 0] + 0.002,
                                   model.jnt_range[:7, 1] - 0.002)
    mujoco.mj_forward(model, scratch)
    residual = float(np.linalg.norm(np.asarray(target) - scratch.site_xpos[tool]))
    return scratch.qpos[:7].copy(), {"converged": converged, "iterations": count + 1,
                                    "position_error_m": residual}


class PandaController:
    def __init__(self, model, data, mode):
        self.model, self.data, self.mode = model, data, mode
        self.tool = model.site("tool").id
        self.cube = model.body("cube").id
        self.cube_q = model.jnt_qposadr[model.joint("cube_free").id]
        self.key = model.key("experiment_initial").id
        self.kp = model.actuator_gainprm[:7, 0].copy()
        self.kd = -model.actuator_biasprm[:7, 2].copy()
        self.gravity_data = mujoco.MjData(model)
        self.jacp, self.jacr = np.zeros((3, model.nv)), np.zeros((3, model.nv))
        self.reset()

    def reset(self):
        mujoco.mj_resetDataKeyframe(self.model, self.data, self.key)
        mujoco.mj_forward(self.model, self.data)
        self.target_q = self.data.qpos[:7].copy()
        self.reference_q = self.target_q.copy()
        self.target = self.data.site_xpos[self.tool].copy()
        self.home_rotation = self.data.site_xmat[self.tool].reshape(3, 3).copy()
        self.width = 0.08
        self.gain_scale = 0.2 if self.mode in {"joint-control", "trajectory"} else 1.0
        self.compensation = True
        self.velocity = np.zeros(7)
        self.ik_result = None
        self.motion = None
        self.task = None
        self.phase = "待操作"
        self.max_cube_height = float(self.data.xpos[self.cube, 2])
        self.profile = "quintic"
        self.friction = 1.0
        self._set_gains()
        self._set_friction()
        self._marker()

    def _set_friction(self):
        bodies = [self.cube, self.model.body("left_finger").id, self.model.body("right_finger").id]
        self.model.geom_friction[np.isin(self.model.geom_bodyid, bodies), 0] = self.friction

    def _set_gains(self):
        enabled = 0 if self.mode == "gravity" else self.gain_scale
        self.model.actuator_gainprm[:7, 0] = self.kp * enabled
        self.model.actuator_biasprm[:7, 1] = -self.kp * enabled
        self.model.actuator_biasprm[:7, 2] = -self.kd * math.sqrt(enabled)

    def _marker(self):
        self.data.mocap_pos[self.model.body("target").mocapid[0]] = self.target

    @staticmethod
    def _vector(value, count, name):
        result = np.asarray(value, dtype=float)
        if result.shape != (count,) or not np.all(np.isfinite(result)):
            raise ValueError(f"{name} 需要 {count} 个有限数值")
        return result

    def configure(self, values):
        allowed = {"joints", "gripper_width", "target", "gain_scale", "compensation", "velocity", "profile", "friction"}
        if set(values) - allowed:
            raise ValueError("包含不支持的控制参数")
        # 所有字段先校验，再更改状态，避免非法请求只应用一部分参数。
        joints = self._vector(values.get("joints", self.target_q), 7, "关节目标")
        if np.any(joints < self.model.jnt_range[:7, 0]) or np.any(joints > self.model.jnt_range[:7, 1]):
            raise ValueError("关节目标超出模型限位")
        width = float(values.get("gripper_width", self.width))
        scale = float(values.get("gain_scale", self.gain_scale))
        if not math.isfinite(width) or not 0 <= width <= 0.08:
            raise ValueError("夹爪开口需在 [0, 0.08] m 内")
        if not math.isfinite(scale) or not 0.05 <= scale <= 1.5:
            raise ValueError("增益倍率需在 [0.05, 1.5] 内")
        target = self._vector(values.get("target", self.target), 3, "末端目标")
        if np.any(np.abs(target) > 2):
            raise ValueError("末端目标各坐标需在 [-2, 2] m 内")
        velocity = self._vector(values.get("velocity", self.velocity), 7, "关节速度")
        if np.any(np.abs(velocity) > 0.5):
            raise ValueError("关节速度需在 [-0.5, 0.5] rad/s 内")
        compensation = values.get("compensation", self.compensation)
        if not isinstance(compensation, bool):
            raise ValueError("重力补偿需为布尔值")
        profile = values.get("profile", self.profile)
        if profile not in {"quintic", "linear"}:
            raise ValueError("轨迹类型不支持")
        friction = float(values.get("friction", self.friction))
        if not math.isfinite(friction) or not 0.02 <= friction <= 2:
            raise ValueError("滑动摩擦系数需在 [0.02, 2] 内")
        self.target_q, self.target = joints.copy(), target.copy()
        self.width, self.gain_scale = width, scale
        self.velocity, self.compensation, self.profile = velocity, compensation, profile
        self.friction = friction
        self._set_friction()
        self._set_gains()
        if self.mode in {"structure", "fk", "jacobian"}:
            self.data.qpos[:7] = joints
            self.data.qpos[7:9] = width / 2
            self.data.qvel[:] = 0
            mujoco.mj_forward(self.model, self.data)
            self.target = self.data.site_xpos[self.tool].copy()
        elif self.mode == "ik":
            solution, self.ik_result = solve_ik(self.model, self.data.qpos, target)
            self.target_q = solution
            self.data.qpos[:7] = solution
            self.data.qvel[:] = 0
            mujoco.mj_forward(self.model, self.data)
        self.reference_q = self.target_q.copy()
        self._marker()

    def start_motion(self):
        self.motion = {"start": self.data.time, "q0": self.data.qpos[:7].copy(),
                       "q1": self.target_q.copy(), "duration": 3.0}
        self.phase = "轨迹跟踪"

    def start_grasp(self):
        cube = self.data.xpos[self.cube].copy()
        if abs(cube[0] - 0.45) > 0.18 or abs(cube[1]) > 0.2:
            raise ValueError("方块已离开本课抓取区域，请恢复初态")
        self.task = {"start": self.data.time, "cube": cube, "stage": -1}
        self.phase = "开始抓取"

    def _grasp_target(self):
        elapsed = self.data.time - self.task["start"]
        cube = self.task["cube"]
        stages = [
            (2.0, "移动到预抓取位置", cube + [0, 0, 0.16], 0.08),
            (4.0, "下降到抓取位置", cube, 0.08),
            (5.5, "闭合夹爪", cube, 0.0),
            (7.5, "抬升方块", cube + [0, 0, 0.16], 0.0),
            (10.0, "移动到放置区域", np.array([0.45, -0.20, 0.385]), 0.0),
            (12.0, "下降到放置位置", np.array([0.45, -0.20, 0.23]), 0.0),
            (13.5, "松开夹爪", np.array([0.45, -0.20, 0.23]), 0.08),
            (16.0, "抬升并观察放置结果", np.array([0.45, -0.20, 0.4]), 0.08),
        ]
        stage = next((i for i, item in enumerate(stages) if elapsed < item[0]), len(stages) - 1)
        if stage != self.task["stage"]:
            _, self.phase, goal, self.width = stages[stage]
            self.target = np.asarray(goal).copy()
            self.target_q, self.ik_result = solve_ik(self.model, self.data.qpos, self.target, self.home_rotation)
            self.task["q0"] = self.data.qpos[:7].copy()
            self.task["stage"] = stage
            self._marker()
        if elapsed >= 16:
            self.phase = "任务结束，请检查实际结果"
        start = 0 if stage == 0 else stages[stage - 1][0]
        u = float(np.clip((elapsed - start) / (stages[stage][0] - start), 0, 1))
        blend = 10*u**3 - 15*u**4 + 6*u**5
        return self.task["q0"] + blend * (self.target_q - self.task["q0"])

    def step(self):
        model, data = self.model, self.data
        dt = model.opt.timestep
        if self.mode in KINEMATIC:
            if self.mode == "jacobian":
                previous = data.qpos[:7].copy()
                data.qpos[:7] = np.clip(data.qpos[:7] + self.velocity * dt,
                                       model.jnt_range[:7, 0], model.jnt_range[:7, 1])
                data.qvel[:7] = (data.qpos[:7] - previous) / dt
            data.time += dt
            mujoco.mj_forward(model, data)
            return
        target_q = self._grasp_target() if self.task else self.target_q
        if self.motion:
            u = float(np.clip((data.time - self.motion["start"]) / self.motion["duration"], 0, 1))
            blend = u if self.profile == "linear" else 10*u**3 - 15*u**4 + 6*u**5
            target_q = self.motion["q0"] + blend * (self.motion["q1"] - self.motion["q0"])
            if u == 1:
                self.phase = "轨迹完成"
        data.ctrl[:7] = target_q
        self.reference_q = target_q.copy()
        data.ctrl[7] = self.width / 0.08 * 255
        data.qfrc_applied[:] = 0
        if self.compensation:
            self.gravity_data.qpos[:] = data.qpos
            self.gravity_data.qvel[:] = 0
            mujoco.mj_forward(model, self.gravity_data)
            data.qfrc_applied[:7] = self.gravity_data.qfrc_bias[:7]
        mujoco.mj_step(model, data)
        mujoco.mj_forward(model, data)
        self.max_cube_height = max(self.max_cube_height, float(data.xpos[self.cube, 2]))

    def state(self):
        model, data = self.model, self.data
        mujoco.mj_forward(model, data)
        mujoco.mj_jacSite(model, data, self.jacp, self.jacr, self.tool)
        singular = np.linalg.svd(self.jacp[:, :7], compute_uv=False)
        self.gravity_data.qpos[:] = data.qpos
        self.gravity_data.qvel[:] = 0
        mujoco.mj_forward(model, self.gravity_data)
        cube_pos = data.xpos[self.cube].copy()
        return {"time": float(data.time), "mode": self.mode, "phase": self.phase,
                "joints": data.qpos[:7].tolist(), "velocities": data.qvel[:7].tolist(),
                "target_joints": self.target_q.tolist(), "joint_limits": model.jnt_range[:7].tolist(),
                "reference_joints": self.reference_q.tolist(),
                "tool_position": data.site_xpos[self.tool].tolist(),
                "tool_rotation": data.site_xmat[self.tool].reshape(3, 3).tolist(),
                "target_position": self.target.tolist(), "gripper_width": float(sum(data.qpos[7:9])),
                "actuator_torque": data.qfrc_actuator[:7].tolist(),
                "gravity_torque": self.gravity_data.qfrc_bias[:7].tolist(),
                "jacobian": self.jacp[:, :7].tolist(),
                "cartesian_velocity": (self.jacp[:, :7] @ data.qvel[:7]).tolist(),
                "singular_values": singular.tolist(), "ik": self.ik_result,
                "gain_scale": self.gain_scale, "compensation": self.compensation,
                "cube_position": cube_pos.tolist(), "max_cube_height": self.max_cube_height,
                "contacts": int(data.ncon), "grasp_lifted": self.max_cube_height > 0.32,
                "place_success": bool(self.task and data.time - self.task["start"] >= 16
                                      and np.linalg.norm(cube_pos[:2] - [0.45, -0.2]) < 0.06
                                      and abs(cube_pos[2] - 0.225) < 0.02)}


def default_settings(mode):
    if mode == "ik":
        return {"target": [0.45, 0.12, 0.42]}
    if mode in {"joint-control", "trajectory"}:
        q = HOME.copy()
        q[0], q[1] = 0.3, 0.2
        return {"joints": q.tolist()}
    if mode == "jacobian":
        return {"velocity": [0, 0.12, 0, 0, 0, 0, 0]}
    return {}


def simulate_panda(experiment, model, data, duration, settings):
    controller = PandaController(model, data, experiment.mode)
    controller.configure(settings if settings is not None else default_settings(experiment.mode))
    if experiment.mode == "trajectory":
        controller.start_motion()
    elif experiment.mode == "grasp":
        controller.start_grasp()
    ratio = duration / model.opt.timestep
    if not math.isfinite(duration) or not 0 < duration <= 30 or not math.isclose(ratio, round(ratio)):
        raise ValueError("Panda 实验时长需在 (0, 30] 秒内，且为步长的整数倍")
    steps, samples = round(ratio), []
    stride = max(1, math.ceil(steps / 300))
    for step in range(steps + 1):
        if step:
            controller.step()
        if step % stride == 0 or step == steps:
            state = controller.state()
            error = float(np.linalg.norm(np.array(state["joints"]) - controller.reference_q))
            samples.append({"time": float(data.time), "value": float(data.qpos[0]),
                            "joints": state["joints"], "tool_position": state["tool_position"],
                            "reference_joints": state["reference_joints"],
                            "joint_error": error, "cube_height": state["cube_position"][2]})
    state = controller.state()
    return {"samples": samples, "state": state, "settings": settings if settings is not None else default_settings(experiment.mode),
            "metrics": {"steps": steps, "final_time": float(data.time),
                        "joint_error_rad": samples[-1]["joint_error"],
                        "tool_target_error_m": float(np.linalg.norm(np.array(state["tool_position"]) - controller.target)),
                        "max_cube_height_m": controller.max_cube_height},
            "model_sha256": fingerprint(experiment.model_path)}
