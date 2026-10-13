"""SO-101 只读观测；不构造 Robot，不 configure，不写舵机寄存器。"""

import hashlib
import json
from pathlib import Path
import threading
import time

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def load_calibration(path):
    from lerobot.motors import MotorCalibration
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(data) != set(JOINTS):
        raise ValueError("从臂标定必须包含完整六轴")
    result = {joint: MotorCalibration(**data[joint]) for joint in JOINTS}
    for motor_id, joint in enumerate(JOINTS, 1):
        c = result[joint]
        if c.id != motor_id or c.drive_mode not in (0, 1) or not 0 <= c.range_min < c.range_max <= 4095:
            raise ValueError(f"{joint}: 标定 ID、方向或编码器范围无效")
    return result


def validate_raw(raw, calibration):
    """硬件编码器越界停止；机械标定范围外的只读输入明确记录其裁剪。"""
    warnings = {}
    for joint in JOINTS:
        value = raw[joint]
        if not 0 <= value <= 4095:
            raise ValueError(f"{joint}: 编码器值 {value} 不在 0..4095，停止诊断")
        c = calibration[joint]
        if not c.range_min <= value <= c.range_max:
            warnings[joint] = {"raw": value, "range": [c.range_min, c.range_max],
                               "input_clipped": True}
    return warnings


class ReadOnlyFollower:
    def __init__(self, serial_number, calibration_path):
        from serial.tools import list_ports
        from lerobot.motors import Motor, MotorNormMode
        from lerobot.motors.feetech import FeetechMotorsBus
        ports = [p.device for p in list_ports.comports() if p.serial_number == serial_number]
        if len(ports) != 1:
            raise RuntimeError(f"从臂 USB 序列号 {serial_number} 匹配到 {len(ports)} 个端口")
        self.calibration = load_calibration(calibration_path)
        self.bus = FeetechMotorsBus(ports[0], {
            joint: Motor(i, "sts3215", MotorNormMode.RANGE_0_100 if joint == "gripper"
                         else MotorNormMode.RANGE_M100_100)
            for i, joint in enumerate(JOINTS, 1)
        }, calibration=self.calibration)
        self.metadata = {"port": ports[0], "serial": serial_number, "joint_order": list(JOINTS),
                         "calibration_sha256": hashlib.sha256(Path(calibration_path).read_bytes()).hexdigest(),
                         "state_units": ["range_-100_100"] * 5 + ["range_0_100"],
                         "motor_register_writes": 0}

    def open(self):
        try:
            # FeetechMotorsBus.connect() only opens the host port, pings and reads firmware.
            self.bus.connect()
            actual = self.bus.read_calibration()
            for joint in JOINTS:
                expected, found = self.calibration[joint], actual[joint]
                if any(getattr(expected, key) != getattr(found, key)
                       for key in ("range_min", "range_max", "homing_offset")):
                    raise ValueError(f"{joint}: 文件标定与舵机标定不同；不会自动回写")
                if self.bus.read("Operating_Mode", joint, normalize=False) != 0:
                    raise ValueError(f"{joint}: 不是位置模式")
            self.read()
        except BaseException:
            self.close()
            raise

    def read(self):
        start = time.perf_counter()
        raw = {}
        for joint in JOINTS:
            # Preserve SDK packet errors via acknowledged per-motor read, rather than sync read.
            if self.bus.read("Torque_Enable", joint, normalize=False, num_retry=2) != 0:
                raise RuntimeError(f"{joint}: 力矩已开启，请先停止其他控制器")
            raw[joint] = self.bus.read("Present_Position", joint, normalize=False, num_retry=2)
        warnings = validate_raw(raw, self.calibration)
        values = self.bus._normalize({i: raw[joint] for i, joint in enumerate(JOINTS, 1)})
        return {"raw": raw, "state": [values[i] for i in range(1, 7)], "warnings": warnings,
                "read_start_monotonic": start, "read_end_monotonic": time.perf_counter()}

    def close(self):
        # Default bus.disconnect() writes Torque_Enable. Explicitly opt out.
        if self.bus.is_connected:
            self.bus.disconnect(disable_torque=False)


class LatestCamera:
    """持续取帧，只保留最新帧；时间戳为主机收帧时间，不是传感器曝光时间。"""
    def __init__(self, index, width, height, fps):
        self.options = index, width, height, fps
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.latest = None
        self.error = None
        self.metadata = {}
        self.thread = None

    def open(self):
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()
        self.after(0)

    def _capture(self):
        import cv2
        camera = None
        try:
            index, width, height, fps = self.options
            camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not camera.isOpened():
                raise RuntimeError(f"无法打开 DirectShow 相机 {index}")
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUY2"))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            camera.set(cv2.CAP_PROP_FPS, fps)
            self.metadata = {"index": index, "backend": "DSHOW", "requested_fps": fps,
                             "reported_fps": camera.get(cv2.CAP_PROP_FPS),
                             "width": int(camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
                             "height": int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))}
            sequence = 0
            while not self.stop.is_set():
                ok, frame = camera.read()
                arrived = time.perf_counter()
                if not ok or frame is None or frame.shape != (height, width, 3):
                    raise RuntimeError("相机取帧失败或实际尺寸不符合配置")
                sequence += 1
                with self.condition:
                    self.latest = sequence, arrived, frame
                    self.condition.notify_all()
        except Exception as error:
            with self.condition:
                self.error = str(error)
                self.condition.notify_all()
        finally:
            if camera is not None:
                camera.release()

    def after(self, sequence, timeout=5):
        with self.condition:
            ready = self.condition.wait_for(
                lambda: self.error or (self.latest is not None and self.latest[0] > sequence), timeout)
            if self.error:
                raise RuntimeError(self.error)
            if not ready:
                raise RuntimeError("等待新相机帧超时")
            number, arrived, frame = self.latest
            if time.perf_counter() - arrived > 1:
                raise RuntimeError("相机最新帧已经过期")
            return number, arrived, frame.copy()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
