"""轨迹划分、特征检查和产物校验；这些规则可离线测试，不导入训练框架。"""

import json
import math
from pathlib import Path
import random


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def split_episodes(rows, fraction, seed):
    """按任务分组后打乱完整轨迹，绝不把相邻帧分别放进两侧。"""
    groups = {}
    seen = set()
    for row in rows:
        episode = int(row["episode_index"])
        if episode < 0 or episode in seen:
            raise ValueError("轨迹编号必须唯一且非负")
        seen.add(episode)
        task = tuple(row.get("tasks") or ())
        groups.setdefault(task, []).append(episode)
    if not groups or not 0 < fraction < 1:
        raise ValueError("需要非空轨迹及有效的验证比例")
    rng = random.Random(seed)
    train, validation = [], []
    for task in sorted(groups):
        episodes = sorted(groups[task])
        if len(episodes) < 2:
            raise ValueError(f"任务 {task} 至少需要两条轨迹，才能同时训练和验证")
        rng.shuffle(episodes)
        count = min(len(episodes) - 1, max(1, math.ceil(len(episodes) * fraction)))
        validation.extend(episodes[:count])
        train.extend(episodes[count:])
    return {"train": sorted(train), "validation": sorted(validation)}


def validate_schema(info):
    if info.get("codebase_version") != "v3.0":
        raise ValueError("第一版只接受 LeRobot v3.0 数据，旧数据需另行转换并验收")
    fps = info["fps"]
    if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("数据集 FPS 无效")
    features = info["features"]
    for key in ("observation.state", "action"):
        shape = features[key]["shape"]
        if len(shape) != 1 or type(shape[0]) is not int or shape[0] <= 0:
            raise ValueError(f"{key} 必须是一维非空向量")
        names = features[key].get("names")
        if names is not None and (len(names) != shape[0] or len(set(names)) != len(names)):
            raise ValueError(f"{key} 的名称与维度不一致或存在重复")
    cameras = [key for key in features if key.startswith("observation.images.")]
    if not cameras:
        raise ValueError("没有 RGB 相机特征")
    for key in cameras:
        if len(features[key]["shape"]) != 3 or features[key]["shape"][-1] != 3:
            raise ValueError(f"{key} 必须是 HWC RGB；不把重复图像伪装成多视角")
    return {
        "fps": fps, "cameras": cameras,
        "state": features["observation.state"], "action": features["action"],
        "units": "dataset-native；未将公共数据数值假定为角度或本机控制单位",
    }


def select_frame_indices(episode_indices, limit):
    """均衡覆盖各验证轨迹，再在轨迹内部选取分散的帧。"""
    groups = {}
    for index, episode in enumerate(episode_indices):
        groups.setdefault(int(episode), []).append(index)
    if not groups or limit <= 0:
        raise ValueError("没有可评估帧或样本上限无效")
    if limit < len(groups):
        raise ValueError("max_samples 小于验证轨迹数，不能覆盖所有轨迹")
    counts = {episode: 0 for episode in groups}
    budget = min(limit, len(episode_indices))
    while budget:
        for episode, frames in groups.items():
            if counts[episode] < len(frames) and budget:
                counts[episode] += 1
                budget -= 1
    selected = []
    for episode, frames in groups.items():
        count = counts[episode]
        positions = [len(frames) // 2] if count == 1 else [round(i * (len(frames) - 1) / (count - 1)) for i in range(count)]
        selected.extend(frames[position] for position in positions)
    return sorted(selected)


def validate_checkpoint(path: Path, *, resume=False):
    """完整 checkpoint 包含处理器与统计状态；只给权重文件不能验收。"""
    model = path if (path / "config.json").is_file() else path / "pretrained_model"
    required = ["config.json", "model.safetensors",
                "policy_preprocessor.json", "policy_postprocessor.json"]
    if resume:
        required.append("train_config.json")
    for name in required:
        if not (model / name).is_file():
            raise ValueError(f"不完整 checkpoint：缺少 {model / name}")
    for name in ("policy_preprocessor.json", "policy_postprocessor.json"):
        steps = read_json(model / name)["steps"]
        normalizer = "normalizer_processor" if name == "policy_preprocessor.json" else "unnormalizer_processor"
        if not any(step.get("registry_name") == normalizer and step.get("state_file") for step in steps):
            raise ValueError(f"缺少保存的归一化状态：{normalizer}")
        for step in steps:
            state_file = step.get("state_file")
            if state_file and (Path(state_file).name != state_file or not (model / state_file).is_file()):
                raise ValueError(f"处理器状态文件缺失或路径不安全：{state_file}")
    if resume:
        state = model.parent / "training_state"
        for name in ("training_step.json", "rng_state.safetensors", "optimizer_state.safetensors",
                     "optimizer_param_groups.json", "scheduler_state.json"):
            if not (state / name).is_file():
                raise ValueError(f"无法恢复训练：缺少 {state / name}")
    return model


def validate_checkpoint_protocol(model: Path, fingerprint, revisions):
    record = model / "experiment.json"
    if not record.is_file():
        raise ValueError("缺少本实验 checkpoint 协议记录，不能声称与本次基线可比")
    payload = read_json(record)
    if payload.get("config_fingerprint") != fingerprint or payload.get("revisions") != revisions:
        raise ValueError("checkpoint 的配置／数据／模型版本与本次实验不一致")


def latest_checkpoint(train_dir: Path):
    candidates = sorted((train_dir / "checkpoints").glob("[0-9]*"), key=lambda p: int(p.name) if p.name.isdigit() else -1)
    for path in reversed(candidates):
        if path.name.isdigit():
            try:
                return validate_checkpoint(path, resume=True)
            except ValueError:
                continue
    raise ValueError("没有完整 checkpoint；不能将中断写入的目录视为成功产物")


def update_checkpoint_pointer(checkpoint_dir: Path):
    # Windows 普通用户未必有 symlink 权限；保存可读索引而不修改系统权限。
    model = validate_checkpoint(checkpoint_dir, resume=True)
    step = read_json(model.parent / "training_state" / "training_step.json")["step"]
    path = checkpoint_dir.parent / "latest.json"
    write_json(path, {"checkpoint": checkpoint_dir.name, "step": step})
    return path


def compare_reports(baseline, trained):
    """只有评估协议、帧样本与数据版本一致时才计算微调前后的差异。"""
    for report in (baseline, trained):
        if report.get("status") != "completed":
            raise ValueError("不能比较失败或未完成的验收")
    for key in ("config_fingerprint", "revisions", "schema", "validation_episodes", "global_indices",
                "chunk_size", "flow_steps", "noise_seed", "precision"):
        if baseline.get(key) != trained.get(key) or key not in baseline:
            raise ValueError(f"评估协议不一致：{key}")
    before, after = baseline["metrics"]["per_axis"], trained["metrics"]["per_axis"]
    if set(before) != set(after):
        raise ValueError("动作轴名称不一致")
    return {"per_axis_delta_after_minus_before": {
                axis: {metric: after[axis][metric] - before[axis][metric] for metric in before[axis]}
                for axis in before},
            "baseline_metrics": baseline["metrics"], "trained_metrics": trained["metrics"],
            "baseline_latency": baseline["latency"], "trained_latency": trained["latency"],
            "limitations": "负误差差值表示离线拟合改善，不代表真实抓放成功率或白臂迁移成功"}
