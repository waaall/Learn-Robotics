"""在留出轨迹上生成动作块；动作仅保存到文件，永不发给驱动或机器人。"""

import csv
from dataclasses import replace
from pathlib import Path
import time

import numpy as np

from smolvla_common.metrics import ActionMetrics, latency_summary
from smolvla_common.config import from_record
from smolvla_common.prepared import read_prepared
from smolvla_common.protocol import select_frame_indices, validate_checkpoint, validate_checkpoint_protocol, write_json
from smolvla_common.runtime import configure_cache, load_policy, make_policy_config, open_dataset, require_runtime, tensor_stats


def observation_only(batch):
    # 推理条件只包含当前观测和语言，示范动作及未来状态不能进入模型输入。
    return {key: value for key, value in batch.items() if key.startswith("observation.") or key == "task"}


def sample_noise(policy_cfg, seed, global_index, device):
    import torch
    generator = torch.Generator(device="cpu").manual_seed(seed + global_index)
    return torch.randn((1, policy_cfg.chunk_size, policy_cfg.max_action_dim), generator=generator).to(device)


def predict_chunk(policy, preprocessor, postprocessor, batch, noise, synchronize):
    """计时边界独立于硬件实现，使条件筛选与处理器回读可以用 CPU 小模型测试。"""
    import torch
    policy.reset()
    synchronize()
    start = time.perf_counter()
    prepared = preprocessor(observation_only(batch))
    synchronize()
    preprocess_end = time.perf_counter()
    with torch.inference_mode(), torch.autocast(noise.device.type, enabled=policy.config.use_amp):
        action = policy.predict_action_chunk(prepared, noise=noise)
    synchronize()
    inference_end = time.perf_counter()
    result = postprocessor(action).detach().cpu().numpy()
    end = time.perf_counter()
    return result, {"preprocess_ms": (preprocess_end - start) * 1000,
                    "inference_ms": (inference_end - preprocess_end) * 1000,
                    "postprocess_ms": (end - inference_end) * 1000}


def infer(job, *, baseline=False, checkpoint=None):
    output = job.output_dir / ("baseline" if baseline else "checkpoint")
    # 新尝试覆盖状态标志，失败时不能把上次的成功报告当成此次验收。
    write_json(output / "report.json", {"status": "running", "hardware_connected": False})
    try:
        manifest = read_prepared(job.prepared_manifest, asset_overrides=job.asset_overrides, require_base=baseline)
        model_dir = None
        if not baseline:
            selected = checkpoint or job.checkpoint
            if selected is None:
                raise ValueError("必须显式配置 model.checkpoint 或传入 --checkpoint，不扫描训练目录")
            model_dir = validate_checkpoint(Path(selected).resolve())
            validate_checkpoint_protocol(model_dir, manifest["config_fingerprint"], manifest["revisions"])
        # 只重定位本机缓存与输出；训练身份继续使用准备记录，不依赖训练项目的代码或环境。
        cfg = replace(from_record(manifest["config"]), cache_dir=job.cache_dir, run_dir=job.output_dir)
        configure_cache(cfg, offline=True)
        return _infer_prepared(cfg, manifest, model_dir, output, baseline, job.inference)
    except BaseException as error:
        write_json(output / "report.json", {"status": "failed", "error": str(error), "hardware_connected": False})
        raise


def _infer_prepared(cfg, manifest, model_dir, output, baseline, options):
    runtime = require_runtime()
    import torch
    from torch.utils.data import default_collate
    from lerobot.policies.factory import make_pre_post_processors

    policy_cfg = make_policy_config(cfg, manifest, checkpoint=model_dir)
    policy = load_policy(policy_cfg)
    if baseline:
        # 基线也使用训练侧统计，比较的是相同输入／动作空间下微调前后的差异。
        preprocessor, postprocessor = make_pre_post_processors(policy_cfg, dataset_stats=tensor_stats(manifest["training_stats"]))
    else:
        # 重载保存的处理器状态；禁止拿验证数据统计覆盖 checkpoint 的归一化参数。
        preprocessor, postprocessor = make_pre_post_processors(
            policy_cfg, pretrained_path=str(model_dir),
            preprocessor_overrides={"device_processor": {"device": "cuda"},
                                    "tokenizer_processor": {"tokenizer_name": manifest["backbone_path"]}},
        )
    dataset = open_dataset(cfg, manifest, manifest["split"]["validation"], policy_cfg)
    selected = select_frame_indices(dataset.hf_dataset["episode_index"], options.max_samples)
    dimension = policy_cfg.action_feature.shape[0]
    names = manifest["schema"]["action"].get("names") or [f"axis_{i}" for i in range(dimension)]
    metrics = ActionMetrics(dimension)
    timings, predictions, targets, masks, records = [], [], [], [], []

    def predict(batch, global_index):
        torch.cuda.synchronize()
        start = time.perf_counter()
        # 用全局帧号绑定噪声；基线和微调模型获得同一随机初值，噪声不是关节实测状态。
        noise = sample_noise(policy_cfg, options.noise_seed, global_index, "cuda")
        torch.cuda.synchronize()
        setup_end = time.perf_counter()
        result, timing = predict_chunk(policy, preprocessor, postprocessor, batch, noise, torch.cuda.synchronize)
        timing["sampling_setup_ms"] = (setup_end - start) * 1000
        return result, timing

    warmup = default_collate([dataset[selected[0]]])
    for _ in range(options.warmup_runs):
        predict(warmup, int(warmup["index"].item()))
    torch.cuda.reset_peak_memory_stats()
    for index in selected:
        start = time.perf_counter()
        batch = default_collate([dataset[index]])
        load_ms = (time.perf_counter() - start) * 1000
        global_index = int(batch["index"].item())
        predicted, timing = predict(batch, global_index)
        target = batch["action"].numpy()
        if "action_is_pad" not in batch:
            raise ValueError("缺少动作填充掩码，不能把轨迹尾部重复动作当成有效标签")
        mask = batch["action_is_pad"].numpy()
        metrics.update(predicted, target, mask)
        timing["data_load_ms"] = load_ms
        timing["end_to_end_ms"] = load_ms + sum(timing[key] for key in ("sampling_setup_ms", "preprocess_ms", "inference_ms", "postprocess_ms"))
        timings.append(timing)
        predictions.append(predicted[0]); targets.append(target[0]); masks.append(mask[0])
        records.append({"global_index": global_index, "episode_index": int(batch["episode_index"].item()), **timing})
    report = {
        "status": "completed", "model": str(policy_cfg.pretrained_path), "runtime": runtime,
        "config_fingerprint": manifest["config_fingerprint"], "revisions": manifest["revisions"], "samples": len(selected),
        "global_indices": [record["global_index"] for record in records],
        "validation_episodes": manifest["split"]["validation"], "schema": manifest["schema"],
        "chunk_size": policy_cfg.chunk_size, "flow_steps": policy_cfg.num_steps, "noise_seed": options.noise_seed,
        "precision": "autocast-float16" if policy_cfg.use_amp else "float32",
        "metrics": metrics.summary(names),
        "latency": {key: latency_summary([sample[key] for sample in timings]) for key in timings[0]},
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(), "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "hardware_connected": False, "limitations": manifest["limitations"],
        "baseline_uses_training_stats": baseline,
    }
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / "actions.npz", predicted=np.stack(predictions), target=np.stack(targets),
                        is_pad=np.stack(masks), global_index=np.array([record["global_index"] for record in records]))
    with (output / "samples.csv").open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)
    write_json(output / "report.json", report)
    return output / "report.json"
