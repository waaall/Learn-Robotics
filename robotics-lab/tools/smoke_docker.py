"""在 API 容器内通过 Web 统一入口验证实际服务，运行期间占用一个查看器会话。"""

import argparse
import json
import time
from urllib.request import Request, urlopen

from websockets.sync.client import connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://web:8080")
    parser.add_argument("--output", default="/tmp/robotics-lab-smoke.json")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    def request(path, payload=None, method=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None

    assert request("/api/health")["status"] == "ok"
    system = request("/api/system")
    assert system["viewer"]["available"], system
    if system["session"] and system["session"]["status"] in ("ready", "starting"):
        raise RuntimeError("已有用户仿真会话；请结束后再运行验收")
    courses = request("/api/courses")
    assert [len(item["lessons"]) for item in courses] == [7, 2]
    run = request("/api/runs", {"experiment_id": "drop-ball"})
    assert abs(run["metrics"]["mean_support_N"] - 9.81) < 1e-4
    assert request("/api/runs/" + run["id"]) == run
    checks = []
    for experiment in ("panda-structure", "pendulum", "drop-ball"):
        session = request("/api/sessions", {"experiment_id": experiment})
        try:
            deadline = time.monotonic() + 60
            while session["status"] == "starting" and time.monotonic() < deadline:
                time.sleep(0.2)
                session = request("/api/sessions/current")
            assert session["status"] == "ready", session
            assert session["url"] == "/viewer/", session
            with urlopen(base + session["url"], timeout=10) as response:
                assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
                assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
                assert b"web_client.js" in response.read()
            with urlopen(base + "/viewer/web_client.wasm", timeout=15) as response:
                assert response.headers.get_content_type() == "application/wasm"
                assert response.read(4) == b"\x00asm"
                size = 4
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                assert size == int(response.headers["Content-Length"])
            ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
            with connect(ws_url + "/state", open_timeout=15) as websocket:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    message = websocket.recv(timeout=10)
                    if isinstance(message, bytes) and message:
                        break
                else:
                    raise AssertionError("WebSocket 未收到二进制仿真状态")
            if experiment == "panda-structure":
                before = request("/api/sessions/current/commands", {
                    "session_id": session["id"], "action": "pause", "paused": True,
                })
                assert before and before["session_id"] == session["id"]
                assert before["paused"]
                after = request("/api/sessions/current/commands", {
                    "session_id": session["id"], "action": "step", "paused": True,
                })
                assert abs(after["time"] - before["time"] - 0.001) < 1e-8
                restored = request("/api/sessions/current/commands", {
                    "session_id": session["id"], "action": "reset", "paused": True,
                })
                assert restored["time"] == 0
            checks.append({"experiment": experiment, "http": True, "wasm": True, "websocket": True})
        finally:
            request("/api/sessions/current", method="DELETE")
        assert request("/api/sessions/current") is None
    report = {"system": system, "courses": len(courses), "lessons": 9,
              "persisted_run_id": run["id"], "viewer_checks": checks}
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
