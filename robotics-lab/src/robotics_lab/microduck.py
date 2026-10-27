"""Microduck 模型专属的策略、关节控制、接触观测与独立数值实验。"""
import hashlib
import math
from pathlib import Path

import mujoco
import numpy as np

from .humanoid import SmoothReference, convex_hull
from .microduck_actuator import MicroduckActuator

ASSETS = Path(__file__).parent / "assets/models/microduck"
HOME = np.array([0, -.0873, -.4579, -.0049, .4530, .3491, .3491, 0, 0,
                 0, .0873, .4579, .0049, -.4530], dtype=np.float32)
JOINT_NAMES = ["left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
               "neck_pitch", "head_pitch", "head_yaw", "head_roll", "right_hip_yaw",
               "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle"]
LEARNING_MODES = {"microduck-walking", "microduck-sitstand", "microduck-robustness"}


def default_settings(mode):
    values = {"joint_index": 7, "joint_offset": 0., "head": [0., 0., 0., 0.], "shift": 0.,
              "duration": 2., "command": [.3, 0., 0.], "friction": 1., "voltage": 7.35,
              "push_force": 1., "push_duration": .3}
    if mode == "microduck-structure":
        values["joint_offset"] = .15
    if mode == "microduck-head":
        values["head"] = [0., 0., .25, 0.]
    if mode == "microduck-robustness":
        values["command"] = [.3, 0., 0.]
    return values


class MicroduckPolicy:
    """固定官方 ONNX 的归一化及 61→512→256→128→14 ELU 网络。"""
    def __init__(self, name="velstand"):
        with np.load(ASSETS / (name + ".npz"), allow_pickle=False) as arrays:
            self.weights = {k: arrays[k].copy() for k in arrays.files}

    def __call__(self, observation):
        w = self.weights
        x = (np.asarray(observation, dtype=np.float32) - w["obs_normalizer._mean"].ravel()) / w["onnx::Div_24"].ravel()
        for index in (0, 2, 4, 6):
            x = w[f"mlp.{index}.weight"] @ x + w[f"mlp.{index}.bias"]
            if index != 6:
                x = np.maximum(x, 0) + np.expm1(np.minimum(x, 0))
        if not np.all(np.isfinite(x)):
            raise ValueError("Microduck 策略输出包含非有限值")
        return x


