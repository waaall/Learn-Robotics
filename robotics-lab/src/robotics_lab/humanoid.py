"""G1 浮动基座、接触观测与连续控制；不依赖 experiments 或训练框架。"""

import hashlib
import math
from pathlib import Path

import mujoco
import numpy as np

HOME = np.array([-0.1, 0, 0, 0.3, -0.2, 0] * 2, dtype=float)
KP = np.array([100, 100, 100, 150, 40, 40] * 2, dtype=float)
KD = np.array([2, 2, 2, 4, 2, 2] * 2, dtype=float)
ASSETS = Path(__file__).parent / "assets/models/g1"


def default_settings(mode):
    settings = {"squat": 0.0, "lean": 0.0, "shift": 0.0, "duration": 3.0,
                "command": [0.3, 0.0, 0.0], "friction": 1.0,
                "push_force": 20.0, "push_duration": 0.4, "payload": 0.0}
    if mode == "g1-structure":
        settings["squat"] = 0.15
    elif mode == "g1-contact":
        settings["shift"] = 0.03
    elif mode == "g1-balance":
        settings.update(squat=0.2, shift=0.015)
    elif mode == "g1-recovery":
        settings["command"] = [0.2, 0.0, 0.0]
    return settings


def fingerprint(path):
    digest = hashlib.sha256()
    for item in [path, *sorted(ASSETS.rglob("*"))]:
        if item.is_file():
            digest.update(item.relative_to(path.parent).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


class G1Policy:
    """官方 TorchScript 的 NumPy LSTM 推理；权重只读，不执行 pickle。"""

    def __init__(self):
        with np.load(ASSETS / "policy.npz", allow_pickle=False) as weights:
            self.weights = {key: weights[key].copy() for key in weights.files}
        self.reset()

    def reset(self):
        self.hidden = np.zeros(64, dtype=np.float32)
        self.cell = np.zeros(64, dtype=np.float32)

    def __call__(self, observation):
        w = self.weights
        gates = (w["memory.weight_ih_l0"] @ np.asarray(observation, dtype=np.float32)
                 + w["memory.weight_hh_l0"] @ self.hidden
                 + w["memory.bias_ih_l0"] + w["memory.bias_hh_l0"])
        i, f, g, o = np.split(gates, 4)
        sigmoid = lambda x: 1 / (1 + np.exp(-np.clip(x, -60, 60)))
        self.cell = sigmoid(f) * self.cell + sigmoid(i) * np.tanh(g)
        self.hidden = sigmoid(o) * np.tanh(self.cell)
        x = w["actor.0.weight"] @ self.hidden + w["actor.0.bias"]
        x = np.maximum(x, 0) + np.expm1(np.minimum(x, 0))
        return w["actor.2.weight"] @ x + w["actor.2.bias"]


class SmoothReference:
    """五次多项式保留切换时刻参考的位置、速度、加速度。"""

    def __init__(self, position, now=0.0):
        self.start = now
        self.duration = 1.0
        self.coefficients = np.zeros((6, len(position)))
        self.coefficients[0] = position

    def sample(self, now):
        t = float(np.clip(now - self.start, 0, self.duration))
        c = self.coefficients
        return (sum(c[k] * t**k for k in range(6)),
                sum(k * c[k] * t**(k - 1) for k in range(1, 6)),
                sum(k * (k - 1) * c[k] * t**(k - 2) for k in range(2, 6)))

    def move(self, target, now, duration):
        q, v, a = self.sample(now)
        self.start, self.duration = now, duration
        self.coefficients[:3] = q, v, a / 2
        t = duration
        matrix = np.array([[t**3, t**4, t**5], [3*t**2, 4*t**3, 5*t**4], [6*t, 12*t**2, 20*t**3]])
        rhs = np.array([np.asarray(target) - q - v*t - a*t*t/2, -v-a*t, -a])
        self.coefficients[3:] = np.linalg.solve(matrix, rhs)


def convex_hull(points):
    points = sorted(set(map(tuple, points)))
    if len(points) < 3:
        return points
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class HumanoidController:
    def __init__(self, model, data, mode):
        self.model, self.data, self.mode = model, data, mode
        self.root = model.body("pelvis").id
        self.floor = model.geom("ground").id
        self.feet = [model.body(side + "_ankle_roll_link").id for side in ("left", "right")]
        self.joint_ids = model.actuator_trnid[:, 0].copy()
        self.qadr = model.jnt_qposadr[self.joint_ids]
        self.vadr = model.jnt_dofadr[self.joint_ids]
        self.policy = G1Policy()
        self.reset()

    def reset(self):
        mujoco.mj_resetDataKeyframe(self.model, self.data, self.model.key("experiment_initial").id)
        mujoco.mj_forward(self.model, self.data)
        self.policy.reset()
        self.settings = {"squat": 0.0, "lean": 0.0, "shift": 0.0, "duration": 3.0,
                         "command": [0.3, 0.0, 0.0], "friction": 1.0,
                         "push_force": 20.0, "push_duration": 0.4, "payload": 0.0}
        self.reference = SmoothReference(self.data.qpos[self.qadr].copy())
        self.command_reference = SmoothReference(np.zeros(3))
        self.blend = SmoothReference(np.zeros(1))
        self.reference_q = self.data.qpos[self.qadr].copy()
        self.target_q = self.reference_q.copy()
        self.action = np.zeros(self.model.nu, dtype=np.float32)
        self.observation = np.zeros(47, dtype=np.float32)
        self.policy_target = HOME.copy()
        self.previous_policy_target = HOME.copy()
        self.policy_tick = -1
        self.walking = False
        self.push_start = None
        self.push_trace = []
        self.phase = "关节 PD 站立 · 目标通过平滑参考执行"
        self.max_tilt = 0.0
        self.initial_xy = self.data.qpos[:2].copy()
        self.initial_mass = getattr(self, "initial_mass", float(self.model.body_mass[self.root]))
        self.model.body_mass[self.root] = self.initial_mass
        self.model.geom_friction[self.floor, 0] = 1.0
        mujoco.mj_setConst(self.model, mujoco.MjData(self.model))
        mujoco.mj_forward(self.model, self.data)

    @staticmethod
    def scalar(value, name, lo, hi):
        if isinstance(value, bool):
            raise ValueError(f"{name}需要有限数值")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{name}需要有限数值") from error
        if not math.isfinite(number) or not lo <= number <= hi:
            raise ValueError(f"{name}需在 [{lo}, {hi}] 内")
        return number

    def configure(self, values):
        if not isinstance(values, dict) or set(values) - self.settings.keys():
            raise ValueError("包含不支持的人形控制参数")
        limits = {"squat": (0, 0.35), "lean": (-0.12, 0.12), "shift": (-0.12, 0.12),
                  "duration": (1, 8), "friction": (0.1, 2), "push_force": (-100, 100),
                  "push_duration": (0.1, 2), "payload": (0, 5)}
        settings = self.settings.copy()
        for key, bounds in limits.items():
            if key in values:
                settings[key] = self.scalar(values[key], key, *bounds)
        if "command" in values:
            try:
                cmd = np.asarray(values["command"], dtype=float)
            except (ValueError, TypeError) as error:
                raise ValueError("速度指令需要三个有限数值") from error
            if cmd.shape != (3,) or not np.all(np.isfinite(cmd)) or np.any(np.abs(cmd) > [0.8, 0.3, 0.8]):
                raise ValueError("速度指令需在前进 ±0.8 m/s、侧移 ±0.3 m/s、转向 ±0.8 rad/s 内")
            settings["command"] = cmd.tolist()
        target = HOME.copy()
        target[[0, 6]] -= settings["squat"] / 2
        target[[3, 9]] += settings["squat"]
        target[[4, 10]] -= settings["squat"] / 2 + settings["lean"]
        target[[1, 7]] -= settings["shift"]
        target[[5, 11]] += settings["shift"]
        if not np.array_equal(target, self.target_q):
            self.reference.move(target, self.data.time, settings["duration"])
            self.target_q = target
        if settings["command"] != self.settings["command"] and self.walking:
            self.command_reference.move(settings["command"], self.data.time, settings["duration"])
        self.model.geom_friction[self.floor, 0] = settings["friction"]
        if settings["payload"] != self.settings["payload"]:
            self.model.body_mass[self.root] = self.initial_mass + settings["payload"]
            mujoco.mj_setConst(self.model, mujoco.MjData(self.model))
            mujoco.mj_forward(self.model, self.data)
        self.settings = settings

    def start_walk(self):
        if self.mode not in {"g1-walking", "g1-recovery"}:
            raise ValueError("请在人形行走或抗扰课启动学习策略")
        if self.data.qpos[2] < 0.45:
            raise ValueError("机器人已跌倒，请恢复初态后重新运行")
        self.walking = True
        self.blend.move([1.0], self.data.time, 1.0)
        self.command_reference.move(self.settings["command"], self.data.time, self.settings["duration"])
        self.phase = "学习策略行走 · 平滑速度指令"

    def stop_walk(self):
        # 保持策略运行，以零速度目标完成动态停止，保留循环网络记忆。
        self.command_reference.move(np.zeros(3), self.data.time, self.settings["duration"])
        self.phase = "学习策略减速 · 速度目标趋于零"

    def push(self):
        if self.mode != "g1-recovery":
            raise ValueError("请在扰动与恢复课施加外力")
        self.push_start = float(self.data.time)
        self.push_trace = []

    def _infer(self):
        d = self.data
        command = self.command_reference.sample(d.time)[0]
        rotation = d.xmat[self.root].reshape(3, 3)
        phase = 2 * np.pi * (d.time % 0.8) / 0.8
        self.observation = np.r_[d.qvel[3:6] * 0.25, rotation.T @ [0, 0, -1],
                                 command * [2, 2, 0.25], d.qpos[self.qadr] - HOME,
                                 d.qvel[self.vadr] * 0.05, self.action,
                                 np.sin(phase), np.cos(phase)].astype(np.float32)
        self.action = self.policy(self.observation)
        self.previous_policy_target = self.policy_target.copy()
        self.policy_target = HOME + 0.25 * self.action

    def step(self):
        d = self.data
        stance, _, _ = self.reference.sample(d.time)
        tick = int(round(d.time / self.model.opt.timestep))
        if self.walking and tick // 10 != self.policy_tick:
            self.policy_tick = tick // 10
            self._infer()
        blend = float(self.blend.sample(d.time)[0][0]) if self.walking else 0.0
        # 策略目标在相邻 20 ms 控制周期之间连续插值，避免控制参考阶跃。
        fraction = (tick % 10) / 10
        s = fraction**3 * (10 + fraction * (-15 + 6*fraction))
        policy_q = self.previous_policy_target + s * (self.policy_target - self.previous_policy_target)
        self.reference_q = (1-blend) * stance + blend * policy_q
        gain = 8.0 * (1-blend) + blend
        d.ctrl[:] = gain * KP * (self.reference_q - d.qpos[self.qadr]) - np.sqrt(gain) * KD * d.qvel[self.vadr]
        d.xfrc_applied[self.root] = 0
        was_pushing = self.push_start is not None
        if was_pushing:
            u = (d.time - self.push_start) / self.settings["push_duration"]
            if 0 <= u <= 1:
                d.xfrc_applied[self.root, 0] = self.settings["push_force"] * np.sin(np.pi*u)**2
            else:
                self.push_start = None
            # 在物理线程保留已施加输入的 50 Hz 记录，短脉冲不依赖网页轮询捕获。
            if not self.push_trace or tick % 10 == 0 or self.push_start is None:
                self.push_trace.append([float(d.time), float(d.xfrc_applied[self.root, 0])])
        mujoco.mj_step(self.model, d)
        mujoco.mj_forward(self.model, d)
        self.max_tilt = max(self.max_tilt, self.tilt())

    def tilt(self):
        return float(np.arccos(np.clip(self.data.xmat[self.root].reshape(3, 3)[2, 2], -1, 1)))

    def state(self):
        d = self.data
        forces = np.zeros((2, 3))
        points = []
        for index in range(d.ncon):
            contact = d.contact[index]
            if self.floor not in (contact.geom1, contact.geom2):
                continue
            other = contact.geom2 if contact.geom1 == self.floor else contact.geom1
            body = self.model.geom_bodyid[other]
            if body not in self.feet:
                continue
            wrench = np.zeros(6)
            mujoco.mj_contactForce(self.model, d, index, wrench)
            force = contact.frame.reshape(3, 3).T @ wrench[:3]
            if contact.geom2 == self.floor:
                force = -force
            forces[self.feet.index(body)] += force
            if force[2] > 0.5:
                points.append(contact.pos[:2].tolist())
        hull = convex_hull(points)
        com = d.subtree_com[self.root].copy()
        margin = None
        if len(hull) >= 3:
            distances = []
            for a, b in zip(hull, hull[1:]+hull[:1]):
                edge, delta = np.array(b)-a, com[:2]-a
                distances.append(float((edge[0]*delta[1]-edge[1]*delta[0]) / np.linalg.norm(edge)))
            margin = min(distances)
        rotation = d.xmat[self.root].reshape(3, 3)
        return {"robot": "g1", "time": float(d.time), "phase": self.phase,
                "joints": d.qpos[self.qadr].tolist(), "velocities": d.qvel[self.vadr].tolist(),
                "joint_names": [self.model.joint(int(j)).name for j in self.joint_ids],
                "reference_joints": self.reference_q.tolist(),
                "target_joints": (self.policy_target if self.walking else self.target_q).tolist(),
                "actuator_torque": d.qfrc_actuator[self.vadr].tolist(), "base_position": d.qpos[:3].tolist(),
                "base_quaternion": d.qpos[3:7].tolist(), "base_velocity": d.qvel[:3].tolist(),
                "body_velocity": (rotation.T @ d.qvel[:3]).tolist(), "tilt_rad": self.tilt(),
                "com": com.tolist(), "support_polygon": hull, "support_margin_m": margin,
                "weight_N": float(self.model.body_subtreemass[self.root] * np.linalg.norm(self.model.opt.gravity)),
                "foot_forces": forces.tolist(), "contacts": int(d.ncon),
                "command": self.command_reference.sample(d.time)[0].tolist(),
                "requested_command": self.settings["command"], "policy_active": self.walking,
                "policy_observation": self.observation.tolist(), "policy_action": self.action.tolist(),
                "push_force_N": float(d.xfrc_applied[self.root, 0]),
                "push_trace": self.push_trace.copy(),
                "fallen": bool(d.qpos[2] < 0.4 or self.tilt() > 1.0),
                "displacement_m": float(np.linalg.norm(d.qpos[:2]-self.initial_xy)),
                "max_tilt_rad": self.max_tilt, "settings": self.settings.copy()}


def simulate_humanoid(experiment, model, data, duration, settings):
    ratio = duration / model.opt.timestep
    if not math.isfinite(duration) or not 0 < duration <= 20 or not math.isclose(ratio, round(ratio)):
        raise ValueError("时长需在 (0, 20] 秒内，且为仿真步长的整数倍")
    controller = HumanoidController(model, data, experiment.mode)
    controller.configure({**default_settings(experiment.mode), **(settings or {})})
    if experiment.mode in {"g1-walking", "g1-recovery"}:
        controller.start_walk()
    steps = round(ratio)
    samples = []
    fallen_samples = 0
    for index in range(steps + 1):
        if index:
            controller.step()
        if experiment.mode == "g1-recovery" and index == round(4/model.opt.timestep):
            controller.push()
        if index % max(1, math.ceil(steps/400)) == 0 or index == steps:
            state = controller.state()
            samples.append(state)
            fallen_samples += int(state["fallen"])
    state = controller.state()
    return {"samples": samples, "state": state, "settings": controller.settings,
            "model_sha256": fingerprint(experiment.model_path),
            "metrics": {"steps": steps, "final_time": float(data.time),
                        "base_height_m": float(data.qpos[2]), "max_tilt_rad": controller.max_tilt,
                        "displacement_m": state["displacement_m"], "fallen_samples": fallen_samples}}
