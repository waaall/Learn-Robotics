"""远程辅助的无网络测试：配置隔离、路径引用、SSH 失败和检查报告真实性。"""

import base64
import gzip
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from remote_lab.__main__ import main
from remote_lab.config import load_config
from remote_lab.inspection import check_server, inspection_script, session_script
from remote_lab.transport import command_text, decode_report, encoded_stdin, ps_literal, run_readonly, ssh_args


ROOT = Path(__file__).resolve().parent


def example():
    return {
        "schema_version": 2,
        "ssh": {"host": "lab.example.test", "user": "robot", "port": 2222,
                "identity_file": "", "connect_timeout_seconds": 5, "check_timeout_seconds": 30},
        "windows": {"repo_dir": "E:\\研发 空间\\O'Brien\\RobotLab",
                    "python_executable": "C:\\Tools\\Python312\\python.exe"},
        "project": {"directory": "experiments/training", "module": "smolvla_training",
                    "config": "configs/smolvla-so100.toml", "required_files": ["experiments/training/run.ps1"]},
    }


def report(*, ready=True):
    return {"schema_version": 1, "status": "collected", "checks": {"test": ready},
            "ready_for_setup": ready, "repo": {"path": "E:\\研发"}}


def frame(value, marker="__TEST__"):
    payload = base64.b64encode(json.dumps(value, ensure_ascii=False).encode()).decode()
    return f"{marker}:{payload}:END\r\n"


class ConfigFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "remote.local.json"

    def load(self, value=None):
        self.path.write_text(json.dumps(example() if value is None else value), encoding="utf-8")
        return load_config(self.path)


class ConfigTests(ConfigFixture, unittest.TestCase):
    def test_machine_paths_are_not_resolved_on_client(self):
        cfg = self.load()
        self.assertEqual(str(cfg.lab_dir), "E:\\研发 空间\\O'Brien\\RobotLab\\experiments\\training")
        self.assertTrue(str(cfg.config_path).startswith(str(cfg.windows.repo_dir)))
        self.assertEqual(cfg.ssh.port, 2222)
        self.assertIsNone(cfg.ssh.identity_file)

    def test_ssh_alias_can_inherit_user_and_port(self):
        value = example()
        value["ssh"].update(host="robot-lab", user="", port=None)
        args = ssh_args(self.load(value))
        self.assertNotIn("-l", args)
        self.assertNotIn("-p", args)
        self.assertEqual(args[-1], "robot-lab")

    def test_identity_is_local_path_without_reading_contents(self):
        key = Path(self.temp.name) / "key with spaces"
        key.write_text("not a key; content must not be read", encoding="utf-8")
        value = example()
        value["ssh"]["identity_file"] = key.name
        cfg = self.load(value)
        self.assertEqual(cfg.ssh.identity_file, key.resolve())
        self.assertIn(str(key.resolve()), ssh_args(cfg))
        self.assertNotIn("not a key", json.dumps(cfg.to_dict()))

    def test_missing_identity_rejected(self):
        value = example()
        value["ssh"]["identity_file"] = "absent-key"
        with self.assertRaises(ValueError):
            self.load(value)

    def test_unknown_fields_and_credentials_rejected(self):
        for section, key in ((None, "install_command"), ("ssh", "password"), ("ssh", "private_key"),
                             ("windows", "startup_command")):
            value = example()
            (value if section is None else value[section])[key] = "unsafe"
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                self.load(value)

    def test_template_must_be_filled(self):
        with self.assertRaisesRegex(ValueError, "占位"):
            load_config(ROOT / "configs" / "remote.example.json")

    def test_invalid_schema_host_user_port_and_timeouts(self):
        bad = [(None, "schema_version", True), (None, "schema_version", 1), (None, "schema_version", 2.0),
               ("ssh", "host", "-oProxyCommand=bad"), ("ssh", "host", "a@b"),
               ("ssh", "host", "lab\nexit"), ("ssh", "user", "robot;exit"),
               ("ssh", "port", True), ("ssh", "port", 0), ("ssh", "port", 65536),
               ("ssh", "connect_timeout_seconds", 0), ("ssh", "check_timeout_seconds", 5)]
        for section, name, setting in bad:
            value = example()
            (value if section is None else value[section])[name] = setting
            with self.subTest(name=name, setting=setting), self.assertRaises(ValueError):
                self.load(value)

    def test_invalid_remote_paths_and_traversal(self):
        bad = [("repo_dir", "repo"), ("repo_dir", "D:repo"), ("repo_dir", "\\repo"),
               ("repo_dir", "\\\\other-host\\share\\repo"), ("repo_dir", "D:\\repo\\..\\escape"),
               ("repo_dir", "D:\\repo\nexit"), ("repo_dir", "D:\\repo:stream"),
               ("python_executable", "C:\\Tools\\python.bat"),
               ("config", "D:\\other.toml"), ("config", "\\other.toml"),
               ("config", "../other.toml"), ("config", "configs/test.json")]
        for name, setting in bad:
            value = example()
            value["project" if name == "config" else "windows"][name] = setting
            with self.subTest(name=name, setting=setting), self.assertRaises(ValueError):
                self.load(value)

    def test_utf8_bom_supported(self):
        self.path.write_text(json.dumps(example()), encoding="utf-8-sig")
        self.assertEqual(load_config(self.path).ssh.host, "lab.example.test")

    def test_project_target_rejects_traversal_commands_and_duplicate_files(self):
        bad = [("directory", "../training"), ("directory", "D:/other"),
               ("module", "smolvla_training --download"), ("module", "x;exit"),
               ("required_files", []), ("required_files", ["../private.json"]),
               ("required_files", ["tools/a.py", "tools/a.py"])]
        for key, setting in bad:
            value = example()
            value["project"][key] = setting
            with self.subTest(key=key, setting=setting), self.assertRaises(ValueError):
                self.load(value)

    def test_inference_target_is_explicit_without_training_paths(self):
        value = example()
        value["project"].update(directory="experiments/inference", module="smolvla_inference",
                                config="configs/smolvla-offline.toml",
                                required_files=["experiments/inference/smolvla_inference/__main__.py"])
        cfg = self.load(value)
        session = session_script(cfg)
        probe = inspection_script(cfg, "__TEST__")
        self.assertIn("$EntryModule = 'smolvla_inference'", session)
        self.assertIn("experiments\\inference", probe)
        self.assertNotIn("experiments\\training", probe)
        self.assertNotIn("smolvla_training", session)

    def test_validate_works_without_ml_packages_or_network(self):
        self.load()
        code = ("import sys; from remote_lab.__main__ import main; main(['--config',sys.argv[1],'validate']); "
                "assert not {'torch','lerobot','huggingface_hub','numpy'} & sys.modules.keys()")
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["ssh"]["host"], "lab.example.test")


