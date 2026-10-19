"""使用本机协议服务验证部署配置、流式代理、WebSocket 与统一启动脚本。"""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from robotics_lab.api import create_app
from robotics_lab.config import PROJECT, Settings
from robotics_lab.gateway import ISOLATION_HEADERS


class SettingsTests(unittest.TestCase):
    def test_environment_is_shared_and_cli_overrides_network_settings(self):
        with patch.dict(os.environ, {"ROBOTICS_LAB_HOST": "0.0.0.0", "ROBOTICS_LAB_PORT": "19000",
                                     "ROBOTICS_LAB_DATA_DIR": "./data/test"}):
            settings = Settings.from_env()
            self.assertEqual((settings.host, settings.port), ("0.0.0.0", 19000))
            self.assertEqual(settings.data_dir, PROJECT / "data/test")
            overridden = Settings.from_env(host="127.0.0.1", port=19001)
            self.assertEqual((overridden.host, overridden.port), ("127.0.0.1", 19001))

    def test_invalid_network_configuration_fails_early(self):
        for port in (0, -1, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                Settings(port=port)
        with self.assertRaises(ValueError):
            Settings(host=" ")


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        directory = Path(self.directory.name)
        (directory / "index.html").write_text("<html>course</html>", encoding="utf-8")
        settings = replace(Settings(), data_dir=directory / "runtime", static_dir=directory)
        self.client = TestClient(create_app(settings=settings))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def test_headers_cover_courses_api_errors_and_static_files(self):
        for path in ("/", "/api/health", "/not-found", "/viewer/"):
            response = self.client.get(path)
            for name, value in ISOLATION_HEADERS.items():
                self.assertEqual(response.headers[name], value)
        self.assertEqual(self.client.get("/viewer/").status_code, 503)
        self.assertEqual(self.client.get("/viewer", follow_redirects=False).headers["location"], "/viewer/")

    def test_http_proxy_preserves_query_bytes_length_status_and_mime(self):
        requests = []
        payload = b"\x00asm" + bytes(range(256)) * 1024

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers))
                self.send_response(206)
                self.send_header("Content-Type", "application/wasm")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close, X-Internal")
                self.send_header("X-Internal", "hidden")
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch("robotics_lab.sessions.SessionManager.active_port", return_value=server.server_port):
                    for path, forwarded in (("/viewer/web_client.wasm", "/web_client.wasm"),
                                            ("/model", "/model"), ("/assets/font.ttf", "/assets/font.ttf")):
                        response = self.client.get(path + "?offset_bytes=0&size_bytes=9", headers={
                            "Authorization": "Bearer private", "Cookie": "private=true"})
                        self.assertEqual(response.status_code, 206)
                        self.assertEqual(response.content, payload)
                        self.assertEqual(response.headers["content-type"], "application/wasm")
                        self.assertEqual(int(response.headers["content-length"]), len(payload))
                        self.assertNotIn("x-internal", response.headers)
                        self.assertEqual(requests[-1][0], forwarded + "?offset_bytes=0&size_bytes=9")
                        self.assertIsNone(requests[-1][1].get("Authorization"))
                        self.assertIsNone(requests[-1][1].get("Cookie"))
                        self.assertEqual(requests[-1][1].get("Connection"), "close")
                    response = self.client.head("/viewer/web_client.wasm")
                    self.assertEqual(response.status_code, 206)
                    self.assertEqual(response.content, b"")
                    self.assertEqual(int(response.headers["content-length"]), len(payload))
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_websocket_preserves_binary_text_query_and_upstream_close(self):
        received = []

        def echo(connection):
            received.append(connection.request.path)
            if connection.request.path.startswith("/ui"):
                connection.close(code=4001, reason="controller occupied")
                return
            for message in connection:
                connection.send(message)

        with serve(echo, "127.0.0.1", 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch("robotics_lab.sessions.SessionManager.active_port",
                           return_value=server.socket.getsockname()[1]):
                    with self.client.websocket_connect("/state?sid=deployment-test") as websocket:
                        websocket.send_bytes(b"\x00\x01state")
                        self.assertEqual(websocket.receive_bytes(), b"\x00\x01state")
                        websocket.send_text("state_ack")
                        self.assertEqual(websocket.receive_text(), "state_ack")
                    self.assertIn("/state?sid=deployment-test", received)
                    with self.client.websocket_connect("/ui") as websocket:
                        with self.assertRaises(WebSocketDisconnect) as error:
                            websocket.receive_text()
                        self.assertEqual(error.exception.code, 4001)
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_websocket_without_session_is_rejected(self):
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect("/state"):
                pass
        self.assertEqual(error.exception.code, 1013)


class LauncherTests(unittest.TestCase):
    def test_supported_hosts_use_identical_commands_and_separate_environments(self):
        for system, machine in (("Linux", "x86_64"), ("Linux", "aarch64"), ("Darwin", "arm64")):
            with self.subTest(system=system, machine=machine), tempfile.TemporaryDirectory(prefix="lab with spaces ") as directory:
                root = Path(directory)
                (root / "lab.sh").write_text((PROJECT / "lab.sh").read_text(), encoding="utf-8")
                (root / ".env").write_text("ROBOTICS_LAB_PORT=19000\n", encoding="utf-8")
                bin_dir = root / "bin"
                bin_dir.mkdir()
                uname = bin_dir / "uname"
                uname.write_text(f'#!/bin/sh\nif [ "$1" = -s ]; then echo {system}; else echo {machine}; fi\n')
                uname.chmod(0o755)
                # 测试替身只记录参数，不下载依赖，也不运行实际平台解释器。
                stub = root / "stub.py"
                stub.write_text(
                    'import json, os, sys\nfrom pathlib import Path\n'
                    'with open("commands.jsonl", "a") as f: f.write(json.dumps({"command": sys.argv[1], '
                    '"args": sys.argv[2:], "environment": os.environ["UV_PROJECT_ENVIRONMENT"]}) + "\\n")\n'
                    'if sys.argv[2:3] == ["sync"]:\n'
                    ' p = Path(os.environ["UV_PROJECT_ENVIRONMENT"]) / "bin/python"\n'
                    ' p.parent.mkdir(parents=True); p.touch(); p.chmod(0o755)\n', encoding="utf-8")
                for name in ("uv", "npm"):
                    command = bin_dir / name
                    command.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(stub))} {name} "$@"\n')
                    command.chmod(0o755)
                environment = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
                subprocess.run(["bash", str(root / "lab.sh"), "setup"], cwd=root, env=environment, check=True)
                calls = [json.loads(line) for line in (root / "commands.jsonl").read_text().splitlines()]
                self.assertEqual([call["command"] for call in calls], ["uv", "npm", "npm", "uv"])
                self.assertEqual(calls[0]["args"], ["sync", "--locked", "--no-install-project", "--python", "3.12"])
                self.assertTrue(all(call["environment"] == str(root / f".venv/{system}-{machine}") for call in calls))
                self.assertIn("--env-file", calls[-1]["args"])
                self.assertEqual(calls[-1]["args"][-3:], ["-m", "robotics_lab", "doctor"])
                (root / "frontend/dist").mkdir(parents=True)
                (root / "frontend/dist/index.html").touch()
                subprocess.run(["bash", str(root / "lab.sh"), "start", "--port", "19001"],
                               cwd=root, env=environment, check=True)
                started = json.loads((root / "commands.jsonl").read_text().splitlines()[-1])
                self.assertEqual(started["args"][-5:], ["-m", "robotics_lab", "serve", "--port", "19001"])


if __name__ == "__main__":
    unittest.main()
