"""XL330 BAM M6 的 NumPy 适配；公式与参数固定到 upstream.json 中的 BAM 版本。

Adapted from Rhoban/bam (actuator.py, model.py, mujoco.py).
Copyright 2025 Marc Duclusaud & Grégoire Passault. Apache-2.0.
课程只使用电压位置环、反电动势与 M6 摩擦；无训练依赖。
课程按 MuJoCo 的 DOF 编号修正摩擦约束筛选，M6 公式与拟合参数保持不变。
"""
import json
from pathlib import Path

import mujoco
import numpy as np

ASSETS = Path(__file__).parent / "assets/models/microduck"
PARAMS = json.loads((ASSETS / "xl330_m6.json").read_text())
ERROR_GAIN = 4096 / (2 * np.pi) / (256 * 885)


def prepare_spec(spec):
    """对应官方 infer_policy.py 的 load_mujoco_with_bam。"""
    limit = 8.2 * PARAMS["kt"] / PARAMS["R"]
    for actuator in spec.actuators:
        actuator.set_to_motor()
        actuator.ctrllimited = False
        actuator.forcelimited = True
        actuator.forcerange = [-limit, limit]
        actuator.gear = [1, 0, 0, 0, 0, 0]
    for joint in spec.joints:
        if joint.type == mujoco.mjtJoint.mjJNT_HINGE:
            joint.damping = np.zeros((3, 1))
            joint.frictionloss = 0
            joint.armature = PARAMS["armature"]
            joint.solref_friction = [-5e4, -2e2]
            joint.solimp_friction = [.99, .9999, .001, .5, 2]


def friction_budget(motor, external, velocity):
    p = PARAMS
    stribeck = np.exp(-np.minimum(np.abs(velocity / p["dtheta_stribeck"]), 1e3)**p["alpha"])
    friction = (p["friction_base"]
                + np.abs(external*p["load_friction_external"] - motor*p["load_friction_motor"])
                + stribeck*(p["friction_stribeck"]
                   + np.abs(external*p["load_friction_external_stribeck"] - motor*p["load_friction_motor_stribeck"])))
    quadratic = ((np.abs(external) < np.abs(motor))*p["load_friction_external_quad"]*external**2
                 + (np.abs(external) > np.abs(motor))*p["load_friction_motor_quad"]*motor**2)
    friction += stribeck * quadratic * (np.sign(external) != np.sign(motor))
    return friction, p["friction_viscous"]


class MicroduckActuator:
    def __init__(self, model, data, joint_ids):
        self.model, self.data = model, data
        self.joints = joint_ids
        self.qadr = model.jnt_qposadr[joint_ids]
        self.vadr = model.jnt_dofadr[joint_ids]
        self.voltage = 7.35
        self.kp = 200.
        self.reset()

    def reset(self):
        self.previous_torque = np.zeros(len(self.joints))
        self.model.dof_frictionloss[self.vadr] = 0
        self.model.dof_damping[self.vadr] = 0

    def update(self, target):
        m, d, p = self.model, self.data, PARAMS
        voltage = max(6., self.voltage - .1*np.sum(np.abs(self.previous_torque)))
        duty = np.clip((target-d.qpos[self.qadr])*self.kp*ERROR_GAIN, -1, 1)
        torque = p["kt"]/p["R"] * (voltage*duty - p["kt"]*d.qvel[self.vadr])
        self.previous_torque = torque.copy()
        d.ctrl[:] = torque
        external = -d.qfrc_bias[self.vadr] + d.qfrc_constraint[self.vadr]
        # 摩擦约束的 efc_id 使用 DOF 编号；扣除各自摩擦后再计算外载预算。
        friction_rows = d.efc_type == mujoco.mjtConstraint.mjCNSTR_FRICTION_DOF
        for i, dof in enumerate(self.vadr):
            external[i] -= np.sum(d.efc_force[friction_rows & (d.efc_id == dof)])
        friction, damping = friction_budget(d.qfrc_actuator[self.vadr], external, d.qvel[self.vadr])
        m.dof_frictionloss[self.vadr] = friction
        m.dof_damping[self.vadr] = damping