class TransportTests(ConfigFixture, unittest.TestCase):
    def test_secure_batch_argv_no_remote_command(self):
        cfg = self.load()
        args = ssh_args(cfg)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        self.assertIn("-T", args)
        self.assertEqual(args[-1], cfg.ssh.host)
        self.assertNotIn("powershell", " ".join(args))

    def test_first_use_requires_human_confirmation(self):
        args = ssh_args(self.load(), interactive=True, first_use=True)
        self.assertIn("StrictHostKeyChecking=ask", args)
        self.assertIn("BatchMode=no", args)
        self.assertNotIn("-T", args)
        self.assertNotIn("StrictHostKeyChecking=no", args)
        with self.assertRaises(ValueError):
            ssh_args(self.load(), first_use=True)

    def test_oversized_script_is_not_sent(self):
        with self.assertRaises(ValueError):
            encoded_stdin("#" * 30001)

    def test_powershell_quoting_and_encoded_unicode(self):
        cfg = self.load()
        script = inspection_script(cfg, "__TEST__")
        lines = encoded_stdin(script).decode("ascii").splitlines()
        payload = "".join(line.split("'")[1] for line in lines if line.startswith("$env:__RemoteLabPayload += "))
        self.assertEqual(gzip.decompress(base64.b64decode(payload)).decode("utf-8"), script)
        encoded = next(line for line in lines if line.startswith("powershell.exe")).split()[-1]
        self.assertIn("$env:__RemoteLabPayload", base64.b64decode(encoded).decode("utf-16-le"))
        self.assertLess(max(map(len, lines)), 2200)
        self.assertIn("O''Brien", script)
        self.assertEqual(ps_literal("a'; $x='b"), "'a''; $x=''b'")
        self.assertEqual(command_text(["ssh", "key's path"], powershell=True), "& 'ssh' 'key''s path'")
        self.assertIn("'key", command_text(["ssh", "key's path"], powershell=False))

    def test_session_uses_config_without_importing_project(self):
        script = session_script(self.load())
        self.assertIn("O''Brien", script)
        self.assertIn("$EntryModule = 'smolvla_training'", script)
        self.assertNotIn("$Plan", script)
        self.assertNotIn(" -m ", script)
        self.assertNotIn("setup.ps1", script)
        self.assertNotIn(" train", script)

    def test_profile_output_does_not_hide_valid_report(self):
        output = "Windows banner\r\nPS C:\\> command echo\n\x1b[32m" + frame(report()) + "\x1b[0mPS>"
        self.assertEqual(decode_report(output, "__TEST__"), report())

    def test_missing_echoed_duplicate_and_corrupt_reports_rejected(self):
        bad = ["PowerShell banner\n", "PS> " + frame(report()), frame(report()) * 2,
               "__TEST__:AAA=:END\n", "__TEST__:====:END\n"]
        for output in bad:
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                decode_report(output, "__TEST__")

    def test_remote_error_and_invalid_conclusions_rejected(self):
        failed = {"schema_version": 1, "status": "failed", "error": "Python probe failed"}
        bad = [failed, [], {"schema_version": 3}, {**report(), "checks": {}},
               {**report(), "checks": {"test": "true"}}, {**report(), "ready_for_setup": False}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                decode_report(frame(value), "__TEST__")

    @patch("remote_lab.transport.subprocess.run")
    def test_subprocess_uses_argv_timeout_and_stdin(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, frame(report()).encode(), b"profile warning")
        cfg = self.load()
        self.assertTrue(run_readonly(cfg, "# test script", "__TEST__")["ready_for_setup"])
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1], cfg.ssh.host)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], cfg.ssh.check_timeout_seconds)
        self.assertIn(b"-NoProfile", kwargs["input"])

    @patch("remote_lab.transport.subprocess.run")
    def test_nonzero_exit_is_not_report_success(self, run):
        run.return_value = subprocess.CompletedProcess([], 255, frame(report()).encode(), b"Host key verification failed")
        with self.assertRaisesRegex(RuntimeError, "Host key"):
            run_readonly(self.load(), "# test", "__TEST__")

    @patch("remote_lab.transport.subprocess.run")
    def test_remote_nonzero_exit_preserves_probe_error(self, run):
        failed = {"schema_version": 1, "status": "failed", "error": "Python probe failed"}
        run.return_value = subprocess.CompletedProcess([], 1, frame(failed).encode(), b"profile warning")
        with self.assertRaisesRegex(RuntimeError, "Python probe failed"):
            run_readonly(self.load(), "# test", "__TEST__")

    @patch("remote_lab.transport.subprocess.run")
    def test_timeout_or_missing_ssh_fails(self, run):
        for error in (subprocess.TimeoutExpired("ssh", 30), FileNotFoundError("ssh")):
            run.side_effect = error
            with self.subTest(error=error), self.assertRaises(RuntimeError):
                run_readonly(self.load(), "# test", "__TEST__")

    @patch("remote_lab.inspection.run_readonly")
    def test_check_is_explicitly_readonly_and_marker_unique(self, run):
        run.return_value = report()
        cfg = self.load()
        check_server(cfg)
        first = run.call_args.args[2]
        script = run.call_args.args[1]
        check_server(cfg)
        self.assertNotEqual(first, run.call_args.args[2])
        self.assertIn("GIT_OPTIONAL_LOCKS", script)
        self.assertNotIn("pip install", script)
        self.assertNotIn("git pull", script)
        self.assertNotIn("import torch", script)

    @patch("remote_lab.__main__.check_server")
    def test_check_cli_reports_missing_prerequisites_with_exit_2(self, check):
        check.return_value = report(ready=False)
        cfg = self.load()
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            main(["--config", str(cfg.source), "check"])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(json.loads(output.getvalue())["ready_for_setup"])

    @patch("remote_lab.__main__.check_server")
    def test_local_commands_never_connect(self, check):
        cfg = self.load()
        for command in ("validate", "ssh-command", "session"):
            with redirect_stdout(io.StringIO()):
                main(["--config", str(cfg.source), command])
        check.assert_not_called()

    def test_bad_config_cli_has_exit_1(self):
        self.path.write_text('{"password": "not allowed"}', encoding="utf-8")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["--config", str(self.path), "validate"])
        self.assertEqual(caught.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