class MicroduckController:
    def __init__(self, model, data, mode):
        self.model, self.data, self.mode = model, data, mode
        self.root = model.body("trunk_base").id
        self.floor = model.geom("ground").id
        self.feet = [model.body("ankle_" + side).id for side in ("left", "right")]
        self.joint_ids = np.array([model.joint(name).id for name in JOINT_NAMES])
        if not np.array_equal(model.actuator_trnid[:, 0], self.joint_ids):
            raise ValueError("Microduck 执行器顺序与官方策略不符")
        self.qadr, self.vadr = model.jnt_qposadr[self.joint_ids], model.jnt_dofadr[self.joint_ids]
        self.actuator = MicroduckActuator(model, data, self.joint_ids)
        self.policy = MicroduckPolicy("sitstand" if mode == "microduck-sitstand" else "walking") if mode in LEARNING_MODES else None
        self.gyro = int(model.sensor_adr[model.sensor("imu_ang_vel").id])
        self.reset()

    def reset(self):
        self.settings = default_settings(self.mode)
        self.model.geom_friction[self.floor, 0] = 1
        self.actuator.reset()
        self.actuator.voltage = 7.35
        self.actuator.kp = 200. if self.mode == "microduck-sitstand" else 800.
        mujoco.mj_resetDataKeyframe(self.model, self.data, self.model.key("experiment_initial").id)
        mujoco.mj_forward(self.model, self.data)
        self.reference = SmoothReference(HOME.copy())
        self.command_reference = SmoothReference(np.zeros(3))
        self.head_reference = SmoothReference(np.zeros(4))
        self.posture = SmoothReference(np.zeros(1))
        self.target_q, self.reference_q = HOME.copy(), HOME.copy()
        self.action = np.zeros(14, dtype=np.float32)
        self.observation = np.zeros(61, dtype=np.float32)
        self.policy_active = self.mode == "microduck-sitstand"
        self.next_policy_time = 0.
        self.sitting = False
        self.push_start = None
        self.push_trace = []
        self.max_tilt = 0.
        self.initial_xy = self.data.qpos[:2].copy()
        self.phase = ("官方 sitstand 策略 · 站立反馈" if self.policy_active else
                      "XL330 电压位置环 · Kp=800 · 平滑关节参考")

    def configure(self, values):
        if not isinstance(values, dict) or set(values) - self.settings.keys():
            raise ValueError("包含不支持的 Microduck 参数")
        new = self.settings.copy()
        limits = {"joint_index": (0, 13), "joint_offset": (-.25, .25), "shift": (-.08, .08),
                  "duration": (1, 6), "friction": (.1, 2), "voltage": (6.5, 8.2),
                  "push_force": (-5, 5), "push_duration": (.1, 1)}
        for name, (lo, hi) in limits.items():
            if name not in values:
                continue
            value = values[name]
            if isinstance(value, bool):
                raise ValueError(f"{name}需要有限数值")
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(f"{name}需要有限数值") from error
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name}需在 [{lo}, {hi}] 内")
            if name == "joint_index":
                if value != int(value):
                    raise ValueError("关节编号需要整数")
                value = int(value)
            new[name] = value
        for name, shape, bound in (("command", (3,), [.4, .2, 1.]), ("head", (4,), [.2, .2, .6, .2])):
            if name in values:
                try:
                    vector = np.asarray(values[name], dtype=float)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"{name}需要有限数值数组") from error
                if vector.shape != shape or not np.all(np.isfinite(vector)) or np.any(np.abs(vector) > bound):
                    raise ValueError(f"{name}维度或范围无效")
                new[name] = vector.tolist()
        target = HOME.astype(float).copy()
        target[new["joint_index"]] += new["joint_offset"]
        target[5:9] += new["head"]
        target[[1, 10]] += new["shift"]
        target[[4, 13]] -= new["shift"]
        ranges = self.model.jnt_range[self.joint_ids]
        if np.any(target < ranges[:, 0]) or np.any(target > ranges[:, 1]):
            raise ValueError("目标超出模型关节限位")
        if not np.array_equal(target, self.target_q):
            self.reference.move(target, self.data.time, new["duration"])
        self.target_q = target
        if self.policy_active and new["command"] != self.settings["command"]:
            self.command_reference.move(new["command"], self.data.time, new["duration"])
        if new["head"] != self.settings["head"]:
            self.head_reference.move(new["head"], self.data.time, new["duration"])
        self.settings = new
        self.model.geom_friction[self.floor, 0] = new["friction"]
        self.actuator.voltage = new["voltage"]

    def start_walk(self):
        if self.mode not in {"microduck-walking", "microduck-robustness"}:
            raise ValueError("请在行走或扰动课启动行走策略")
        self.policy_active = True
        self.actuator.kp = 200.
        self.command_reference.move(self.settings["command"], self.data.time, self.settings["duration"])
        self.phase = "官方 alpha_walking 策略 · 50 Hz 状态反馈"

    def stop_walk(self):
        if not self.policy_active or self.mode == "microduck-sitstand":
            raise ValueError("请先启动行走策略")
        self.command_reference.move(np.zeros(3), self.data.time, self.settings["duration"])
        self.phase = "速度指令趋于零 · 保留策略站立反馈"

    def set_posture(self, sit):
        if self.mode != "microduck-sitstand":
            raise ValueError("请在坐下与站起课切换姿态")
        self.policy_active = True
        self.actuator.kp = 200.
        self.sitting = sit
        # 策略训练使用离散姿态标志；中间值会改变策略行为，物理状态不随标志重置。
        self.posture = SmoothReference(np.array([float(sit)]), self.data.time)
        self.phase = "官方 sitstand 策略 · " + ("坐下" if sit else "站起")

    def push(self):
        if self.mode != "microduck-robustness":
            raise ValueError("请在扰动实验课施加外力")
        self.push_start = float(self.data.time)
        self.push_trace = []

    def _infer(self):
        d = self.data
        rotation = d.xmat[self.root].reshape(3, 3)
        command = self.command_reference.sample(d.time)[0]
        if self.mode == "microduck-sitstand":
            command = np.array([self.posture.sample(d.time)[0][0], 0, 0])
        self.observation = np.r_[d.sensordata[self.gyro:self.gyro+3], rotation.T @ [0, 0, -1],
                                 d.qpos[self.qadr] - HOME, d.qvel[self.vadr], self.action,
                                 command, self.head_reference.sample(d.time)[0], np.zeros(6)].astype(np.float32)
        self.action = self.policy(self.observation)
        # 官方部署缩放为 1.0；控制周期内保持目标，电压位置环每个物理步执行。
        self.reference_q = HOME + self.action

    def step(self):
        d = self.data
        if self.policy_active:
            if d.time + 1e-9 >= self.next_policy_time:
                self._infer()
                self.next_policy_time = float(d.time) + .02
        else:
            self.reference_q = self.reference.sample(d.time)[0]
        self.actuator.update(self.reference_q)
        d.xfrc_applied[self.root] = 0
        if self.push_start is not None:
            u = (d.time - self.push_start) / self.settings["push_duration"]
            if u <= 1:
                d.xfrc_applied[self.root, 0] = self.settings["push_force"]*np.sin(np.pi*u)**2
            else:
                self.push_start = None
            if not self.push_trace or round(d.time/self.model.opt.timestep) % 10 == 0 or self.push_start is None:
                self.push_trace.append([float(d.time), float(d.xfrc_applied[self.root, 0])])
        mujoco.mj_step(self.model, d)
        mujoco.mj_forward(self.model, d)
        self.max_tilt = max(self.max_tilt, self.tilt())

    def tilt(self):
        return float(np.arccos(np.clip(self.data.xmat[self.root].reshape(3, 3)[2, 2], -1, 1)))

    def state(self):
        m, d = self.model, self.data
        forces, points = np.zeros((2, 3)), []
        for i in range(d.ncon):
            c = d.contact[i]
            if self.floor not in (c.geom1, c.geom2):
                continue
            other = c.geom2 if c.geom1 == self.floor else c.geom1
            body = m.geom_bodyid[other]
            if body not in self.feet:
                continue
            wrench = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, wrench)
            force = c.frame.reshape(3, 3).T @ wrench[:3] * (1 if c.geom1 == self.floor else -1)
            forces[self.feet.index(body)] += force
            if force[2] > .02:
                points.append(c.pos[:2].tolist())
        hull = convex_hull(points)
        com = d.subtree_com[self.root].copy()
        margin = None
        if len(hull) >= 3:
            distances = []
            for a, b in zip(hull, hull[1:]+hull[:1]):
                edge, delta = np.array(b)-a, com[:2]-a
                distances.append(float((edge[0]*delta[1]-edge[1]*delta[0])/np.linalg.norm(edge)))
            margin = min(distances)
        rotation = d.xmat[self.root].reshape(3, 3)
        return {"robot": "microduck", "time": float(d.time), "phase": self.phase,
                "joints": d.qpos[self.qadr].tolist(), "joint_names": JOINT_NAMES,
                "velocities": d.qvel[self.vadr].tolist(), "reference_joints": self.reference_q.tolist(),
                "target_joints": (self.reference_q if self.policy_active else self.target_q).tolist(),
                "actuator_torque": d.qfrc_actuator[self.vadr].tolist(),
                "base_position": d.qpos[:3].tolist(), "base_quaternion": d.qpos[3:7].tolist(),
                "body_velocity": (rotation.T @ d.qvel[:3]).tolist(), "com": com.tolist(),
                "support_polygon": hull, "support_margin_m": margin, "foot_forces": forces.tolist(),
                "weight_N": float(m.body_subtreemass[self.root]*9.81), "contacts": int(d.ncon),
                "tilt_rad": self.tilt(), "max_tilt_rad": self.max_tilt,
                "fallen": bool(self.tilt() > 1.), "sitting": self.sitting,
                "displacement_m": float(np.linalg.norm(d.qpos[:2]-self.initial_xy)),
                "command": self.command_reference.sample(d.time)[0].tolist(),
                "posture_command": float(self.posture.sample(d.time)[0][0]),
                "requested_command": self.settings["command"], "policy_active": self.policy_active,
                "policy_observation": self.observation.tolist(), "policy_action": self.action.tolist(),
                "push_force_N": float(d.xfrc_applied[self.root, 0]), "push_trace": self.push_trace.copy(),
                "servo_kp": self.actuator.kp, "settings": self.settings.copy()}


