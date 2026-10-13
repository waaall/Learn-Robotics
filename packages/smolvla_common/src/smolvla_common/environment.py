"""学习项目的独立软件预检：CUDA、基础数值与视频解码，不导入机器人或下载模型。"""

import argparse
from pathlib import Path
import tempfile

from .protocol import write_json
from .runtime import require_runtime


def check(output: Path, *, training=False):
    write_json(output, {"status": "running", "hardware_connected": False})
    try:
        runtime = require_runtime()
        import av
        import numpy as np
        import torch
        import torchvision
        from lerobot.datasets.video_utils import VideoDecoderCache, decode_video_frames, decode_video_frames_torchcodec

        torch.manual_seed(42)
        torch.cuda.manual_seed_all(42)
        # 这里只验证基础 CUDA 数值／更新链路，不把小矩阵冒充真实 SmolVLA。
        matrix = torch.randn(8, 8, device="cuda", requires_grad=training)
        if training:
            optimizer = torch.optim.SGD([matrix], lr=0.01)
            before = matrix.detach().clone()
            loss = (matrix @ matrix.T).square().mean()
            if not bool(torch.isfinite(loss)):
                raise RuntimeError("CUDA 数值非有限")
            loss.backward()
            if not bool(matrix.grad.isfinite().all()):
                raise RuntimeError("CUDA 梯度非有限")
            optimizer.step()
            if torch.equal(before, matrix.detach()):
                raise RuntimeError("CUDA 参数未更新")
        else:
            with torch.inference_mode():
                if not bool((matrix @ matrix.T).isfinite().all()):
                    raise RuntimeError("CUDA 推理数值非有限")
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "synthetic.mp4"
            with av.open(str(video), "w") as container:
                stream = container.add_stream("libx264", rate=10)
                stream.width = stream.height = 64
                stream.pix_fmt = "yuv420p"
                for index in range(10):
                    frame = av.VideoFrame.from_ndarray(np.full((64, 64, 3), index * 20, dtype=np.uint8), format="rgb24")
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            cache = VideoDecoderCache()
            try:
                for backend in ("pyav", "torchcodec"):
                    frames = (decode_video_frames(video, [0.0, 0.5, 0.9], tolerance_s=0.06, backend=backend)
                              if backend == "pyav" else
                              decode_video_frames_torchcodec(video, [0.0, 0.5, 0.9], tolerance_s=0.06, decoder_cache=cache))
                    if tuple(frames.shape) != (3, 3, 64, 64) or not bool(frames.isfinite().all()):
                        raise RuntimeError(f"{backend} 解码结果无效")
                    means = frames.mean(dim=(1, 2, 3))
                    if not bool(means[0] < means[1] < means[2]):
                        raise RuntimeError(f"{backend} 时间戳／内容检查失败")
            finally:
                cache.clear()
        report = {"status": "completed", "role": "training" if training else "inference",
                  "runtime": runtime, "cuda_numeric_check": "passed", "video_check": "passed",
                  "hardware_connected": False, "smolvla_model_verified": False,
                  "limitations": "基础矩阵和合成视频预检；不代表真实 SmolVLA 前向、训练或任务验收"}
        write_json(output, report)
        return report
    except BaseException as error:
        write_json(output, {"status": "failed", "error": str(error), "hardware_connected": False})
        raise


def main(project_dir: Path, *, training=False):
    parser = argparse.ArgumentParser(description="学习项目的软件预检，不连接机器人或下载模型")
    parser.add_argument("--output", type=Path, default=project_dir / "outputs/environment-check.json")
    args = parser.parse_args()
    try:
        print(check(args.output.resolve(), training=training))
    except (ValueError, RuntimeError, OSError, ImportError) as error:
        parser.exit(1, f"环境验收停止：{error}\n")
