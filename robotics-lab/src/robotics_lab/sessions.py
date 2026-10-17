"""管理一个官方查看器子进程；数值验证运行不复用该会话状态。"""

from dataclasses import dataclass
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from .catalog import get_experiment
from .diagnostics import viewer_capability


@dataclass
class Session:
    id: str
    experiment_id: str
    port: int
    process: subprocess.Popen
    started: float
    log_path: Path
    ready: bool = False


class SessionManager:
    def __init__(self, directory: Path):
        self.directory = directory
        self.session: Session | None = None
        self.lock = threading.RLock()

    def start(self, experiment_id: str) -> dict:
        with self.lock:
            get_experiment(experiment_id)
            check = viewer_capability()
            if not check["available"]:
                raise RuntimeError(check["reason"])
            if self.session and self.session.process.poll() is None:
                raise ValueError("已有仿真会话，请先关闭当前会话")
            self.directory.mkdir(parents=True, exist_ok=True)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            identifier = str(uuid4())
            log_path = self.directory / f"{identifier}.log"
            command = [sys.executable, "-m", "robotics_lab.viewer", "--experiment", experiment_id, "--port", str(port)]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            with log_path.open("wb") as log:
                process = subprocess.Popen(command, stdout=log, stderr=log, creationflags=flags)
            self.session = Session(identifier, experiment_id, port, process, time.monotonic(), log_path)
            return self.status()

    def status(self) -> dict | None:
        with self.lock:
            session = self.session
            if not session:
                return None
            code = session.process.poll()
            status, error = "starting", None
            if code is not None:
                status = "stopped" if code == 0 else "failed"
                if code:
                    log = session.log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                    error = f"查看器进程退出（状态码 {code}）\n{log}"
            elif session.ready:
                status = "ready"
            else:
                try:
                    with urlopen(f"http://127.0.0.1:{session.port}/", timeout=0.5) as response:
                        if response.status == 200:
                            session.ready = True
                            status = "ready"
                except (URLError, TimeoutError, OSError):
                    if time.monotonic() - session.started > 45:
                        status, error = "failed", "查看器启动超时；请检查会话日志与运行组件。"
                        self._terminate(session)
                        code = session.process.poll()
            return {"id": session.id, "experiment_id": session.experiment_id, "port": session.port,
                    "status": status, "error": error, "exit_code": code}

    @staticmethod
    def _terminate(session: Session) -> None:
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                session.process.kill()
                session.process.wait(timeout=3)

    def stop(self) -> None:
        with self.lock:
            if self.session:
                self._terminate(self.session)
                self.session = None
