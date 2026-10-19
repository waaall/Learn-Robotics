"""集中读取原生部署与容器部署的应用配置，查看器端口仅在进程内部使用。"""

from dataclasses import dataclass
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
VIEWER_URL = "/viewer/"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 18320
    data_dir: Path = PROJECT / ".runtime"
    static_dir: Path = PROJECT / "frontend" / "dist"

    def __post_init__(self):
        if not self.host.strip():
            raise ValueError("ROBOTICS_LAB_HOST 不能为空")
        if not 1 <= self.port <= 65535:
            raise ValueError("ROBOTICS_LAB_PORT 必须在 1 到 65535 之间")

    @classmethod
    def from_env(cls, *, host: str | None = None, port: int | None = None):
        # 相对目录始终相对于项目解析，不随启动终端的工作目录变化。
        directory = Path(os.environ.get("ROBOTICS_LAB_DATA_DIR") or PROJECT / ".runtime").expanduser()
        if not directory.is_absolute():
            directory = PROJECT / directory
        return cls(
            host=host if host is not None else os.environ.get("ROBOTICS_LAB_HOST", "127.0.0.1"),
            port=port if port is not None else int(os.environ.get("ROBOTICS_LAB_PORT", "18320")),
            data_dir=directory.resolve(),
        )
