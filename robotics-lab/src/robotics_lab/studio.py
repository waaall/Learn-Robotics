"""课程控制在 Studio 的仿真线程内执行，通过原子 JSON 文件与本地 API 通信。"""

import json
from pathlib import Path
import time

from mujoco.experimental.studio import messages, sim, step_control

from .panda import PandaController


class CourseStudio(step_control.StepControl):
    def __init__(self, model, data, mode: str, bridge: Path, adapter="panda"):
        super().__init__()
        self.adapter = adapter
        if adapter == "humanoid":
            from .humanoid import HumanoidController
            self.controller = HumanoidController(model, data, mode)
        else:
            self.controller = PandaController(model, data, mode)
        self.bridge = bridge
        self.command_id = None
        self.command_error = None
        self.last_tick = time.monotonic()
        self.last_write = 0.0
        self.budget = 0.0

    def _write(self):
        state = self.controller.state()
        state.update(command_id=self.command_id, command_error=self.command_error,
                     paused=self.step_control.get_pause_state() != sim.PauseState.UNPAUSED,
                     written_at=time.time())
        path = self.bridge.with_suffix(".state.json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        try:
            temporary.replace(path)
        except PermissionError:
            # Windows 读取 DrvFS 文件时可能短暂禁止替换；保留上一份状态，下轮重试。
            return False
        self.last_write = time.monotonic()
        return True

    def _command(self):
        path = self.bridge.with_suffix(".command.json")
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # DrvFS 的替换过程可能暂时使路径不可见；下一轮读取，不能终止仿真。
            return
        if request["id"] == self.command_id:
            return
        self.command_id, self.command_error = request["id"], None
        try:
            action = request["action"]
            common = {"reset", "configure", "pause", "step"}
            specific = ({"walk", "walk-stop", "push"} if self.adapter == "humanoid" else
                        {"gravity-release", "gravity-hold", "jacobian-run", "jacobian-stop", "trajectory", "grasp"})
            if action not in common | specific:
                raise ValueError("该课程不支持此操作")
            if action == "reset":
                self.controller.reset()
                self._apply_lesson_defaults()
            elif action == "configure":
                self.controller.configure(request.get("settings", {}))
            elif action in {"gravity-release", "gravity-hold"}:
                self.controller.start_gravity_trial(action == "gravity-hold")
                self.budget = 0
                self.step_control.set_pause_state(sim.PauseState.UNPAUSED)
            elif action == "jacobian-run":
                self.controller.configure(request.get("settings", {}))
                self.controller.start_jacobian()
                self.step_control.set_pause_state(sim.PauseState.UNPAUSED)
            elif action == "jacobian-stop":
                if self.controller.mode != "jacobian":
                    raise ValueError("请在雅可比课停止单关节运动")
                self.controller.stop_jacobian()
            elif action == "trajectory":
                self.controller.configure(request.get("settings", {}))
                self.controller.start_motion()
            elif action == "grasp":
                self.controller.start_grasp()
            elif action in {"walk", "walk-stop", "push"}:
                if not self.controller.mode.startswith("g1-"):
                    raise ValueError("该操作仅支持人形课程")
                self.controller.configure(request.get("settings", {}))
                {"walk": self.controller.start_walk, "walk-stop": self.controller.stop_walk,
                 "push": self.controller.push}[action]()
                self.step_control.set_pause_state(sim.PauseState.UNPAUSED)
            elif action == "pause":
                paused = request.get("paused", True)
                self.step_control.set_pause_state(sim.PauseState.NORMAL_PAUSED if paused else sim.PauseState.UNPAUSED)
            elif action == "step":
                self.step_control.set_pause_state(sim.PauseState.NORMAL_PAUSED)
                self.controller.step()
            else:
                raise ValueError("不支持的课程操作")
        except (ValueError, TypeError) as error:
            self.command_error = str(error)
        self._write()

    @messages.handler
    def _on_reset(self, event: messages.ResetEvent) -> bool:
        self.controller.reset()
        self._apply_lesson_defaults()
        self._write()
        return True

    def _apply_lesson_defaults(self):
        if self.adapter == "humanoid":
            from .humanoid import default_settings
        else:
            from .panda import default_settings
        self.controller.configure(default_settings(self.controller.mode))

    @messages.handler(priority=messages.Priority.INTERNAL)
    def _on_step(self, event: messages.StepEvent) -> None:
        with self._send_if_changes():
            self._command()
            now = time.monotonic()
            elapsed, self.last_tick = min(now - self.last_tick, 0.05), now
            if self.step_control.get_pause_state() == sim.PauseState.UNPAUSED:
                # Studio 的速度设置为百分数：100 表示一倍速。
                self.budget += elapsed * self.step_control.get_speed() / 100
                count = min(int(self.budget / event.model.opt.timestep), 50)
                self.budget -= count * event.model.opt.timestep
            else:
                self.budget = 0
                count = int(self.step_control.consume_single_step_request())
            for _ in range(count):
                self.controller.step()
            if now - self.last_write >= 0.1:
                self._write()
        time.sleep(0.005)


# 既有 Panda 插件调用保留兼容入口；课程调度按 adapter 选择控制器。
PandaStudio = CourseStudio
