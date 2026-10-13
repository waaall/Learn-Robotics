"""Live USB camera preview using OpenCV capture and Tkinter display; no robot access."""
import argparse
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk


class CameraPreview:
    def __init__(self, args):
        self.args = args
        self.output = Path(__file__).resolve().parent / "outputs/camera-preview"
        self.output.mkdir(parents=True, exist_ok=True)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.frame = None
        self.frame_number = 0
        self.arrivals = deque(maxlen=120)
        self.negotiated = {}
        self.error = None
        self.started = time.monotonic()
        self.last_report = 0.0
        self.last_displayed = 0
        self.closing = False

        self.root = tk.Tk()
        self.root.title("SO-101 夹爪相机实时预览")
        self.root.geometry(f"{args.width + 32}x{args.height + 120}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<s>", lambda _event: self.save_frame())
        self.root.bind("<S>", lambda _event: self.save_frame())

        self.image_label = ttk.Label(self.root, text="正在打开相机……", anchor="center")
        self.image_label.pack(fill="both", expand=True, padx=8, pady=8)
        self.status = tk.StringVar(value="相机 0 | DirectShow | 正在连接")
        ttk.Label(self.root, textvariable=self.status).pack(padx=8, pady=4)
        controls = ttk.Frame(self.root)
        controls.pack(fill="x", padx=8, pady=8)
        ttk.Button(controls, text="保存当前画面 (S)", command=self.save_frame).pack(side="left")
        ttk.Button(controls, text="关闭 (Esc)", command=self.close).pack(side="right")
        self.notice = tk.StringVar(value="仅预览相机。窗口显示取帧实测 FPS。")
        ttk.Label(controls, textvariable=self.notice).pack(side="left", padx=12)
        self.worker = threading.Thread(target=self.capture, name="camera-capture", daemon=True)

    def capture(self):
        camera = None
        try:
            cv2.setNumThreads(1)
            camera = cv2.VideoCapture(self.args.index, cv2.CAP_DSHOW)
            if not camera.isOpened():
                raise RuntimeError("相机无法打开，请关闭其他占用相机的程序并确认相机编号。")
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUY2"))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.height)
            camera.set(cv2.CAP_PROP_FPS, self.args.fps)
            negotiated = {
                "backend": camera.getBackendName(),
                "width": camera.get(cv2.CAP_PROP_FRAME_WIDTH),
                "height": camera.get(cv2.CAP_PROP_FRAME_HEIGHT),
                "fps": camera.get(cv2.CAP_PROP_FPS),
            }
            with self.lock:
                self.negotiated = negotiated
            while not self.stop.is_set():
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError("相机取帧失败，请检查 USB 连接或设备占用。")
                with self.lock:
                    self.frame = frame
                    self.frame_number += 1
                    self.arrivals.append(time.monotonic())
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            if camera is not None:
                camera.release()

    def report(self, status, fps, number):
        record = {
            "timestamp": datetime.now().astimezone().isoformat(), "status": status,
            "camera_index": self.args.index, "robot_access": False,
            "frames_captured": number, "frames_displayed": self.last_displayed,
            "measured_read_fps": fps, "negotiated": self.negotiated, "error": self.error,
        }
        destination = self.output / "status.json"
        temporary = destination.with_suffix(".partial")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)

    def refresh(self):
        if self.closing:
            return
        with self.lock:
            frame, number = self.frame, self.frame_number
            times, error = list(self.arrivals), self.error
        fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0
        if frame is not None and number != self.last_displayed:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.image_label.configure(image=photo, text="")
            self.image_label.image = photo
            if self.last_displayed == 0:
                cv2.imwrite(str(self.output / "first-frame.jpg"), frame)
                print("READY: live camera frames displayed in Tk window", flush=True)
            self.last_displayed = number
            self.status.set(f"相机 {self.args.index} | DirectShow | {frame.shape[1]}×{frame.shape[0]}"
                            f" | 实测 {fps:.1f} FPS | 请求 {self.args.fps:g} FPS")
        if error:
            self.status.set(f"错误：{error}")
            self.notice.set("请检查连接，关闭窗口后可重新运行。")
        now = time.monotonic()
        if now - self.last_report >= 1:
            self.report("error" if error else "streaming" if frame is not None else "connecting", fps, number)
            self.last_report = now
        if self.args.seconds and now - self.started >= self.args.seconds:
            self.close()
            return
        self.root.after(25, self.refresh)

    def save_frame(self):
        with self.lock:
            frame = self.frame
        if frame is None:
            self.notice.set("暂时没有可保存的画面。")
            return
        filename = "wrist-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".jpg"
        if cv2.imwrite(str(self.output / filename), frame):
            self.notice.set(f"已保存：{filename}")
        else:
            self.notice.set("保存失败，请检查输出目录。")

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.stop.set()
        self.worker.join(timeout=2)
        self.report("closed", 0.0, self.frame_number)
        self.root.destroy()

    def run(self):
        self.worker.start()
        self.root.after(25, self.refresh)
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=0, help="DirectShow camera index")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--seconds", type=float, default=0, help="Auto-close after this duration; 0 keeps the window open")
    args = parser.parse_args()
    if args.index < 0 or args.width <= 0 or args.height <= 0 or not 0 < args.fps <= 120 or args.seconds < 0:
        parser.error("Invalid camera index, dimensions, FPS or duration")
    CameraPreview(args).run()


if __name__ == "__main__":
    main()
