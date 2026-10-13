"""单 wrist 实时推理诊断：真实输入、基础权重、仅落盘，没有动作执行入口。"""

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
import hashlib
import os
from pathlib import Path
import time
import tempfile
import tomllib

import numpy as np

from smolvla_common.metrics import latency_summary
from smolvla_common.protocol import write_json
from .live_hardware import JOINTS, LatestCamera, ReadOnlyFollower

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "configs/smolvla-wrist-live.toml"
IMAGE_KEY = "observation.images.wrist"


@dataclass(frozen=True)
class LiveConfig:
    cache_dir: Path
    output_dir: Path
    calibration: Path
    repo_id: str
    revision: str
    follower_serial: str
    camera_index: int
    width: int
    height: int
    fps: int
    task: str
    samples: int
    warmup_runs: int
    noise_seed: int
    use_amp: bool

    @property
    def assets_path(self):
        return self.cache_dir / "assets.json"

    def record(self):
        return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}


def load_config(path):
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    required = {"paths": {"cache_dir", "output_dir", "calibration"}, "model": {"repo_id", "revision"},
                "hardware": {"follower_serial", "camera_index", "width", "height", "fps"},
                "inference": {"task", "samples", "warmup_runs", "noise_seed", "use_amp"}}
    if set(data) != set(required) or any(set(data[key]) != fields for key, fields in required.items()):
        raise ValueError("实时配置字段不完整或存在未知字段")
    values = {name: value for section in data.values() for name, value in section.items()}
    for key in required["paths"]:
        values[key] = (path.parent / values[key]).resolve()
    cfg = LiveConfig(**values)
    for key in ("samples", "width", "height", "fps"):
        if type(getattr(cfg, key)) is not int or getattr(cfg, key) <= 0:
            raise ValueError(f"{key} 必须是正整数")
    for key in ("warmup_runs", "noise_seed", "camera_index"):
        if type(getattr(cfg, key)) is not int or getattr(cfg, key) < 0:
            raise ValueError(f"{key} 必须是非负整数")
    if type(cfg.use_amp) is not bool or not cfg.task.strip() or not cfg.follower_serial.strip():
        raise ValueError("task、USB 序列号或 use_amp 无效")
    if cfg.repo_id != "lerobot/smolvla_base":
        raise ValueError("此入口当前只验收 smolvla_base；其他权重需单独验证状态／动作协议")
    return cfg


def configure_cache(cfg, *, offline=False):
    import os
    os.environ["HF_HOME"] = str(cfg.cache_dir / "hf")
    os.environ["HF_HUB_CACHE"] = str(cfg.cache_dir / "hub")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def import_weights(source, target, expected_size, expected_sha256):
    """边复制边校验；只有完整匹配上游固定版本的文件才替换正式权重。"""
    source, target = Path(source).resolve(), Path(target)
    if source.stat().st_size != expected_size:
        raise ValueError(f"权重大小不符，应为 {expected_size} 字节")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    temporary = None
    try:
        with source.open("rb") as reader, tempfile.NamedTemporaryFile(
                dir=target.parent, prefix="weights-", suffix=".partial", delete=False) as writer:
            temporary = Path(writer.name)
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
                writer.write(chunk)
        if digest.hexdigest() != expected_sha256 or temporary.stat().st_size != expected_size:
            raise ValueError("权重 SHA-256 不符；未替换模型文件")
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def prepare(cfg, *, weights=None):
    """只下载公开模型与 tokenizer；冻结两个 SHA，既不读相机，也不打开串口。"""
    configure_cache(cfg)
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    api = HfApi()
    model_info = api.model_info(cfg.repo_id, revision=cfg.revision, files_metadata=weights is not None)
    model_sha = model_info.sha
    print(f"Preparing {cfg.repo_id}@{model_sha}", flush=True)
    config_path = hf_hub_download(cfg.repo_id, "config.json", revision=model_sha, cache_dir=cfg.cache_dir / "hub")
    backbone_repo = json.loads(Path(config_path).read_text(encoding="utf-8"))["vlm_model_name"]
    backbone_sha = api.model_info(backbone_repo).sha
    # 完整 SmolVLA 权重已含 VLM；骨干只下载配置与 tokenizer，不重复下载骨干权重。
    backbone_path = snapshot_download(backbone_repo, revision=backbone_sha, cache_dir=cfg.cache_dir / "hub",
                                      allow_patterns=["*.json", "*.txt", "*.model", "*.jinja"], max_workers=2)
    model_patterns = ["config.json", "policy_*.json", "policy_*.safetensors"]
    if weights is not None:
        metadata = next(file for file in model_info.siblings if file.rfilename == "model.safetensors").lfs
        import_weights(weights, Path(config_path).parent / "model.safetensors", metadata.size, metadata.sha256)
        print("Local weights match upstream SHA-256", flush=True)
    else:
        model_patterns.append("model.safetensors")
    model_path = snapshot_download(cfg.repo_id, revision=model_sha, cache_dir=cfg.cache_dir / "hub",
                                   allow_patterns=model_patterns, max_workers=2)
    result = {"status": "prepared", "model_repo": cfg.repo_id, "requested_revision": cfg.revision,
              "model_sha": model_sha, "model_path": str(Path(model_path).resolve()),
              "backbone_repo": backbone_repo, "backbone_sha": backbone_sha,
              "backbone_path": str(Path(backbone_path).resolve())}
    write_json(cfg.assets_path, result)
    print(cfg.assets_path, flush=True)
    return result


