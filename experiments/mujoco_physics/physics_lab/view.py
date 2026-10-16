"""沿用实验配置打开官方原生查看器，不引入新的仿真或界面框架。"""

import argparse
from pathlib import Path

import mujoco
import mujoco.viewer

from .common import DEFAULT_CONFIG, load_config, load_model


INITIAL_KEY = "experiment_initial"


def prepare_view(case: dict, base: Path) -> tuple[mujoco.MjModel, mujoco.MjData]:
    model, data = load_model(case, base)
    # 仅在内存中的模型副本增加初态关键帧，让原生 Load key 恢复配置中的状态和输入。
    spec = mujoco.MjSpec.from_file(str((base / case["model"]).resolve()))
    spec.add_key(name=INITIAL_KEY, time=data.time, qpos=data.qpos, qvel=data.qvel,
                 act=data.act, ctrl=data.ctrl)
    view_model = spec.compile()
    view_model.opt.timestep = model.opt.timestep
    view_data = mujoco.MjData(view_model)
    key = mujoco.mj_name2id(view_model, mujoco.mjtObj.mjOBJ_KEY, INITIAL_KEY)
    mujoco.mj_resetDataKeyframe(view_model, view_data, key)
    mujoco.mj_forward(view_model, view_data)
    return view_model, view_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 MuJoCo 原生 UI 查看已配置的物理实验")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--case", help="只打开指定算例；省略时依次打开配置中的所有算例")
    args = parser.parse_args(argv)
    path = args.config.resolve()
    config = load_config(path)
    expected = config["runtime"]["expected_version"]
    if mujoco.__version__ != expected or mujoco.mj_versionString() != expected:
        parser.error(f"Python 包和运行库必须同时为 {expected}")
    cases = config["cases"]
    if args.case is not None and args.case not in cases:
        parser.error(f"未知算例 {args.case!r}，可选：{', '.join(cases)}")
    selected = [args.case] if args.case is not None else list(cases)
    if not selected:
        parser.error("配置中没有可查看的算例")
    for index, name in enumerate(selected, start=1):
        model, data = prepare_view(cases[name], path.parent)
        print(f"[{index}/{len(selected)}] {name} | {model.names[:model.names.index(0)].decode()}", flush=True)
        print("Space: 暂停/继续；Simulation > Load key: 恢复实验初态；关闭窗口进入下一项。", flush=True)
        print("球形转子可在 Rendering > Frame 选择 Body 观察旋转。", flush=True)
        # 物理线程、播放速度、关节滑块和鼠标交互全部交给官方查看器管理。
        mujoco.viewer.launch(model, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
