"""Hardware-free checks. Synthetic observations are NOT robot training data."""

import importlib.metadata as metadata
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import av
import numpy as np
import torch

from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.datasets.video_utils import VideoDecoderCache, decode_video_frames, decode_video_frames_torchcodec
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig


def main():
    assert (3, 12) <= sys.version_info[:2] < (3, 14), sys.version
    assert torch.cuda.is_available(), "CUDA unavailable; this check requires the NVIDIA GPU"
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {name: metadata.version(name) for name in
                     ("lerobot", "torch", "torchvision", "torchcodec", "av", "numpy", "feetech-servo-sdk")},
        "gpu": torch.cuda.get_device_name(0),
        "cuda": torch.version.cuda,
        "seed": 42,
        "hardware_connected": False,
    }
    # Import checks only. Never instantiate/connect a robot or open a serial port.
    assert SO101Follower and SO101FollowerConfig
    print("CUDA and robot imports passed", flush=True)
    for command in ("lerobot-calibrate", "lerobot-teleoperate", "lerobot-record", "lerobot-train"):
        result = subprocess.run([str(Path(sys.executable).parent / f"{command}.exe"), "--help"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if result.returncode:
            raise RuntimeError(f"{command} --help failed:\n{result.stderr[-4000:]}")
        print(f"{command} --help passed", flush=True)
    report["cli_help"] = "passed"
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "synthetic.mp4"
        with av.open(str(video), "w") as container:
            stream = container.add_stream("libx264", rate=10)
            stream.width = stream.height = 64
            stream.pix_fmt = "yuv420p"
            for i in range(10):
                frame = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i * 20, dtype=np.uint8), format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        decoder_cache = VideoDecoderCache()
        try:
            for backend in ("pyav", "torchcodec"):
                if backend == "torchcodec":
                    frames = decode_video_frames_torchcodec(video, [0.0, 0.5, 0.9],
                                                           tolerance_s=0.06, decoder_cache=decoder_cache)
                else:
                    frames = decode_video_frames(video, [0.0, 0.5, 0.9], tolerance_s=0.06, backend=backend)
                assert frames.shape == (3, 3, 64, 64), frames.shape
                means = frames.mean(dim=(1, 2, 3))
                assert means[0] < means[1] < means[2], means
                report[f"video_{backend}"] = "passed"
                print(f"Video {backend} passed", flush=True)
        finally:
            # Release cached open handles before TemporaryDirectory removes the Windows file.
            decoder_cache.clear()
        # Small ACT configuration: exercise vision, CUDA backward, update and checkpoint reload.
        config = ACTConfig(
            device="cuda", pretrained_backbone_weights=None,
            input_features={
                "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(6,)),
                "observation.images.front": PolicyFeature(type=FeatureType.VISUAL, shape=(3, 64, 64)),
            },
            output_features={"action": PolicyFeature(type=FeatureType.ACTION, shape=(6,))},
            chunk_size=4, n_action_steps=4, dim_model=64, n_heads=4,
            dim_feedforward=128, n_encoder_layers=1, n_decoder_layers=1,
            n_vae_encoder_layers=1, latent_dim=8,
        )
        policy = ACTPolicy(config).cuda().train()
        batch = {
            "observation.state": torch.rand(2, 6, device="cuda"),
            "observation.images.front": torch.rand(2, 3, 64, 64, device="cuda"),
            "action": torch.rand(2, 4, 6, device="cuda"),
            "action_is_pad": torch.zeros(2, 4, dtype=torch.bool, device="cuda"),
        }
        optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-4)
        before = next(policy.parameters()).detach().clone()
        loss, _ = policy(batch)
        assert torch.isfinite(loss), loss
        loss.backward()
        assert all(torch.isfinite(p.grad).all() for p in policy.parameters() if p.grad is not None)
        optimizer.step()
        assert not torch.equal(before, next(policy.parameters()).detach()), "No parameter update"
        policy.eval()
        obs = {key: value for key, value in batch.items() if key.startswith("observation.")}
        policy.reset()
        expected = policy.select_action(obs)
        checkpoint = Path(tmp) / "act"
        policy.save_pretrained(checkpoint)
        restored = ACTPolicy.from_pretrained(checkpoint).cuda().eval()
        restored.reset()
        actual = restored.select_action(obs)
        torch.testing.assert_close(actual, expected)
        assert actual.shape == (2, 6)
        report["act_synthetic_step"] = "passed"
        report["act_loss"] = float(loss.detach())
        report["checkpoint_reload"] = "passed"
    report["limitations"] = "Synthetic reduced ACT only; no real dataset, camera, robot or Python 3.13 validation."
    output = Path(__file__).parent / "outputs" / "environment-check.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
