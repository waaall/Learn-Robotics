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
    controlled = experiment.adapter in {"panda", "humanoid"}
    if controlled:
        from .studio import CourseStudio
        if args.bridge is None:
            parser.error("交互课程需要 --bridge")
        plugins = [CourseStudio(model, data, experiment.mode, args.bridge, adapter=experiment.adapter)]
    ui_config = viewer_app.ViewerAppConfig(
        show_options=not controlled, show_inspector=not controlled)
    launch_web.run(config, model=model, data=data,
                   viewer_plugins=[viewer_app.ViewerApp(ui_config)],
                   sim_plugins=plugins)


if __name__ == "__main__":
    main()
