"""官方 Studio WebViewer 适配入口。"""

import argparse

from .catalog import get_experiment
from .diagnostics import viewer_capability
from .physics import load_model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    capability = viewer_capability()
    if not capability["available"]:
        parser.exit(2, capability["reason"] + "\n" + "\n".join(capability["details"]) + "\n")
    from mujoco.experimental.studio import launch_web, sim_history, step_control, viewer_app, viewer_protocol
    model, data = load_model(get_experiment(args.experiment))
    config = viewer_protocol.ViewerConfig(title="Robotics Lab", gfx="web", http_port=args.port)
    launch_web.run(config, model=model, data=data,
                   viewer_plugins=[viewer_app.ViewerApp()],
                   sim_plugins=[step_control.StepControl(), sim_history.SimHistory()])


if __name__ == "__main__":
    main()
