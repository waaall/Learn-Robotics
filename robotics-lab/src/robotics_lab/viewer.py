"""官方 Studio WebViewer 适配入口。"""

import argparse
from pathlib import Path

from .catalog import get_experiment
from .diagnostics import viewer_capability
from .physics import load_model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bridge", type=Path)
    args = parser.parse_args()
    capability = viewer_capability()
    if not capability["available"]:
        parser.exit(2, capability["reason"] + "\n" + "\n".join(capability["details"]) + "\n")
    from mujoco.experimental.studio import launch_web, sim_history, step_control, viewer_app, viewer_protocol
    experiment = get_experiment(args.experiment)
    model, data = load_model(experiment)
    config = viewer_protocol.ViewerConfig(title="Robotics Lab", gfx="web", http_port=args.port)
    plugins = [step_control.StepControl(), sim_history.SimHistory()]
    if experiment.adapter == "panda":
        from .studio import PandaStudio
        if args.bridge is None:
            parser.error("Panda 课程需要 --bridge")
        plugins = [PandaStudio(model, data, experiment.mode, args.bridge)]
    launch_web.run(config, model=model, data=data,
                   viewer_plugins=[viewer_app.ViewerApp()],
                   sim_plugins=plugins)


if __name__ == "__main__":
    main()
