"""管理一个官方查看器子进程；数值验证运行不复用该会话状态。"""

from dataclasses import dataclass
import json
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
from .config import VIEWER_URL


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
        self._state_cache: dict | None = None

    def start(self, experiment_id: str) -> dict:
        with self.lock:
            experiment_id = get_experiment(experiment_id).id
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
            command += ["--bridge", str(log_path.with_suffix(""))]
            with log_path.open("wb") as log:
                process = subprocess.Popen(command, stdout=log, stderr=log)
            self.session = Session(identifier, experiment_id, port, process, time.monotonic(), log_path)
            self._state_cache = None
            return self.status()

    def active_port(self) -> int | None:
        """代理只读取当前存活进程的内部端口，不在事件循环中执行就绪探测。"""
        with self.lock:
            if self.session and self.session.process.poll() is None:
                return self.session.port
            return None

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
                    # 官方服务先监听，再发布模型并重建服务。仅 HTTP 首页可读时
                    # 尚未完成初始化；模型字节就绪后才允许浏览器开始资源加载。
                    with urlopen(f"http://127.0.0.1:{session.port}/model?total_bytes", timeout=0.5) as response:
                        size = json.loads(response.read()).get("total_bytes", 0)
                        if response.status == 200 and isinstance(size, int) and size > 0:
                            session.ready = True
                            status = "ready"
                except (URLError, TimeoutError, OSError, json.JSONDecodeError):
                    pass
                if not session.ready and time.monotonic() - session.started > 45:
                    status, error = "failed", "查看器启动超时；请检查会话日志与运行组件。"
                    self._terminate(session)
                    code = session.process.poll()
            return {"id": session.id, "experiment_id": session.experiment_id,
                    "url": VIEWER_URL, "status": status, "error": error, "exit_code": code}

    @staticmethod
    def _terminate(session: Session) -> None:
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                session.process.kill()
                session.process.wait(timeout=3)

    def state(self) -> dict | None:
        with self.lock:
            session = self.session
            if not session or session.process.poll() is not None:
                return None
            path = session.log_path.with_suffix(".state.json")
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                self._state_cache = state.copy()
            except (OSError, json.JSONDecodeError):
                # WSL 挂载目录在替换文件时可能暂时不可读，保留最近一次有效观测及其时间。
                if self._state_cache is None:
                    return None
                state = self._state_cache.copy()
            state.update(session_id=session.id, experiment_id=session.experiment_id,
                         age_seconds=max(0, time.time() - state["written_at"]))
            return state

    def command(self, identifier: str, request: dict) -> dict:
        with self.lock:
            session = self.session
            if not session or session.id != identifier or session.process.poll() is not None:
                raise ValueError("课程会话已改变，请重新打开实验")
            if get_experiment(session.experiment_id).adapter not in {"panda", "humanoid"}:
                raise ValueError("该实验使用官方窗口中的操作控件")
            identifier = str(uuid4())
            request = {**request, "id": identifier}
            path = session.log_path.with_suffix(".command.json")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
            temporary.replace(path)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state = self.state()
                if state and state.get("command_id") == identifier:
                    if state.get("command_error"):
                        raise ValueError(state["command_error"])
                    return state
                if session.process.poll() is not None:
                    raise RuntimeError("仿真进程已退出，请检查会话日志")
                time.sleep(0.02)
            raise RuntimeError("课程操作等待超时，请检查仿真进程")
    def stop(self) -> None:
        with self.lock:
            if self.session:
                self._terminate(self.session)
                self.session = None
                self._state_cache = None
