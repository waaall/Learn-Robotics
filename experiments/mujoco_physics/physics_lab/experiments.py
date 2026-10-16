"""四个小规模算例分别核对执行器、关节耦合、重力及接触求解。"""

from pathlib import Path

import mujoco
import numpy as np

from .common import load_model, mass_matrix, require, residual, rollout, sha256


def torque(model: mujoco.MjModel, data: mujoco.MjData, case: dict) -> tuple[dict, dict]:
    require(model.nv == model.nq == model.nu == 1, "力矩算例需要一个关节和一个标量电机")
    require(np.allclose(model.opt.gravity, 0) and np.allclose(model.dof_damping, 0),
            "力矩算例要求关闭重力和关节阻尼")
    require(model.opt.integrator == mujoco.mjtIntegrator.mjINT_EULER,
            "半隐式欧拉解析检查需要 Euler 积分器")
    geom = model.geom(case["geom"]).id
    body = model.geom_bodyid[geom]
    drive = model.actuator(case["actuator"]).id
    require(model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_SPHERE
            and np.allclose(model.body_ipos[body], 0)
            and np.allclose(model.jnt_pos, 0) and model.ngeom == 1,
            "解析惯量检查要求唯一实心球的质心位于关节原点")
    inertia = (2 / 5) * model.body_mass[body] * model.geom_size[geom, 0] ** 2
    inertia += model.dof_armature[0]
    expected_torque = data.ctrl[model.actuator_ctrladr[drive]] * model.actuator_gear[drive, 0]
    acceleration = expected_torque / inertia
    q0, v0 = float(data.qpos[0]), float(data.qvel[0])
    max_acceleration_error = 0.0
    for _ in rollout(model, data, case["duration"]):
        max_acceleration_error = max(max_acceleration_error, abs(data.qacc[0] - acceleration))
    elapsed = float(data.time)
    continuous = q0 + v0 * elapsed + 0.5 * acceleration * elapsed**2
    discrete = continuous + 0.5 * acceleration * elapsed * model.opt.timestep
    metrics = {
        "inertia_kg_m2": float(inertia), "torque_Nm": float(data.qfrc_actuator[0]),
        "expected_acceleration_rad_s2": float(acceleration),
        "actual_acceleration_rad_s2": float(data.qacc[0]),
        "max_acceleration_error": float(max_acceleration_error),
        "qpos_rad": float(data.qpos[0]), "continuous_qpos_rad": float(continuous),
        "semi_implicit_qpos_rad": float(discrete),
        "continuous_position_error_rad": float(abs(data.qpos[0] - continuous)),
        "semi_implicit_position_error_rad": float(abs(data.qpos[0] - discrete)),
        "time_s": elapsed,
    }
    checks = {
        "actuator_torque_matches": abs(data.qfrc_actuator[0] - expected_torque) < case["atol"],
        "acceleration_matches": max_acceleration_error < case["atol"],
        "discrete_integration_matches": abs(data.qpos[0] - discrete) < case["atol"],
        "dynamics_residual_small": residual(model, data) < case["atol"],
    }
    return metrics, checks


def coupling(model: mujoco.MjModel, data: mujoco.MjData, case: dict) -> tuple[dict, dict]:
    require(model.nv == model.nq == 2 and np.allclose(data.qvel, 0)
            and np.allclose(model.opt.gravity, 0), "耦合算例需要静止、无重力的双关节模型")
    require(abs(data.qfrc_actuator[1]) < case["atol"], "第二关节必须没有驱动力矩")
    matrix = mass_matrix(model, data)
    net_force = data.qfrc_smooth + data.qfrc_constraint
    coupled = np.linalg.solve(matrix, net_force)
    # 与对角近似比较；此处只检查编译后动力学方程的一致性。
    independent = net_force / np.diag(matrix)
    metrics = {
        "mass_matrix": matrix.tolist(), "joint_torque_Nm": data.qfrc_actuator.tolist(),
        "qacc_rad_s2": data.qacc.tolist(), "matrix_solve_qacc_rad_s2": coupled.tolist(),
        "diagonal_approximation_qacc_rad_s2": independent.tolist(),
        "dynamics_residual": residual(model, data),
    }
    checks = {
        "mass_matrix_has_coupling": abs(matrix[0, 1]) > case["min_coupling"],
        "unpowered_joint_accelerates": abs(data.qacc[1]) > case["min_passive_acceleration"],
        "coupled_solve_matches": np.max(np.abs(coupled - data.qacc)) < case["atol"],
        "dynamics_residual_small": metrics["dynamics_residual"] < case["atol"],
    }
    return metrics, checks


