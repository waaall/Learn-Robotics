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
    from mujoco.experimental.studio.web import web_server
    experiment = get_experiment(args.experiment)
    model, data = load_model(experiment)
    config = viewer_protocol.ViewerConfig(title="Robotics Lab", gfx="web", http_port=args.port)
    plugins = [step_control.StepControl(), sim_history.SimHistory()]
    controlled = experiment.adapter in {"panda", "humanoid", "microduck"}
    if controlled:
        from .studio import CourseStudio
        if args.bridge is None:
            parser.error("交互课程需要 --bridge")
        plugins = [CourseStudio(model, data, experiment.mode, args.bridge, adapter=experiment.adapter)]
    ui_config = viewer_app.ViewerAppConfig(
        show_options=not controlled, show_inspector=not controlled)
    # 上游 3.16.0 固定传入 ::，尚未开放监听地址配置。仅在此子进程内替换
    # 套接字工厂，保持官方服务实现，同时确保动态查看器端口仅监听回环。
    bind_socket = web_server.bind_public_socket
    web_server.bind_public_socket = lambda _host, port: bind_socket("127.0.0.1", port)
    try:
        launch_web.run(config, model=model, data=data,
                       viewer_plugins=[viewer_app.ViewerApp(ui_config)],
                       sim_plugins=plugins)
    finally:
        web_server.bind_public_socket = bind_socket


if __name__ == "__main__":
    main()
