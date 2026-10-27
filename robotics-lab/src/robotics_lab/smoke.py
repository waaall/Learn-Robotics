"""通过统一服务入口验收 HTTP、WASM、模型分块、WebSocket 与课程控制。"""

import json
import time
from urllib.request import Request, urlopen

from websockets.sync.client import connect

from .config import VIEWER_URL
from .gateway import ISOLATION_HEADERS


def check_service(base: str) -> dict:
    base = base.rstrip("/")

    def request(path, payload=None, method=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None

    with urlopen(base + "/", timeout=10) as response:
        for header, value in ISOLATION_HEADERS.items():
            assert response.headers[header] == value, (header, response.headers)
        assert b"<html" in response.read().lower()
    assert request("/api/health")["status"] == "ok"
    system = request("/api/system")
    assert system["viewer"]["available"], system
    if system["session"] and system["session"]["status"] in ("ready", "starting"):
        raise RuntimeError("已有用户仿真会话；请结束后再运行验收")
    courses = request("/api/courses")
    experiments = request("/api/catalog")
    catalog = {item["id"]: item for item in experiments}
    for course in courses:
        for lesson in course["lessons"]:
            assert lesson["experiment_id"] in catalog, lesson

    # 从实际目录选择每种适配器的代表实验，并覆盖所有基础物理场景。
    selected, seen = [], set()
    for item in experiments:
        key = (item["adapter"], item["id"] if item["adapter"] == "basic" else "")
        if key not in seen:
            selected.append(item)
            seen.add(key)
    checks, records = [], []
    for experiment in selected:
        identifier = experiment["id"]
        run = request("/api/runs", {"experiment_id": identifier})
        assert request("/api/runs/" + run["id"]) == run
        records.append(run["id"])
        session = request("/api/sessions", {"experiment_id": identifier})
        try:
            deadline = time.monotonic() + 60
            while session["status"] == "starting" and time.monotonic() < deadline:
                time.sleep(0.2)
                session = request("/api/sessions/current")
            assert session["status"] == "ready", session
            assert session["url"] == VIEWER_URL, session
            assert "port" not in session, session
            with urlopen(base + session["url"], timeout=10) as response:
                for header, value in ISOLATION_HEADERS.items():
                    assert response.headers[header] == value
                assert b"web_client.js" in response.read()
            with urlopen(base + VIEWER_URL + "web_client.wasm", timeout=30) as response:
                assert response.headers.get_content_type() == "application/wasm"
                assert response.read(4) == b"\x00asm"
                size = 4
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                assert size == int(response.headers["Content-Length"])
            model_size = request("/model?total_bytes")["total_bytes"]
            with urlopen(base + f"/model?offset_bytes=0&size_bytes={min(model_size, 64)}", timeout=10) as response:
                assert len(response.read()) == min(model_size, 64)
            ws_url = base.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
            with connect(ws_url + "/state?sid=smoke", open_timeout=15, proxy=None) as websocket:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    message = websocket.recv(timeout=10)
                    if isinstance(message, bytes) and message:
                        websocket.send("state_ack")
                        break
                else:
                    raise AssertionError("WebSocket 未收到二进制仿真状态")
            if experiment["adapter"] in {"panda", "humanoid", "microduck"}:
                def command(action):
                    return request("/api/sessions/current/commands", {
                        "session_id": session["id"], "action": action, "paused": True})

                before = command("pause")
                assert before["paused"]
                after = command("step")
                assert abs(after["time"] - before["time"] - run["runtime"]["timestep"]) < 1e-8
                assert command("reset")["time"] == 0
            checks.append({"experiment": identifier, "http": True, "wasm": True,
                           "model_chunks": True, "websocket": True})
        finally:
            request("/api/sessions/current", method="DELETE")
        assert request("/api/sessions/current") is None
    return {"system": system, "courses": len(courses),
            "lessons": sum(len(item["lessons"]) for item in courses),
            "persisted_run_ids": records, "viewer_checks": checks}
