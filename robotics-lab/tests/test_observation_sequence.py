"""观测发布序号覆盖暂停、命令与两种重置路径，不依赖仿真时间或系统时钟排序。"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mujoco.experimental.studio import messages, sim

from robotics_lab.catalog import get_experiment
from robotics_lab.physics import load_model
from robotics_lab.studio import CourseStudio


class ObservationSequenceTests(unittest.TestCase):
    def studio(self, identifier, directory):
        experiment = get_experiment(identifier)
        model, data = load_model(experiment)
        return CourseStudio(model, data, experiment.mode, Path(directory) / identifier,
                            adapter=experiment.adapter)

    def read(self, studio):
        return json.loads(studio.bridge.with_suffix(".state.json").read_text(encoding="utf-8"))

    def command(self, studio, action):
        studio.bridge.with_suffix(".command.json").write_text(
            json.dumps({"id": action, "action": action}), encoding="utf-8")
        studio._command()
        self.assertIsNone(studio.command_error)
        return self.read(studio)

    def test_sequence_increases_across_pause_step_and_both_reset_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            for identifier in ("panda-structure", "g1-structure"):
                with self.subTest(identifier=identifier):
                    studio = self.studio(identifier, directory)
                    studio.step_control.set_pause_state(sim.PauseState.NORMAL_PAUSED)
                    # 发布时钟即使倒退，序号仍按仿真线程中的发布顺序递增。
                    with patch("robotics_lab.studio.time.time", side_effect=[100, 99, 98, 97, 96, 95]):
                        states = []
                        for _ in range(2):
                            self.assertTrue(studio._write())
                            states.append(self.read(studio))
                        states.append(self.command(studio, "step"))
                        states.append(self.command(studio, "reset"))
                        studio.controller.step()
                        self.assertTrue(studio._write())
                        states.append(self.read(studio))
                        self.assertTrue(studio._on_reset(messages.ResetEvent()))
                        states.append(self.read(studio))
                    self.assertEqual([s["observation_sequence"] for s in states], list(range(1, 7)))
                    self.assertEqual([s["time"] for s in states[:2]], [0, 0])
                    self.assertAlmostEqual(states[2]["time"], studio.controller.model.opt.timestep)
                    self.assertEqual(states[3]["time"], 0)
                    self.assertEqual(states[-1]["time"], 0)
                    self.assertTrue(all(s["paused"] for s in states))

    def test_failed_publication_keeps_previous_sequence_and_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = self.studio("panda-structure", directory)
            self.assertTrue(studio._write())
            previous = self.read(studio)
            studio.controller.step()
            with patch("robotics_lab.studio.Path.replace", side_effect=PermissionError):
                self.assertFalse(studio._write())
            self.assertEqual(self.read(studio), previous)
            self.assertTrue(studio._write())
            current = self.read(studio)
            self.assertEqual(current["observation_sequence"], previous["observation_sequence"] + 1)
            self.assertGreater(current["time"], previous["time"])


if __name__ == "__main__":
    unittest.main()