def build_observation(frame_bgr, state, task):
    import torch
    if frame_bgr.dtype != np.uint8 or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
        raise ValueError("相机图像必须是 HWC uint8 BGR")
    state = np.asarray(state, dtype=np.float32)
    if state.shape != (6,) or not np.isfinite(state).all():
        raise ValueError("从臂状态必须是六维有限数值")
    rgb_chw = np.ascontiguousarray(frame_bgr[:, :, ::-1].transpose(2, 0, 1))
    return {IMAGE_KEY: torch.from_numpy(rgb_chw).float().div_(255),
            "observation.state": torch.from_numpy(state), "task": task}


def validate_prediction(action, chunk_size):
    if action.shape != (1, chunk_size, 6) or not np.isfinite(action).all():
        raise ValueError(f"预测动作形状或数值无效：{action.shape}")


def load_model(cfg):
    configure_cache(cfg, offline=True)
    from smolvla_common.runtime import require_runtime
    runtime = require_runtime()
    from lerobot.configs import FeatureType, PolicyFeature
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    assets = json.loads(cfg.assets_path.read_text(encoding="utf-8"))
    if (assets["status"] != "prepared" or assets["model_repo"] != cfg.repo_id
            or assets["requested_revision"] != cfg.revision):
        raise ValueError("模型准备记录与当前配置不一致，请重新 prepare")
    model_path, backbone_path = assets["model_path"], assets["backbone_path"]
    pc = SmolVLAConfig.from_pretrained(model_path, local_files_only=True)
    if (pc.input_features["observation.state"].shape != (6,) or pc.action_feature.shape != (6,)
            or pc.n_obs_steps != 1 or pc.adapt_to_pi_aloha or pc.use_delta_joint_actions_aloha):
        raise ValueError("只支持当前六轴、单时刻、无 ALOHA 转换的基础配置")
    # 只声明真实 wrist 输入。不会复制图像、补黑图或沿用公共双相机 dataset schema。
    pc.input_features = {"observation.state": pc.input_features["observation.state"],
                         IMAGE_KEY: PolicyFeature(type=FeatureType.VISUAL, shape=(3, cfg.height, cfg.width))}
    pc.device, pc.use_amp = "cuda", cfg.use_amp
    pc.empty_cameras = 0
    pc.vlm_model_name, pc.load_vlm_weights = backbone_path, False
    pc.pretrained_path, pc.push_to_hub = model_path, False
    pc.compile_model, pc.rtc_config = False, None
    print("Loading SmolVLA on CUDA (single wrist input)", flush=True)
    policy = SmolVLAPolicy.from_pretrained(model_path, config=pc, local_files_only=True, strict=True).eval()
    preprocessor, postprocessor = make_pre_post_processors(
        pc, pretrained_path=model_path,
        preprocessor_overrides={"device_processor": {"device": "cuda"},
                                "tokenizer_processor": {"tokenizer_name": backbone_path},
                                "rename_observations_processor": {"rename_map": {}},
                                "normalizer_processor": {"features": {**pc.input_features, **pc.output_features}}})
    # 保留权重自带统计；不从公共数据或本次实时输入重新拟合归一化参数。
    return policy, preprocessor, postprocessor, runtime, assets