def simulate_microduck(experiment, model, data, duration, settings):
    ratio = duration/model.opt.timestep
    if not math.isfinite(duration) or not 0 < duration <= 20 or not math.isclose(ratio, round(ratio)):
        raise ValueError("时长需在 (0, 20] 秒内，且为仿真步长的整数倍")
    c = MicroduckController(model, data, experiment.mode)
    c.configure({**default_settings(experiment.mode), **(settings or {})})
    if experiment.mode in {"microduck-walking", "microduck-robustness"}:
        c.start_walk()
    steps, samples = round(ratio), []
    for i in range(steps+1):
        if i:
            c.step()
        if experiment.mode == "microduck-sitstand":
            if i == round(1/model.opt.timestep):
                c.set_posture(True)
            elif i == round(6/model.opt.timestep):
                c.set_posture(False)
        if experiment.mode == "microduck-robustness" and i == round(4/model.opt.timestep):
            c.push()
        if i % max(1, math.ceil(steps/400)) == 0 or i == steps:
            samples.append(c.state())
    state = c.state()
    digest = hashlib.sha256()
    for path in [experiment.model_path, *sorted(ASSETS.rglob("*"))]:
        if path.is_file():
            digest.update(path.relative_to(experiment.model_path.parent).as_posix().encode())
            digest.update(path.read_bytes())
    return {"samples": samples, "state": state, "settings": c.settings,
            "model_sha256": digest.hexdigest(),
            "metrics": {"steps": steps, "final_time": float(data.time),
                        "base_height_m": float(data.qpos[2]), "max_tilt_rad": c.max_tilt,
                        "displacement_m": state["displacement_m"],
                        "fallen_samples": sum(s["fallen"] for s in samples)}}
