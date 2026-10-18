"""SO-101 bounded execution math. No hardware or model imports."""

from dataclasses import asdict, dataclass
import math

from .live_hardware import JOINTS


class ControlStop(RuntimeError):
    """An experiment condition requiring a local stop."""


def audit_processors(preprocessor, postprocessor):
    """Require actual active feature stats, rather than accepting a silently skipped transform."""
    stages, issues = {}, []
    for label, pipeline, feature in (("state", preprocessor, "observation.state"),
                                      ("action", postprocessor, "action")):
        found = []
        for step in pipeline.steps:
            if not hasattr(step, "_tensor_stats"):
                continue
            keys = sorted(step._tensor_stats)
            stats = step._tensor_stats.get(feature, {})
            found.append({"processor": type(step).__name__, "available_keys": keys,
                          "feature": feature, "bound": feature in step._tensor_stats})
            if feature not in step._tensor_stats:
                issues.append(f"{label}: no normalization statistics bound to {feature}")
            elif any(k not in stats for k in ("mean", "std")):
                issues.append(f"{label}: missing mean/std")
            else:
                for name in ("mean", "std"):
                    values = stats[name].detach().cpu().reshape(-1).tolist()
                    if len(values) != 6 or not all(math.isfinite(v) for v in values):
                        issues.append(f"{label}: invalid {name} values")
                    if name == "std" and any(v <= 0 for v in values):
                        issues.append(f"{label}: nonpositive std")
        if not found:
            issues.append(f"{label}: normalization processor absent")
        stages[label] = found
    return {"ready_for_vla_execution": not issues, "issues": issues, "stages": stages}


@dataclass(frozen=True)
class Limits:
    control_hz: float = 20
    policy_hz: float = 30
    joint_speed_deg_s: float = 8
    gripper_speed_units_s: float = 12
    tracking_error_deg: float = 10
    tracking_error_gripper: float = 15
    excursion_deg: float = 20
    margin_ticks: int = 24
    max_burst_s: float = 3
    max_session_s: float = 600
    max_frame_age_s: float = .5
    max_io_s: float = .15
    max_temperature_c: float = 55

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"invalid positive limit: {name}")
        if not 5 <= self.control_hz <= 60 or not 1 <= self.policy_hz <= 60:
            raise ValueError("control/policy frequency outside supported range")
        if self.joint_speed_deg_s > 20 or self.gripper_speed_units_s > 25:
            raise ValueError("speed exceeds the experiment's hard cap")
        if self.max_burst_s > 5 or self.max_session_s > 900 or self.excursion_deg > 40:
            raise ValueError("duration/excursion exceeds the experiment's hard cap")


def validate_action(action):
    if len(action) != len(JOINTS):
        raise ControlStop("action must contain six joints")
    for joint, value in zip(JOINTS, action):
        lo = 0 if joint == "gripper" else -100
        if isinstance(value, bool) or not math.isfinite(float(value)) or not lo <= value <= 100:
            raise ControlStop(f"{joint}: model target outside assumed range-position protocol: {value}")


def validate_start(raw, calibration, limits):
    for joint in JOINTS:
        c = calibration[joint]
        low, high = c.range_min + limits.margin_ticks, c.range_max - limits.margin_ticks
        if not low <= raw[joint] <= high:
            raise ControlStop(f"{joint}: {raw[joint]} outside startup interval [{low}, {high}]")


def bounded_targets(requested, previous, measured, origin, calibration, dt, limits):
    """Bound command velocity and cumulative excursion in encoder ticks; retain every modification."""
    if not math.isfinite(dt) or not 0 < dt <= limits.max_io_s:
        raise ControlStop("control interval expired")
    targets, reasons = {}, {}
    for joint in JOINTS:
        c = calibration[joint]
        tick_per_unit = (c.range_max - c.range_min) / 100 if joint == "gripper" else 4095 / 360
        speed = limits.gripper_speed_units_s if joint == "gripper" else limits.joint_speed_deg_s
        tracking = limits.tracking_error_gripper if joint == "gripper" else limits.tracking_error_deg
        if abs(previous[joint] - measured[joint]) > tracking * tick_per_unit:
            raise ControlStop(f"{joint}: measured position failed to track the previous command")
        if not c.range_min <= measured[joint] <= c.range_max:
            raise ControlStop(f"{joint}: measured encoder outside calibration")
        low, high = c.range_min + limits.margin_ticks, c.range_max - limits.margin_ticks
        if joint != "gripper":
            excursion = limits.excursion_deg * tick_per_unit
            low, high = max(low, origin[joint] - excursion), min(high, origin[joint] + excursion)
        goal = min(high, max(low, requested[joint]))
        change = speed * tick_per_unit * dt
        target = min(previous[joint] + change, max(previous[joint] - change, goal))
        # Keep the floating trajectory accumulator; round only at the device boundary.
        targets[joint] = target
        reasons[joint] = {"range_or_excursion": goal != requested[joint],
                          "speed": abs(target - goal) > 1e-6}
    return targets, reasons
