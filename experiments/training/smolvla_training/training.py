"""复用 LeRobot 官方训练循环、优化器和 checkpoint；只适配数据划分与严格模型加载。"""

from contextlib import contextmanager
import sys
import time
from pathlib import Path
from unittest.mock import patch

from smolvla_common.protocol import latest_checkpoint, read_json, update_checkpoint_pointer, validate_checkpoint, validate_checkpoint_protocol, write_json
from smolvla_common.runtime import configure_cache, load_manifest, load_policy, make_policy_config, open_dataset, require_runtime


@contextmanager
def trainer_arguments(arguments):
    # 官方 validate 会重读命令行；不能把本实验的 --config 误解析成上游参数。
    previous = sys.argv
    sys.argv = ["lerobot-train", *arguments]
    try:
        yield
    finally:
        sys.argv = previous


def train(cfg, resume_from=None):
    configure_cache(cfg, offline=True)
    runtime = require_runtime()
    manifest = load_manifest(cfg)
    from lerobot.configs.default import DatasetConfig
    from lerobot.configs.train import TrainPipelineConfig
    from lerobot.scripts import lerobot_train

    train_dir = cfg.run_dir / "train"
    arguments = []
    if resume_from:
        model_dir = validate_checkpoint(Path(resume_from).resolve(), resume=True)
        validate_checkpoint_protocol(model_dir, cfg.fingerprint, manifest["revisions"])
        train_cfg = TrainPipelineConfig.from_pretrained(model_dir / "train_config.json", local_files_only=True)
        if Path(train_cfg.output_dir).resolve() != train_dir:
            raise ValueError("只能恢复本次 run_dir 的 checkpoint，不能混用其他运行")
        step = read_json(model_dir.parent / "training_state" / "training_step.json")["step"]
        if step >= train_cfg.steps:
            raise ValueError("checkpoint 已达到配置的总步数，不需要恢复")
        train_cfg.resume = True
        train_cfg.policy.vlm_model_name = manifest["backbone_path"]
        train_cfg.policy.load_vlm_weights = False
        arguments = [f"--config_path={model_dir / 'train_config.json'}"]
    else:
        if train_dir.exists():
            raise ValueError("训练目录已存在；请显式 --resume-from，或换 run_dir，禁止覆盖")
        policy_cfg = make_policy_config(cfg, manifest)
        train_cfg = TrainPipelineConfig(
            dataset=DatasetConfig(repo_id=cfg.dataset.repo_id, root=manifest["dataset_path"],
                                  revision=manifest["revisions"]["dataset"],
                                  video_backend=cfg.dataset.video_backend, use_imagenet_stats=False,
                                  eval_split=cfg.dataset.validation_fraction),
            policy=policy_cfg, output_dir=train_dir, job_name=cfg.run_dir.name,
            steps=cfg.training.steps, batch_size=cfg.training.batch_size, num_workers=cfg.training.num_workers,
            seed=cfg.training.seed, save_freq=cfg.training.save_freq, log_freq=cfg.training.log_freq,
            eval_steps=cfg.training.eval_freq, max_eval_samples=cfg.training.max_eval_samples,
            env_eval_freq=0, persistent_workers=cfg.training.num_workers > 0,
        )

    def datasets_adapter(active_cfg):
        if active_cfg.dataset.root != manifest["dataset_path"] or active_cfg.dataset.revision != manifest["revisions"]["dataset"]:
            raise ValueError("训练配置的数据路径／版本与准备记录不符")
        return tuple(open_dataset(cfg, manifest, manifest["split"][side], active_cfg.policy)
                     for side in ("train", "validation"))

    def policy_adapter(*, cfg, ds_meta, rename_map):
        # 模型权重必须严格匹配，不能让缺失参数静默保持随机初始化。
        if rename_map:
            raise ValueError("本实验从数据集特征构建输入，不额外重命名或伪造视角")
        return load_policy(cfg)

    original_processors = lerobot_train.make_pre_post_processors

    def processors_adapter(*args, **kwargs):
        # 基础模型的处理器可能写着未固定版本的 Hub 名称，改为本次冻结的本地 tokenizer。
        overrides = dict(kwargs.get("preprocessor_overrides", {}))
        overrides["tokenizer_processor"] = {"tokenizer_name": manifest["backbone_path"]}
        kwargs["preprocessor_overrides"] = overrides
        return original_processors(*args, **kwargs)

    def checkpoint_adapter(checkpoint_dir):
        write_json(checkpoint_dir / "pretrained_model" / "experiment.json",
                   {"config_fingerprint": cfg.fingerprint, "revisions": manifest["revisions"]})
        return update_checkpoint_pointer(checkpoint_dir)

    report_path = cfg.run_dir / "training-result.json"
    write_json(report_path, {"status": "running", "runtime": runtime, "hardware_connected": False})
    start = time.perf_counter()
    try:
        # 替换仅限此进程和本次调用，不修改第三方源码；上游仍负责更新、保存和恢复状态。
        with trainer_arguments(arguments), patch.object(lerobot_train, "make_train_eval_datasets", datasets_adapter), \
                patch.object(lerobot_train, "make_policy", policy_adapter), \
                patch.object(lerobot_train, "make_pre_post_processors", processors_adapter), \
                patch.object(lerobot_train, "update_last_checkpoint", checkpoint_adapter):
            lerobot_train.train(train_cfg)
        model_dir = latest_checkpoint(train_dir)
        validate_checkpoint_protocol(model_dir, cfg.fingerprint, manifest["revisions"])
        actual_step = read_json(model_dir.parent / "training_state" / "training_step.json")["step"]
        if actual_step != train_cfg.steps:
            raise RuntimeError("最后 checkpoint 的训练步数与目标不一致")
        write_json(report_path, {"status": "completed", "steps": actual_step,
                                "elapsed_seconds": time.perf_counter() - start, "checkpoint": str(model_dir),
                                "runtime": runtime, "hardware_connected": False,
                                "offline_inference_verified": False})
        return model_dir
    except BaseException as error:
        write_json(report_path, {"status": "failed", "error": str(error),
                                "elapsed_seconds": time.perf_counter() - start, "hardware_connected": False})
        raise