def run(cfg, *, capture_only=False):
    import cv2
    folder = cfg.output_dir / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True)
    report = {"status": "running", "mode": "capture" if capture_only else "inference",
              "config": cfg.record(), "samples": 0, "robot_actions_sent": 0,
              "motor_register_writes": 0, "camera_inputs": [IMAGE_KEY],
              "limitations": ["仅基础模型单视角诊断，未验证抓放能力",
                              "本机标定归一化状态与预训练状态语义尚未验证一致",
                              "预测为模型处理器输出单位，不当作角度或可执行目标",
                              "相机时间戳为主机收帧时间；关节读取与曝光没有硬件同步",
                              "每次用最新观测生成独立动作块，没有执行动作队列"]}
    write_json(folder / "report.json", report)
    camera = LatestCamera(cfg.camera_index, cfg.width, cfg.height, cfg.fps)
    follower = None
    predictions, records = [], []
    try:
        # 先检查只读 SDK／标定文件与设备身份，再进行耗时的模型加载；此处未打开串口。
        follower = ReadOnlyFollower(cfg.follower_serial, cfg.calibration)
        if not capture_only:
            import torch
            from .engine import sample_noise
            start = time.perf_counter()
            policy, preprocessor, postprocessor, runtime, assets = load_model(cfg)
            report.update(runtime=runtime, assets=assets, model_load_ms=(time.perf_counter() - start) * 1000,
                          chunk_size=policy.config.chunk_size, flow_steps=policy.config.num_steps,
                          precision="autocast-float16" if cfg.use_amp else "autocast-disabled")
            policy.reset()  # 每次诊断开始时重置一次；直接 predict_action_chunk，不取缓存旧动作。
        follower.open()
        camera.open()
        report.update(follower=follower.metadata, camera=camera.metadata)
        write_json(folder / "report.json", report)
        sequence = 0

        def observe():
            nonlocal sequence
            begin = time.perf_counter()
            sequence, arrived, frame = camera.after(sequence)
            state = follower.read()
            end = time.perf_counter()
            if end - arrived > 1:
                raise RuntimeError("读取关节后图像已过期")
            return frame, state, {"frame_sequence": sequence, "frame_received_monotonic": arrived,
                                  "state_read_start_monotonic": state["read_start_monotonic"],
                                  "state_read_end_monotonic": state["read_end_monotonic"],
                                  "capture_ms": (end - begin) * 1000,
                                  "frame_age_at_input_ms": (end - arrived) * 1000}

        def predict(frame, state, sample):
            noise = sample_noise(policy.config, cfg.noise_seed, sample, "cuda")
            torch.cuda.synchronize()
            start = time.perf_counter()
            batch = preprocessor(build_observation(frame, state["state"], cfg.task))
            if set(key for key in batch if key.startswith("observation.images.")) != {IMAGE_KEY}:
                raise ValueError("预处理后不是唯一真实 wrist 图像")
            torch.cuda.synchronize()
            prepared = time.perf_counter()
            with torch.inference_mode(), torch.autocast("cuda", enabled=cfg.use_amp):
                action = policy.predict_action_chunk(batch, noise=noise)
            torch.cuda.synchronize()
            predicted = time.perf_counter()
            normalized = action.detach().cpu().numpy()
            output = postprocessor(action).detach().cpu().numpy()
            ended = time.perf_counter()
            validate_prediction(output, policy.config.chunk_size)
            validate_prediction(normalized, policy.config.chunk_size)
            return output, normalized, {"preprocess_ms": (prepared - start) * 1000,
                                        "inference_ms": (predicted - prepared) * 1000,
                                        "postprocess_ms": (ended - predicted) * 1000}

        if not capture_only:
            for warmup in range(cfg.warmup_runs):
                frame, state, _ = observe()
                predict(frame, state, cfg.samples + warmup)
                print(f"Warmup {warmup + 1}/{cfg.warmup_runs}", flush=True)
            torch.cuda.reset_peak_memory_stats()
        with (folder / "samples.jsonl").open("w", encoding="utf-8", buffering=1) as log:
            for sample in range(cfg.samples):
                begin = time.perf_counter()
                frame, state, timing = observe()
                if sample == 0 and not cv2.imwrite(str(folder / "first-frame.jpg"), frame):
                    raise OSError("无法保存首帧")
                row = {"sample": sample, "timestamp": datetime.now().astimezone().isoformat(),
                       "raw": state["raw"], "state": state["state"], "state_warnings": state["warnings"],
                       "task": cfg.task, **timing}
                if not capture_only:
                    output, normalized, timing = predict(frame, state, sample)
                    predictions.append(output[0])
                    # 每块立即保存，中断时已生成动作也可回读。
                    np.savez_compressed(folder / f"chunk-{sample:04d}.npz", predicted=output[0],
                                        normalized=normalized[0], state=np.asarray(state["state"]),
                                        frame_sequence=sequence)
                    row.update(timing, first_action=output[0, 0].tolist())
                row["end_to_end_ms"] = (time.perf_counter() - begin) * 1000
                log.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                records.append(row)
                report["samples"] = len(records)
                write_json(folder / "report.json", report)
                print(f"Sample {sample + 1}/{cfg.samples}: total={row['end_to_end_ms']:.1f}ms"
                      + (f", model={row['inference_ms']:.1f}ms, first={row['first_action']}"
                         if not capture_only else f", state={row['state']}")
                      + (f", calibration warnings={list(state['warnings'])}" if state["warnings"] else ""), flush=True)
        if predictions:
            np.savez_compressed(folder / "actions.npz", predicted=np.stack(predictions),
                                state=np.asarray([r["state"] for r in records]),
                                frame_sequence=np.asarray([r["frame_sequence"] for r in records]))
            report.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                          peak_reserved_bytes=torch.cuda.max_memory_reserved())
        timing_keys = [key for key in records[0] if key.endswith("_ms")]
        report.update(status="completed", latency={key: latency_summary([r[key] for r in records]) for key in timing_keys},
                      samples_with_state_warnings=sum(bool(r["state_warnings"]) for r in records))
        if len(records) > 1:
            camera_elapsed = records[-1]["frame_received_monotonic"] - records[0]["frame_received_monotonic"]
            if camera_elapsed > 0:
                report["camera"]["measured_read_fps"] = (
                    records[-1]["frame_sequence"] - records[0]["frame_sequence"]) / camera_elapsed
    except BaseException as error:
        report.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error=str(error))
        raise
    finally:
        camera.close()
        try:
            if follower is not None:
                follower.close()
        finally:
            write_json(folder / "report.json", report)
            print(f"Report: {folder / 'report.json'}", flush=True)
    return folder / "report.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="配置与输入协议，不联网或接触硬件")
    preparation = commands.add_parser("prepare", help="下载基础权重及骨干配置／tokenizer，冻结 SHA")
    preparation.add_argument("--weights", type=Path, help="可选的手动下载权重，校验固定版本大小和 SHA-256")
    for name in ("capture", "infer"):
        command = commands.add_parser(name, help="只读观测" if name == "capture" else "实时动作块诊断，仅写文件")
        command.add_argument("--samples", type=int)
        command.add_argument("--task", help="本次输入的任务指令")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command == "plan":
            print(json.dumps({**cfg.record(), "input_image": IMAGE_KEY, "joint_order": list(JOINTS),
                              "actions_sent": 0, "state_space": "5x[-100,100] + gripper[0,100]"}, ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            prepare(cfg, weights=args.weights)
        else:
            if args.samples is not None:
                if args.samples <= 0:
                    raise ValueError("--samples 必须大于零")
                cfg = replace(cfg, samples=args.samples)
            if args.task is not None:
                if not args.task.strip():
                    raise ValueError("任务指令不能为空")
                cfg = replace(cfg, task=args.task)
            run(cfg, capture_only=args.command == "capture")
    except (ValueError, RuntimeError, OSError, ImportError, KeyError) as error:
        parser.exit(1, f"实时诊断停止：{error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "实时诊断已停止，资源已关闭\n")


if __name__ == "__main__":
    main()