def pendulum(model: mujoco.MjModel, data: mujoco.MjData, case: dict) -> tuple[dict, dict]:
    require(model.nq == model.nv == 1 and model.nbody == 2 and np.allclose(data.qvel, 0),
            "重力解析检查需要静止起步的单刚体、单铰链")
    joint, body = model.joint(case["joint"]).id, model.body(case["body"]).id
    require(model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_HINGE,
            "重力算例需要铰链关节")
    require(np.allclose(model.dof_damping, 0) and model.nu == 0,
            "能量检查要求无关节阻尼且无执行器")
    # 在世界坐标中独立计算重力矩和绕铰链的转动惯量，避免依赖惯量轴排列。
    axis = data.xaxis[joint]
    arm = data.xipos[body] - data.xanchor[joint]
    rotation = data.ximat[body].reshape(3, 3)
    inertia_world = rotation @ np.diag(model.body_inertia[body]) @ rotation.T
    mass = model.body_mass[body]
    inertia = axis @ inertia_world @ axis + mass * (arm @ arm - (axis @ arm) ** 2)
    inertia += model.dof_armature[0]
    gravity_torque = axis @ np.cross(arm, mass * model.opt.gravity)
    expected = float(gravity_torque / inertia)
    actual, bias = float(data.qacc[0]), float(data.qfrc_bias[0])
    energies = []
    for _ in rollout(model, data, case["duration"]):
        mujoco.mj_energyPos(model, data)
        mujoco.mj_energyVel(model, data)
        energies.append(float(np.sum(data.energy)))
    drift = max(abs(value - energies[0]) for value in energies)
    relative_drift = drift / max(abs(energies[0]), np.finfo(float).eps)
    metrics = {
        "initial_gravity_torque_Nm": float(gravity_torque), "initial_bias_Nm": bias,
        "initial_expected_qacc_rad_s2": expected, "initial_actual_qacc_rad_s2": actual,
        "initial_energy_J": energies[0], "max_energy_drift_J": drift,
        "max_relative_energy_drift": relative_drift, "final_qpos_rad": float(data.qpos[0]),
    }
    checks = {
        "gravity_acceleration_matches": abs(actual - expected) < case["atol"],
        "bias_is_negative_gravity_torque": abs(bias + gravity_torque) < case["atol"],
        "energy_drift_small": relative_drift < case["energy_relative_tolerance"],
    }
    return metrics, checks


def contact(model: mujoco.MjModel, data: mujoco.MjData, case: dict) -> tuple[dict, dict]:
    ball, ground = model.geom(case["ball_geom"]).id, model.geom(case["ground_geom"]).id
    require(model.geom_type[ball] == mujoco.mjtGeom.mjGEOM_SPHERE
            and model.geom_type[ground] == mujoco.mjtGeom.mjGEOM_PLANE,
            "落球算例需要球体和地面平面")
    require(model.nbody == 2 and model.nq == 7 and model.nv == 6,
            "落球算例只支持一个自由刚体和固定地面")
    require(np.allclose(data.geom_xmat[ground].reshape(3, 3)[:, 2], [0, 0, 1])
            and np.allclose(model.opt.gravity[:2], 0) and model.opt.gravity[2] < 0,
            "支撑力检查需要水平地面和沿负 z 轴的重力")
    require(0 < case["settle_window"] <= case["duration"], "稳定采样窗口必须位于仿真时长内")
    radius = model.geom_size[ball, 0]
    mass = model.body_mass[model.geom_bodyid[ball]]
    weight = float(-mass * model.opt.gravity[2])
    supports, gaps = [], []
    max_contacts, max_residual, min_gap = 0, 0.0, float("inf")
    wrench = np.empty(6)
    for _ in rollout(model, data, case["duration"]):
        gap = float(data.geom_xpos[ball, 2] - data.geom_xpos[ground, 2] - radius)
        min_gap = min(min_gap, gap)
        max_contacts = max(max_contacts, int(data.ncon))
        max_residual = max(max_residual, residual(model, data))
        support = 0.0
        for index in range(data.ncon):
            item = data.contact[index]
            if {item.geom1, item.geom2} != {ball, ground}:
                continue
            mujoco.mj_contactForce(model, data, index, wrench)
            # 接触坐标轴按行存储；力从 geom1 指向 geom2，转换为球体所受世界系力。
            world_force = item.frame.reshape(3, 3).T @ wrench[:3]
            support += world_force[2] * (1 if item.geom2 == ball else -1)
        if data.time >= case["duration"] - case["settle_window"]:
            supports.append(float(support))
            gaps.append(gap)
    support_mean = float(np.mean(supports))
    metrics = {
        "nq": model.nq, "nv": model.nv, "weight_N": weight,
        "settled_mean_support_N": support_mean,
        "support_relative_error": abs(support_mean - weight) / weight,
        "settled_mean_gap_m": float(np.mean(gaps)),
        "max_penetration_m": max(0.0, -min_gap), "max_contact_count": max_contacts,
        "final_speed_norm": float(np.linalg.norm(data.qvel)),
        "max_dynamics_residual": max_residual,
    }
    checks = {
        "contact_detected": max_contacts > 0,
        "support_balances_weight": metrics["support_relative_error"] < case["support_relative_tolerance"],
        "settled_gap_small": abs(metrics["settled_mean_gap_m"]) < case["height_atol"],
        "ball_settled": metrics["final_speed_norm"] < case["speed_atol"],
        "dynamics_residual_small": max_residual < case["residual_atol"],
    }
    return metrics, checks


EXPERIMENTS = {"torque": torque, "coupling": coupling, "pendulum": pendulum, "contact": contact}


def run_case(name: str, case: dict, base: Path) -> dict:
    model, data = load_model(case, base)
    metrics, checks = EXPERIMENTS[case["kind"]](model, data, case)
    return {
        "name": name, "kind": case["kind"], "model_sha256": sha256(base / case["model"]),
        "settings": {
            "nq": model.nq, "nv": model.nv, "nu": model.nu,
            "timestep": float(model.opt.timestep), "gravity": model.opt.gravity.tolist(),
            "integrator": mujoco.mjtIntegrator(model.opt.integrator).name,
            "solver": mujoco.mjtSolver(model.opt.solver).name,
        },
        "metrics": metrics, "checks": {key: bool(value) for key, value in checks.items()},
        "passed": bool(all(checks.values())),
    }
