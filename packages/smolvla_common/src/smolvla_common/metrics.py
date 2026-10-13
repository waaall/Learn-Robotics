"""在数据原始动作空间计算误差，排除轨迹尾部填充，并单独保留夹爪等各轴指标。"""

import numpy as np


def feature_stats(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or not len(values) or not np.isfinite(values).all():
        raise ValueError("统计输入必须是非空、有限的帧×维度矩阵")
    return {"mean": values.mean(axis=0).tolist(), "std": values.std(axis=0).tolist(),
            "min": values.min(axis=0).tolist(), "max": values.max(axis=0).tolist(),
            "count": [len(values)]}


class ActionMetrics:
    def __init__(self, dimension):
        self.absolute = np.zeros(dimension, dtype=np.float64)
        self.squared = np.zeros(dimension, dtype=np.float64)
        self.first_absolute = np.zeros(dimension, dtype=np.float64)
        self.valid_steps = 0
        self.first_steps = 0

    def update(self, predicted, target, is_pad):
        predicted, target = np.asarray(predicted), np.asarray(target)
        is_pad = np.asarray(is_pad, dtype=bool)
        if predicted.ndim != 3 or predicted.shape != target.shape or is_pad.shape != target.shape[:2]:
            raise ValueError("动作形状必须一致为 B×K×D，填充掩码必须是 B×K")
        if predicted.shape[-1] != len(self.absolute):
            raise ValueError("动作维度与指标配置不一致")
        if not np.isfinite(predicted).all() or not np.isfinite(target).all():
            raise ValueError("动作包含 NaN 或无穷值")
        error = predicted.astype(np.float64) - target
        valid = ~is_pad
        self.absolute += np.abs(error[valid]).sum(axis=0)
        self.squared += np.square(error[valid]).sum(axis=0)
        self.valid_steps += int(valid.sum())
        first_valid = valid[:, 0]
        self.first_absolute += np.abs(error[:, 0][first_valid]).sum(axis=0)
        self.first_steps += int(first_valid.sum())

    def summary(self, names):
        if not self.valid_steps or not self.first_steps or len(names) != len(self.absolute):
            raise ValueError("没有有效动作或动作名称维度不一致")
        return {
            "valid_action_steps": self.valid_steps,
            "per_axis": {name: {"mae": float(self.absolute[i] / self.valid_steps),
                                "rmse": float(np.sqrt(self.squared[i] / self.valid_steps)),
                                "first_action_mae": float(self.first_absolute[i] / self.first_steps)}
                         for i, name in enumerate(names)},
        }


def latency_summary(values):
    values = np.asarray(values, dtype=np.float64)
    if not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("计时样本无效")
    return {"p50_ms": float(np.percentile(values, 50)), "p95_ms": float(np.percentile(values, 95)),
            "max_ms": float(values.max())}
