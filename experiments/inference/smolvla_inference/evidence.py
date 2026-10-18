"""Summarize recorded control ticks and export timestamp-corrected H.264 trial clips."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(folder):
    import numpy as np
    from .live_hardware import JOINTS
    events = read_rows(folder / "operations.jsonl")
    frames = read_rows(folder / "frames.jsonl")
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    calibration = report.get("hardware", {}).get("calibration")
    if calibration is None:
        path = Path(report["config"]["calibration"])
        expected = report["hardware"]["calibration_sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("calibration changed since recording; a matching snapshot is required")
        calibration = json.loads(path.read_text(encoding="utf-8"))
    trials, current = [], None
    for event in events:
        if event["event"] == "llm_decision" and event["operation"] == "start_task":
            current = {"start_monotonic": event["monotonic"], "arguments": event["arguments"], "ticks": []}
        elif event["event"] == "control_tick" and current is not None:
            current["ticks"].append(event)
        elif event["event"] == "job_finished" and current is not None and event["job"]["operation"] == "start_task":
            current.update(job=event["job"], end_monotonic=event["monotonic"])
            trials.append(current)
            current = None
    summary = {"folder": str(folder), "frames": len(frames), "trials": [],
               "video_time_note": "camera.avi uses nominal 30fps; exported clips use per-frame measured timestamps"}
    if len(frames) > 1:
        summary["measured_camera_fps"] = (len(frames) - 1) / (frames[-1]["received_monotonic"] - frames[0]["received_monotonic"])
    for number, trial in enumerate(trials, 1):
        ticks, job = trial["ticks"], trial["job"]
        result = {"number": number, "job_id": job["id"], "state": job["state"],
                  "arguments": trial["arguments"], "control_ticks": len(ticks),
                  "start_monotonic": trial["start_monotonic"], "end_monotonic": trial["end_monotonic"],
                  "axes": {}}
        if ticks:
            times = np.array([t["monotonic"] for t in ticks])
            if len(times) > 1:
                intervals = np.diff(times) * 1000
                result["control_interval_ms"] = {"p50": float(np.median(intervals)),
                                                  "p95": float(np.percentile(intervals, 95)), "max": float(max(intervals))}
            for joint in JOINTS:
                scale = 360 / 4095 if joint != "gripper" else 100 / (calibration[joint]["range_max"] - calibration[joint]["range_min"])
                measured = np.array([t["observation"]["raw"][joint] for t in ticks])
                command = np.array([t["commanded_raw"][joint] for t in ticks])
                old_goal = np.array([t["observation"]["telemetry"][joint]["goal_raw"] for t in ticks])
                result["axes"][joint] = {"unit": "encoder_degrees" if joint != "gripper" else "calibrated_gripper_units",
                                         "measured_min_raw": int(min(measured)), "measured_max_raw": int(max(measured)),
                                         "measured_span": float(np.ptp(measured) * scale),
                                         "command_span": float(np.ptp(command) * scale),
                                         "tracking_error_max": float(max(abs(measured - old_goal)) * scale)}
            result["maximum_temperature_c"] = max(t["observation"]["telemetry"][j]["temperature_c"] for t in ticks for j in JOINTS)
            data_path = folder / f"trial-{number}-trajectory.csv"
            with data_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["time_s", "command_wrist_deg", "measured_wrist_deg"])
                origin = job.get("result", {}).get("before", ticks[0]["observation"])["raw"]["wrist_flex"]
                for tick in ticks:
                    writer.writerow([tick["monotonic"] - trial["start_monotonic"],
                                     (tick["commanded_raw"]["wrist_flex"] - origin) * 360 / 4095,
                                     (tick["observation"]["raw"]["wrist_flex"] - origin) * 360 / 4095])
            result["trajectory_csv"] = str(data_path)
            result["immediate_return_error_deg"] = job.get("result", {}).get("wrist_return_error_deg")
        summary["trials"].append(result)
    (folder / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, frames


def export_clip(folder, trial, frames, ffmpeg):
    import cv2
    start, end = trial["start_monotonic"] - 1, trial["end_monotonic"] + 1
    chosen = [f for f in frames if start <= f["received_monotonic"] <= end]
    if len(chosen) < 2:
        raise ValueError("insufficient recorded frames around trial")
    output = folder / f"trial-{trial['number']}.mp4"
    capture = cv2.VideoCapture(str(folder / "camera.avi"))
    if not capture.isOpened():
        raise RuntimeError("could not decode recorded AVI")
    if int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != len(frames):
        raise RuntimeError("AVI frame count differs from timestamp log")
    try:
        # Every temporary path is freshly created inside the explicitly requested session directory.
        with tempfile.TemporaryDirectory(prefix=".clip-", dir=folder) as temporary:
            temp = Path(temporary).resolve()
            if not temp.is_relative_to(folder.resolve()):
                raise RuntimeError("temporary path escaped session directory")
            capture.set(cv2.CAP_PROP_POS_FRAMES, chosen[0]["video_frame"])
            manifest = ["ffconcat version 1.0"]
            for index, row in enumerate(chosen):
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("video decode failed")
                relative = row["received_monotonic"] - trial["start_monotonic"]
                cv2.rectangle(frame, (0, 0), (640, 54), (25, 25, 25), -1)
                cv2.putText(frame, "WRIST NOD: deterministic controller; VLA disabled", (8, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, .49, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(frame, f"Measured camera time: {relative:+.3f} s", (8, 43),
                            cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1, cv2.LINE_AA)
                name = f"frame-{index:04d}.png"
                if not cv2.imwrite(str(temp / name), frame):
                    raise OSError("could not write video export frame")
                following = frames[row["video_frame"] + 1] if row["video_frame"] + 1 < len(frames) else None
                duration = following["received_monotonic"] - row["received_monotonic"] if following else 1 / 30
                if duration <= 0:
                    raise ValueError("camera timestamps are not strictly increasing")
                manifest.extend([f"file '{name}'", "option framerate 1000", f"duration {duration:.9f}"])
            manifest.extend([f"file '{name}'", "option framerate 1000"])
            listing = temp / "frames.ffconcat"
            listing.write_text("\n".join(manifest) + "\n", encoding="utf-8")
            subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(listing), "-fps_mode", "vfr", "-c:v", "libx264", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], check=True)
    finally:
        capture.release()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    summary, frames = summarize(folder)
    if args.ffmpeg:
        for trial in summary["trials"]:
            if trial["control_ticks"]:
                print(export_clip(folder, trial, frames, args.ffmpeg.resolve()))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
