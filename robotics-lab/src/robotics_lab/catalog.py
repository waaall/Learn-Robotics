"""显式实验目录；模型、初态和教学内容随项目版本发布。"""

from dataclasses import asdict, dataclass
from pathlib import Path
import tomllib

ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class Experiment:
    id: str
    title: str
    topic: str
    robot: str
    summary: str
    model: str
    qpos: tuple[float, ...]
    duration: float
    observable_index: int
    observable_name: str
    observable_unit: str
    explanation: str
    observations: tuple[str, ...]
    adapter: str = "basic"
    mode: str = "physics"
    initial_ctrl: tuple[float, ...] = ()

    @property
    def model_path(self) -> Path:
        path = (ASSETS / "models" / self.model).resolve()
        if not path.is_relative_to((ASSETS / "models").resolve()):
            raise ValueError("模型路径必须位于项目模型目录")
        return path

    def public(self) -> dict:
        result = asdict(self)
        result.pop("model")
        return result


def catalog() -> dict[str, Experiment]:
    with (ASSETS / "catalog.toml").open("rb") as stream:
        entries = tomllib.load(stream)["experiments"]
    result = {}
    from .curriculum import PANDA_LESSONS
    for lesson in PANDA_LESSONS:
        entries.append({"id": lesson["id"], "title": lesson["title"], "topic": "Panda 机械臂基础",
                        "robot": "Franka Emika Panda", "summary": lesson["summary"],
                        "model": "panda_course.xml", "qpos": [0, 0, 0, -1.57079, 0, 1.57079, -0.7853, 0.04, 0.04,
                                                                  0.45, 0, 0.225, 1, 0, 0, 0],
                        "initial_ctrl": [0, 0, 0, -1.57079, 0, 1.57079, -0.7853, 255],
                        "duration": lesson["duration"], "observable_index": 0,
                        "observable_name": "关节 1 角度", "observable_unit": "rad",
                        "explanation": lesson["summary"], "observations": lesson["observations"],
                        "adapter": "panda", "mode": lesson["mode"]})
    from .humanoid_curriculum import HUMANOID_LESSONS
    from .humanoid import HOME as G1_HOME
    for lesson in HUMANOID_LESSONS:
        entries.append({"id": lesson["id"], "title": lesson["title"], "topic": "人形机器人基础",
                        "robot": "Unitree G1（12 驱动关节）", "summary": lesson["summary"],
                        "model": "g1_course.xml", "qpos": [0, 0, 0.793, 1, 0, 0, 0, *G1_HOME.tolist()],
                        "initial_ctrl": [0.0]*len(G1_HOME), "duration": lesson["duration"],
                        "observable_index": 2, "observable_name": "基座高度", "observable_unit": "m",
                        "explanation": lesson["summary"], "observations": lesson["observations"],
                        "adapter": "humanoid", "mode": lesson["mode"]})
    for entry in entries:
        entry["qpos"] = tuple(entry["qpos"])
        entry["observations"] = tuple(entry["observations"])
        entry["initial_ctrl"] = tuple(entry.get("initial_ctrl", ()))
        item = Experiment(**entry)
        if item.id in result or not item.model_path.is_file():
            raise ValueError(f"重复实验标识或模型缺失：{item.id}")
        result[item.id] = item
    return result


def get_experiment(identifier: str) -> Experiment:
    from .curriculum import LESSON_ALIASES
    identifier = LESSON_ALIASES.get(identifier, identifier)
    try:
        return catalog()[identifier]
    except KeyError:
        raise ValueError(f"未知实验：{identifier}") from None
