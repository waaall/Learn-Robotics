"""隔离机器信息与实验参数，严格校验本地 JSON，不接受密码或任意命令字段。"""

from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath
import re


@dataclass(frozen=True)
class SSHConfig:
    host: str
    user: str
    port: int | None
    identity_file: Path | None
    connect_timeout_seconds: int
    check_timeout_seconds: int


@dataclass(frozen=True)
class WindowsConfig:
    repo_dir: PureWindowsPath
    python_executable: PureWindowsPath


@dataclass(frozen=True)
class ProjectConfig:
    directory: PureWindowsPath
    module: str
    config: PureWindowsPath
    required_files: tuple[PureWindowsPath, ...]


@dataclass(frozen=True)
class RemoteConfig:
    source: Path
    ssh: SSHConfig
    windows: WindowsConfig
    project: ProjectConfig

    @property
    def lab_dir(self):
        return self.windows.repo_dir / self.project.directory

    @property
    def config_path(self):
        return self.lab_dir / self.project.config

    def to_dict(self):
        return {
            "config_file": str(self.source),
            "ssh": {
                "host": self.ssh.host, "user": self.ssh.user, "port": self.ssh.port,
                "identity_file": str(self.ssh.identity_file) if self.ssh.identity_file else "",
                "connect_timeout_seconds": self.ssh.connect_timeout_seconds,
                "check_timeout_seconds": self.ssh.check_timeout_seconds,
            },
            "windows": {
                "repo_dir": str(self.windows.repo_dir),
                "python_executable": str(self.windows.python_executable),
            },
            "project": {
                "directory": str(self.lab_dir), "module": self.project.module,
                "config": str(self.config_path),
                "required_files": [str(self.windows.repo_dir / path) for path in self.project.required_files],
            },
        }


def _object(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{name} 必须且只能包含：{', '.join(sorted(keys))}")
    return value


def _text(value, name, *, empty=False):
    if not isinstance(value, str) or (not value and not empty):
        raise ValueError(f"{name} 必须是{'可空' if empty else '非空'}字符串")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} 不能包含控制字符")
    if "CHANGE_ME" in value:
        raise ValueError(f"请先填写 {name}，不能直接使用模板占位值")
    return value


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} 必须是 {low} 到 {high} 的整数")
    return value


def _windows_absolute(value, name):
    value = _text(value, name)
    path = PureWindowsPath(value)
    # 第一版仅支持本地盘符；避免 UNC 检查引发额外网络访问或使用设备路径。
    if not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive):
        raise ValueError(f"{name} 必须是带盘符的 Windows 绝对路径")
    if ".." in path.parts or any(char in value for char in '<>"|?*') or ":" in value[2:]:
        raise ValueError(f"{name} 包含不支持的路径字符或父目录跳转")
    return path


def _relative(value, name):
    value = _text(value, name)
    path = PureWindowsPath(value)
    if path.drive or path.root or ".." in path.parts or not path.parts or any(char in value for char in '<>:"|?*'):
        raise ValueError(f"{name} 必须是目录内相对路径，禁止父目录跳转")
    return path


def load_config(path: Path) -> RemoteConfig:
    path = path.expanduser().resolve()
    with path.open(encoding="utf-8-sig") as source:
        raw = json.load(source)
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 2:
        raise ValueError("仅支持 schema_version = 2；旧机器配置需按新模板填写 project 目标")
    raw = _object(raw, {"schema_version", "ssh", "windows", "project"}, "根配置")
    ssh = _object(raw["ssh"], {"host", "user", "port", "identity_file",
                             "connect_timeout_seconds", "check_timeout_seconds"}, "ssh")
    windows = _object(raw["windows"], {"repo_dir", "python_executable"}, "windows")
    project = _object(raw["project"], {"directory", "module", "config", "required_files"}, "project")
    host = _text(ssh["host"], "ssh.host")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", host):
        raise ValueError("ssh.host 必须是主机名、IP 或 SSH 别名，不能含空格、@ 或选项")
    user = _text(ssh["user"], "ssh.user", empty=True)
    if user and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\\-]*", user):
        raise ValueError("ssh.user 格式不受支持；特殊账号可在 SSH 配置中声明并留空此字段")
    port = None if ssh["port"] is None else _integer(ssh["port"], 1, 65535, "ssh.port")
    connect = _integer(ssh["connect_timeout_seconds"], 1, 120, "ssh.connect_timeout_seconds")
    timeout = _integer(ssh["check_timeout_seconds"], connect + 1, 600, "ssh.check_timeout_seconds")
    identity = _text(ssh["identity_file"], "ssh.identity_file", empty=True)
    # 密钥只引用当前客户端上的文件路径；不读取或输出私钥内容。
    identity_path = (path.parent / Path(identity).expanduser()).resolve() if identity else None
    if identity_path and not identity_path.is_file():
        raise ValueError(f"ssh.identity_file 不存在：{identity_path}")
    repo = _windows_absolute(windows["repo_dir"], "windows.repo_dir")
    python = _windows_absolute(windows["python_executable"], "windows.python_executable")
    if python.suffix.lower() != ".exe":
        raise ValueError("windows.python_executable 必须指向 Python .exe")
    directory = _relative(project["directory"], "project.directory")
    experiment = _relative(project["config"], "project.config")
    if experiment.suffix.lower() != ".toml":
        raise ValueError("project.config 必须是实验 TOML 文件")
    module = _text(project["module"], "project.module")
    if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", module, flags=re.ASCII):
        raise ValueError("project.module 必须是 Python 模块名，不能包含命令参数")
    required = project["required_files"]
    if not isinstance(required, list) or not required:
        raise ValueError("project.required_files 必须是非空的仓库相对文件路径列表")
    files = tuple(_relative(value, "project.required_files") for value in required)
    if len(set(files)) != len(files):
        raise ValueError("required_files 不能重复")
    return RemoteConfig(path, SSHConfig(host, user, port, identity_path, connect, timeout),
                        WindowsConfig(repo, python), ProjectConfig(directory, module, experiment, files))
