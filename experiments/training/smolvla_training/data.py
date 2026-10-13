"""显式下载、锁定 Hub 版本并验收公开数据；不在 import 或 plan 阶段触发下载。"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from smolvla_common.metrics import feature_stats
from smolvla_common.protocol import read_json, split_episodes, validate_schema, write_json
from smolvla_common.runtime import configure_cache, load_manifest, require_runtime


def prepare(cfg):
    if (cfg.run_dir / "prepared.json").exists():
        return load_manifest(cfg)
    configure_cache(cfg)
    runtime = require_runtime()
    from huggingface_hub import HfApi, snapshot_download
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    api = HfApi()
    # 先把 main/tag 解析为完整提交号，后续下载和重载只使用该固定版本。
    model_sha = api.model_info(cfg.policy.repo_id, revision=cfg.policy.revision).sha
    dataset_sha = api.dataset_info(cfg.dataset.repo_id, revision=cfg.dataset.revision).sha
    cache = str(cfg.cache_dir / "hub")
    model_path = snapshot_download(cfg.policy.repo_id, revision=model_sha, cache_dir=cache,
                                   allow_patterns=["*.json", "*.safetensors"])
    base_config = read_json(Path(model_path) / "config.json")
    backbone_id = base_config["vlm_model_name"]
    backbone_sha = api.model_info(backbone_id, revision=cfg.policy.backbone_revision).sha
    backbone_path = snapshot_download(backbone_id, revision=backbone_sha, cache_dir=cache,
                                      allow_patterns=["*.json", "*.txt", "*.model", "*.jinja", "*.tiktoken"])
    dataset_path = snapshot_download(cfg.dataset.repo_id, repo_type="dataset", revision=dataset_sha,
                                     cache_dir=cache, allow_patterns=["meta/**", "data/**", "videos/**"])
    info = read_json(Path(dataset_path) / "meta" / "info.json")
    schema = validate_schema(info)
    dataset = LeRobotDataset(cfg.dataset.repo_id, root=dataset_path, revision=dataset_sha,
                             video_backend=cfg.dataset.video_backend)
    split = split_episodes(list(dataset.meta.episodes), cfg.dataset.validation_fraction, cfg.dataset.split_seed)
    train = LeRobotDataset(cfg.dataset.repo_id, root=dataset_path, revision=dataset_sha,
                           episodes=split["train"], video_backend=cfg.dataset.video_backend)
    # 官方 metadata 的全局 stats 可能包含验证轨迹；这里仅从训练侧原始数值重新统计。
    stats = {key: feature_stats(np.stack([np.asarray(value) for value in train.hf_dataset[key]]))
             for key in ("observation.state", "action")}
    checked = []
    for index in sorted({0, len(dataset) // 2, len(dataset) - 1}):
        sample = dataset[index]
        if not sample.get("task") or not isinstance(sample["task"], str):
            raise ValueError("缺少任务语言标签，不能用空字符串代替")
        for camera in schema["cameras"]:
            image = sample[camera]
            if image.ndim != 3 or image.shape[0] != 3 or not bool(image.isfinite().all()):
                raise ValueError(f"相机 {camera} 解码输出无效")
        checked.append(index)
    manifest = {
        "manifest_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(), "config_fingerprint": cfg.fingerprint,
        "config": cfg.to_dict(), "revisions": {"model": model_sha, "dataset": dataset_sha, "backbone": backbone_sha},
        "model_path": model_path, "dataset_path": dataset_path, "backbone_path": backbone_path,
        "backbone_repo_id": backbone_id, "dataset_info": info, "schema": schema, "split": split,
        "training_stats": stats, "train_frames": len(train), "all_frames": len(dataset),
        "decoded_sample_indices": checked, "runtime": runtime, "hardware_connected": False,
        "limitations": ["公开数据可能与基础模型预训练重叠，不能据此宣称未见任务泛化",
                         "离线误差不是闭环抓放成功率", "颜色、相机和校准向本机迁移尚未验收"],
    }
    write_json(cfg.run_dir / "prepared.json", manifest)
    return manifest
