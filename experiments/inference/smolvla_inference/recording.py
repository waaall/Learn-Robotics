"""Continuous camera recording with per-frame monotonic timestamps and explicit failures."""

import json
from pathlib import Path
import threading
import time


class VideoRecorder:
    def __init__(self, camera, folder, fps, event):
        self.camera, self.folder, self.fps, self.event = camera, Path(folder), fps, event
        self.stop = threading.Event()
        self.error = None
        self.frames = 0
        self.thread = None

    def open(self):
        import cv2
        _, _, frame = self.camera.after(0)
        height, width = frame.shape[:2]
        self.writer = cv2.VideoWriter(str(self.folder / "camera.avi"),
                                      cv2.VideoWriter_fourcc(*"MJPG"), self.fps, (width, height))
        if not self.writer.isOpened():
            raise RuntimeError("could not open video writer")
        self.log = (self.folder / "frames.jsonl").open("w", encoding="utf-8", buffering=1)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        sequence = 0
        try:
            while not self.stop.is_set():
                sequence, arrived, frame = self.camera.after(sequence)
                self.writer.write(frame)
                self.log.write(json.dumps({"video_frame": self.frames, "camera_sequence": sequence,
                                           "received_monotonic": arrived,
                                           "written_monotonic": time.perf_counter()}) + "\n")
                self.frames += 1
        except Exception as error:
            if not self.stop.is_set():
                self.error = str(error)
                self.event("recording_failed", error=self.error)

    def check(self):
        if self.error or self.thread is None or not self.thread.is_alive() or self.frames == 0:
            raise RuntimeError(f"camera recording unavailable: {self.error}")

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=6)
            if self.thread.is_alive():
                raise RuntimeError("recording thread did not stop")
        self.writer.release()
        self.log.close()
        self.event("recording_closed", frames=self.frames, nominal_fps=self.fps,
                   timing="AVI uses constant fps; frames.jsonl is the measured timeline")
