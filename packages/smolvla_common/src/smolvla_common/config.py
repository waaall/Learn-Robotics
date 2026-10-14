"""读取、校验实验配置；路径以配置声明的基目录为准，不依赖启动目录。"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class DatasetConfig:
    repo_id: str
    revision: str = "main"
    validation_fraction: float = 0.2
    split_seed: int = 42
    video_backend: str = "torchcodec"


@dataclass(frozen=True)
class PolicyConfig:
    repo_id: str
    revision: str = "main"
    backbone_revision: str = "main"
    chunk_size: int = 50
    num_steps: int = 10
    train_expert_only: bool = True
    freeze_vision_encoder: bool = True
    train_state_proj: bool = True
    use_amp: bool = False


@dataclass(frozen=True)
class TrainingConfig:
    steps: int = 20000
    batch_size: int = 8
    num_workers: int = 0
    learning_rate: float = 1e-4
    warmup_steps: int = 1000
    save_freq: int = 2000
    log_freq: int = 100
    eval_freq: int = 2000
    max_eval_samples: int = 0
    seed: int = 42


@dataclass(frozen=True)
class InferenceConfig:
    max_samples: int = 128
    warmup_runs: int = 3
    noise_seed: int = 123


@dataclass(frozen=True)
class ExperimentConfig:
    cache_dir: Path
    run_dir: Path
    dataset: DatasetConfig
    policy: PolicyConfig
    training: TrainingConfig = field(default_factory=TrainingConfig)

    def to_dict(self):
        result = asdict(self)
        result["cache_dir"] = str(self.cache_dir)
        result["run_dir"] = str(self.run_dir)
        return result

    @property
    def fingerprint(self):
        return fingerprint(self.to_dict())


def fingerprint(value):
    payload = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def from_record(raw):
    """还原冻结参数，不按推理机器的目录重新计算训练身份。"""
    if set(raw) != {"cache_dir", "run_dir", "dataset", "policy", "training"}:
        raise ValueError("准备记录的配置格式不兼容；旧运行不自动升级，请保留后在新 run_dir 准备")
    cfg = ExperimentConfig(Path(raw["cache_dir"]), Path(raw["run_dir"]),
                           DatasetConfig(**raw["dataset"]), PolicyConfig(**raw["policy"]),
                           TrainingConfig(**raw["training"]))
    validate_config(cfg)
    return cfg


def load_config(path: Path) -> ExperimentConfig:
    path = path.resolve()
    with path.open("rb") as source:
        raw = tomllib.load(source)
    allowed = {"paths", "dataset", "policy", "training"}
    if set(raw) - allowed:
        raise ValueError(f"未知配置节：{sorted(set(raw) - allowed)}")
    paths = dict(raw["paths"])
    if set(paths) != {"base_dir", "cache_dir", "run_dir"}:
        raise ValueError("paths 必须包含 base_dir、cache_dir、run_dir")
    base = (path.parent / paths["base_dir"]).resolve()
    cfg = ExperimentConfig(
        cache_dir=(base / paths["cache_dir"]).resolve(),
        run_dir=(base / paths["run_dir"]).resolve(),
        dataset=DatasetConfig(**raw["dataset"]),
        policy=PolicyConfig(**raw["policy"]),
        training=TrainingConfig(**raw.get("training", {})),
    )
    validate_config(cfg)
    return cfg


def validate_config(cfg: ExperimentConfig):
    for name, value in (("dataset.repo_id", cfg.dataset.repo_id), ("policy.repo_id", cfg.policy.repo_id)):
        if not isinstance(value, str) or len(value.split("/")) != 2 or not all(value.split("/")):
            raise ValueError(f"{name} 必须是 owner/name")
    for revision in (cfg.dataset.revision, cfg.policy.revision, cfg.policy.backbone_revision):
        if not isinstance(revision, str) or not revision:
            raise ValueError("revision 不能为空")
    if not 0 < cfg.dataset.validation_fraction < 1:
        raise ValueError("validation_fraction 必须在 0 与 1 之间")
    if cfg.dataset.video_backend not in {"torchcodec", "pyav"}:
        raise ValueError("video_backend 必须是 torchcodec 或 pyav")
    positive = {
        "steps": cfg.training.steps, "batch_size": cfg.training.batch_size,
        "chunk_size": cfg.policy.chunk_size, "num_steps": cfg.policy.num_steps,
        "save_freq": cfg.training.save_freq, "log_freq": cfg.training.log_freq,
        "eval_freq": cfg.training.eval_freq,
    }
    for name, value in positive.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} 必须是正整数")
    for name, value in (("num_workers", cfg.training.num_workers),
                        ("max_eval_samples", cfg.training.max_eval_samples),
                        ("warmup_steps", cfg.training.warmup_steps), ("seed", cfg.training.seed),
                        ("split_seed", cfg.dataset.split_seed)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} 必须是非负整数")
    if cfg.training.warmup_steps >= cfg.training.steps:
        raise ValueError("warmup_steps 必须小于总训练步数")
    if not math.isfinite(cfg.training.learning_rate) or cfg.training.learning_rate <= 0:
        raise ValueError("learning_rate 必须是有限正数")
    for value in (cfg.policy.train_expert_only, cfg.policy.freeze_vision_encoder,
                  cfg.policy.train_state_proj, cfg.policy.use_amp):
        if type(value) is not bool:
            raise ValueError("策略开关必须为布尔值")


def validate_inference(cfg: InferenceConfig):
    if type(cfg.max_samples) is not int or cfg.max_samples <= 0:
        raise ValueError("max_samples 必须是正整数")
    for name, value in (("warmup_runs", cfg.warmup_runs), ("noise_seed", cfg.noise_seed)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} 必须是非负整数")
