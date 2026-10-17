"""检查实际安装的 WebViewer 组件，不以源码存在代替运行能力。"""

import importlib
import platform
from pathlib import Path

import mujoco

SOURCE = "https://github.com/google-deepmind/mujoco/blob/3.16.0/python/mujoco/experimental/studio/web/CMakeLists.txt"


def viewer_capability() -> dict:
    base = Path(mujoco.__file__).parent / "experimental" / "studio" / "web"
    missing = []
    for name in ("headless_ui", "state_payload"):
        try:
            importlib.import_module(f"mujoco.experimental.studio.web.{name}")
        except (ImportError, OSError) as error:
            missing.append(f"{name}: {error}")
    for asset in ("web_client.js", "web_client.wasm"):
        if not (base / "dist" / asset).is_file():
            missing.append(f"浏览器资源缺失：{asset}")
    if not missing:
        try:
            importlib.import_module("mujoco.experimental.studio.web_viewer")
        except (ImportError, OSError) as error:
            missing.append(str(error))
    return {
        "available": not missing, "platform": platform.system(), "mujoco": mujoco.__version__,
        "reason": ("查看器组件检查通过，启动后仍需浏览器验收" if not missing else
                   "当前运行环境缺少官方网页仿真组件；请在具备完整组件的 Linux 环境运行平台。"),
        "details": missing, "source": SOURCE,
    }
