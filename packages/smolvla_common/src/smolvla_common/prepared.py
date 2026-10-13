"""冻结准备记录是训练与推理的文件接口；路径可显式重定位，协议身份不能随之改变。"""

from pathlib import Path

from .config import fingerprint, from_record
from .protocol import read_json, validate_schema


def read_prepared(path: Path, *, asset_overrides=None, require_base=True):
    manifest = read_json(path)
    if type(manifest.get("manifest_version")) is not int or manifest["manifest_version"] != 1:
        raise ValueError("准备记录格式不兼容；旧运行需保留并在新目录重新 prepare，不自动覆盖")
    if fingerprint(manifest["config"]) != manifest["config_fingerprint"]:
        raise ValueError("冻结配置与准备记录指纹不一致")
    # 配置指纹直接绑定原始 JSON，跨操作系统复制时不改写其中的历史路径。
    from_record(manifest["config"])
    if validate_schema(manifest["dataset_info"]) != manifest["schema"]:
        raise ValueError("准备记录的特征协议与原始 metadata 不一致")
    split = manifest["split"]
    for side in ("train", "validation"):
        values = split[side]
        if not values or any(type(value) is not int or value < 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("数据划分必须是非空、唯一的非负轨迹编号")
    if set(split["train"]) & set(split["validation"]):
        raise ValueError("准备记录存在训练／验证轨迹重叠")
    overrides = asset_overrides or {}
    if set(overrides) - {"dataset_path", "model_path", "backbone_path"}:
        raise ValueError("未知资产路径覆盖")
    manifest = {**manifest, **{key: str(value) for key, value in overrides.items() if value is not None}}
    required = ["dataset_path", "backbone_path"] + (["model_path"] if require_base else [])
    for key in required:
        asset = Path(manifest[key])
        if not asset.is_absolute() or not asset.is_dir():
            raise ValueError(f"资产缺失或路径不适用于本机：{key}={asset}；跨机器时显式配置资产路径")
    actual_info = read_json(Path(manifest["dataset_path"]) / "meta" / "info.json")
    if actual_info != manifest["dataset_info"]:
        raise ValueError("重定位数据的 metadata 与冻结版本不一致，不能换成另一个数据集")
    return manifest
