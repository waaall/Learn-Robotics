"""推理配置只描述输入产物、本机资产位置、评估参数与输出，不包含训练超参数。"""

from dataclasses import asdict, dataclass
from pathlib import Path
import tomllib

from smolvla_common.config import InferenceConfig, validate_inference


@dataclass(frozen=True)
class InferenceJob:
    prepared_manifest: Path
    cache_dir: Path
    output_dir: Path
    checkpoint: Path | None
    dataset_dir: Path | None
    base_model_dir: Path | None
    backbone_dir: Path | None
    inference: InferenceConfig

    def to_dict(self):
        result = asdict(self)
        for key in result:
            if key != "inference":
                result[key] = str(result[key]) if result[key] is not None else None
        return result

    @property
    def asset_overrides(self):
        return {"dataset_path": self.dataset_dir, "model_path": self.base_model_dir,
                "backbone_path": self.backbone_dir}


def load_config(path: Path):
    path = path.resolve()
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if set(raw) != {"paths", "assets", "model", "inference"}:
        raise ValueError("推理配置必须且只能包含 paths、assets、model、inference")
    paths, assets = raw["paths"], raw["assets"]
    if set(paths) != {"base_dir", "prepared_manifest", "cache_dir", "output_dir"}:
        raise ValueError("paths 字段不完整或含未知字段")
    if set(assets) != {"dataset_dir", "base_model_dir", "backbone_dir"} or set(raw["model"]) != {"checkpoint"}:
        raise ValueError("assets 或 model 字段不完整或含未知字段")
    for key, value in {**paths, **assets, **raw["model"]}.items():
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            raise ValueError(f"路径 {key} 必须是无控制字符的字符串")
    if any(not paths[key] for key in paths):
        raise ValueError("paths 字段不能为空")
    base = (path.parent / paths["base_dir"]).resolve()
    resolve = lambda value: (base / value).resolve() if value else None
    options = InferenceConfig(**raw["inference"])
    validate_inference(options)
    return InferenceJob(resolve(paths["prepared_manifest"]), resolve(paths["cache_dir"]),
                        resolve(paths["output_dir"]), resolve(raw["model"]["checkpoint"]),
                        resolve(assets["dataset_dir"]), resolve(assets["base_model_dir"]),
                        resolve(assets["backbone_dir"]), options)
