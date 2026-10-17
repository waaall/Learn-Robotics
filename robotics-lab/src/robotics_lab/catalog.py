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
    for entry in entries:
        entry["qpos"] = tuple(entry["qpos"])
        entry["observations"] = tuple(entry["observations"])
        item = Experiment(**entry)
        if item.id in result or not item.model_path.is_file():
            raise ValueError(f"重复实验标识或模型缺失：{item.id}")
        result[item.id] = item
    return result


def get_experiment(identifier: str) -> Experiment:
    try:
        return catalog()[identifier]
    except KeyError:
        raise ValueError(f"未知实验：{identifier}") from None
