"""隔离缓存和官方接口适配；只有实际实验命令才导入 LeRobot 等重依赖。"""

import importlib.metadata as metadata
import os
from pathlib import Path

from .prepared import read_prepared


def configure_cache(cfg, *, offline=False):
    # 所有设置仅作用于本进程，模型和数据缓存不挤占系统盘默认目录。
    os.environ["HF_HOME"] = str(cfg.cache_dir / "hf")
    os.environ["HF_HUB_CACHE"] = str(cfg.cache_dir / "hub")
    os.environ["HF_LEROBOT_HOME"] = str(cfg.cache_dir / "datasets")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def require_runtime():
    expected = {"lerobot": "0.6.1", "torch": "2.10.0", "torchvision": "0.25.0", "torchcodec": "0.10.0"}
    versions = {}
    for name in (*expected, "transformers", "accelerate", "huggingface-hub", "numpy"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError as error:
            raise RuntimeError(f"缺少 {name}；请在当前独立项目运行 setup.ps1 部署锁定环境") from error
    for name, version in expected.items():
        if versions[name].split("+")[0] != version:
            raise RuntimeError(f"接口适配要求 {name}=={version}，当前为 {versions[name]}")
    from packaging.version import Version
    for name, lower, upper in (("transformers", "5.4.0", "5.6.0"), ("accelerate", "1.14.0", "2.0.0")):
        if not Version(lower) <= Version(versions[name]) < Version(upper):
            raise RuntimeError(f"{name} 版本不符合锁定接口范围：[{lower}, {upper})")
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("本实验要求 CUDA；不会静默切换 CPU 或连接机械臂")
    return {"packages": versions, "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda}


def load_manifest(cfg):
    path = cfg.run_dir / "prepared.json"
    if not path.is_file():
        raise ValueError("尚未 prepare；请先显式下载并检查公开数据与预训练模型")
    manifest = read_prepared(path)
    if manifest["config_fingerprint"] != cfg.fingerprint:
        raise ValueError("配置已改变；请使用新的 run_dir 重新 prepare，避免混用数据划分和训练设置")
    return manifest


def make_policy_config(cfg, manifest, *, checkpoint=None):
    from lerobot.configs import FeatureType, NormalizationMode
    from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
    from lerobot.utils.feature_utils import dataset_to_policy_features

    source = Path(checkpoint or manifest["model_path"])
    policy_cfg = SmolVLAConfig.from_pretrained(source, local_files_only=True)
    if policy_cfg.type != "smolvla":
        raise ValueError("预训练模型不是 SmolVLA")
    features = dataset_to_policy_features(manifest["dataset_info"]["features"])
    inputs = {key: value for key, value in features.items() if key.startswith("observation.")}
    outputs = {key: value for key, value in features.items() if value.type == FeatureType.ACTION}
    if set(outputs) != {"action"}:
        raise ValueError("只支持单一 action 向量")
    if inputs["observation.state"].shape[0] > policy_cfg.max_state_dim or outputs["action"].shape[0] > policy_cfg.max_action_dim:
        raise ValueError("数据维度超过预训练模型容量；不能静默截断")
    if checkpoint:
        if policy_cfg.input_features != inputs or policy_cfg.output_features != outputs:
            raise ValueError("checkpoint 的特征名称／形状与当前数据集不一致")
    else:
        # 相机名称和数量来自真实数据，不能照搬基础模型的三个占位视角。
        policy_cfg.input_features, policy_cfg.output_features = inputs, outputs
        policy_cfg.chunk_size = policy_cfg.n_action_steps = cfg.policy.chunk_size
        policy_cfg.num_steps = cfg.policy.num_steps
        policy_cfg.train_expert_only = cfg.policy.train_expert_only
        policy_cfg.freeze_vision_encoder = cfg.policy.freeze_vision_encoder
        policy_cfg.train_state_proj = cfg.policy.train_state_proj
        policy_cfg.use_amp = cfg.policy.use_amp
        policy_cfg.optimizer_lr = cfg.training.learning_rate
        policy_cfg.scheduler_warmup_steps = cfg.training.warmup_steps
        policy_cfg.scheduler_decay_steps = cfg.training.steps
    required_modes = {"VISUAL": NormalizationMode.IDENTITY, "STATE": NormalizationMode.MEAN_STD,
                      "ACTION": NormalizationMode.MEAN_STD}
    if any(policy_cfg.normalization_mapping.get(key) != value for key, value in required_modes.items()):
        raise ValueError("第一版要求视觉 IDENTITY、状态／动作 MEAN_STD；只使用训练侧统计")
    if policy_cfg.adapt_to_pi_aloha or policy_cfg.use_delta_joint_actions_aloha or policy_cfg.empty_cameras:
        raise ValueError("第一版不启用 ALOHA 动作转换或伪造相机")
    policy_cfg.device = "cuda"
    policy_cfg.push_to_hub = False
    policy_cfg.pretrained_path = source
    policy_cfg.vlm_model_name = manifest["backbone_path"]
    # 完整 SmolVLA checkpoint 已含 VLM 权重，只用固定版本的骨干配置初始化结构。
    policy_cfg.load_vlm_weights = False
    policy_cfg.compile_model = False
    policy_cfg.rtc_config = None
    return policy_cfg


def load_policy(policy_cfg):
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    return SmolVLAPolicy.from_pretrained(policy_cfg.pretrained_path, config=policy_cfg,
                                        local_files_only=True, strict=True).to("cuda").eval()


def tensor_stats(stats):
    import torch
    return {key: {name: torch.tensor(value, dtype=torch.float32) for name, value in feature.items()}
            for key, feature in stats.items()}


def open_dataset(cfg, manifest, episodes, policy_cfg=None):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    args = dict(repo_id=cfg.dataset.repo_id, root=manifest["dataset_path"],
                revision=manifest["revisions"]["dataset"], episodes=episodes,
                video_backend=cfg.dataset.video_backend, return_uint8=False)
    if policy_cfg is not None:
        meta = LeRobotDatasetMetadata(args["repo_id"], root=args["root"], revision=args["revision"])
        args["delta_timestamps"] = resolve_delta_timestamps(policy_cfg, meta)
    dataset = LeRobotDataset(**args)
    actual = {int(value) for value in dataset.hf_dataset["episode_index"]}
    if actual != set(episodes):
        raise ValueError("实际加载轨迹与冻结的数据划分不一致")
    dataset.meta.stats = tensor_stats(manifest["training_stats"])
    return dataset
