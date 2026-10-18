"""Local tools for an external LLM: observe, load_model, preview, start_task, status, stop.

The current Codex conversation calls the CLI tools and supplies the task and rationale.
All serial IO and timing remain in this persistent local process. CLI clients only import
the standard library. The server binds localhost and requires a per-session bearer token.
"""

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid


def now():
    return datetime.now().astimezone().isoformat()


def save_json(path, value):
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


class Runtime:
    def __init__(self, cfg, folder, limits, allow_motion):
        from .control_hardware import PositionFollower
        from .live_hardware import LatestCamera
        from .recording import VideoRecorder
        self.cfg, self.folder, self.limits = cfg, folder, limits
        self.allow_motion = allow_motion
        self.log_lock, self.bus_lock, self.job_lock = threading.Lock(), threading.RLock(), threading.Lock()
        self.report_lock = threading.Lock()
        self.cancel, self.shutdown = threading.Event(), threading.Event()
        self.started = time.perf_counter()
        self.lease_deadline = 0
        self.policy = None
        self.job = {"state": "idle"}
        self.observations = {}
        self.model_calls = 0
        self.commands_sent = 0
        self.fault = None
        self.processor_audit = {"ready_for_vla_execution": False, "issues": ["model not audited"]}
        self.hardware = PositionFollower(cfg.follower_serial, cfg.calibration, limits, self.event)
        self.camera = LatestCamera(cfg.camera_index, cfg.width, cfg.height, cfg.fps)
        self.recorder = None
        self.worker = None
        self.monitor = None
        self.report = {"schema_version": 1, "started": now(), "status": "starting",
                       "config": cfg.record(), "limits": asdict(limits), "motion_enabled": allow_motion,
                       "controller": "external_llm_tools", "model_weights_updated": False,
                       "protocol": "SO101 absolute range positions: body [-100,100], gripper [0,100]",
                       "protocol_evidence": "LeRobot legacy SO100/101 mapping; roundtrip checked locally",
                       "unverified": ["base-model training calibration/embodiment semantic alignment",
                                      "single wrist view transfer and task success",
                                      "30Hz policy sampling is an explicit experimental setting",
                                      "no scene geometry or collision model; visual review and small joint excursions",
                                      "software watchdog cannot release torque after forced process termination"],
                       "commands_sent": 0, "model_calls": 0}
        self.flush()

    def event(self, kind, **values):
        row = {**values, "time": now(), "monotonic": time.perf_counter(), "event": kind}
        with self.log_lock:
            with (self.folder / "operations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")

    def flush(self):
        with self.report_lock:
            self.report.update(commands_sent=self.commands_sent, model_calls=self.model_calls,
                               job=dict(self.job), updated=now())
            save_json(self.folder / "report.json", self.report)

    def open(self):
        state = self.hardware.open()
        self.origin = dict(state["raw"])
        # Roundtrip checks the implemented mapping, without asserting training-distribution equivalence.
        roundtrip = self.hardware.action_to_raw(state["state"])
        if max(abs(roundtrip[j] - state["raw"][j]) for j in self.origin) > 1:
            raise RuntimeError("state/action encoder mapping failed roundtrip")
        self.report["initial_observation"] = state
        self.camera.open()
        self.recorder = __import__("smolvla_inference.recording", fromlist=["VideoRecorder"]).VideoRecorder(
            self.camera, self.folder, self.cfg.fps, self.event)
        self.recorder.open()
        deadline = time.perf_counter() + 3
        while self.recorder.frames == 0 and not self.recorder.error and time.perf_counter() < deadline:
            time.sleep(.02)
        self.recorder.check()
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()
        self.report.update(status="ready", camera=self.camera.metadata, hardware=self.hardware.metadata)
        self.flush()

    def _monitor(self):
        try:
            while not self.shutdown.wait(.1):
                if time.perf_counter() - self.started > self.limits.max_session_s:
                    try:
                        self.event("session_deadline")
                    finally:
                        self.stop("session deadline")
                        self.shutdown.set()
                    return
                self.recorder.check()
                _, arrived, _ = self.camera.after(0)
                if time.perf_counter() - arrived > self.limits.max_frame_age_s:
                    raise RuntimeError("camera frame expired")
                with self.bus_lock:
                    if self.hardware.owns_torque:
                        if time.perf_counter() > self.lease_deadline:
                            raise RuntimeError("60 second LLM supervision lease expired")
                        self.hardware.read()
        except Exception as error:
            self.fault = str(error)
            try:
                self.event("watchdog_stop", error=str(error))
            finally:
                self.stop(str(error))

    def observe(self):
        import cv2
        number, arrived, frame = self.camera.after(0)
        with self.bus_lock:
            state = self.hardware.read()
        if time.perf_counter() - arrived > self.limits.max_frame_age_s:
            raise RuntimeError("observation expired")
        observation_id = uuid.uuid4().hex[:12]
        path = self.folder / f"observation-{observation_id}.jpg"
        if not cv2.imwrite(str(path), frame):
            raise OSError("could not save observation")
        result = {"observation_id": observation_id, "image_path": str(path), "camera_sequence": number,
                  "frame_received_monotonic": arrived, "observed_monotonic": time.perf_counter(),
                  "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **state}
        self.observations[observation_id] = result
        self.event("observe", **result)
        self.lease_deadline = time.perf_counter() + 60
        return result

    def load_model(self):
        if self.policy is None:
            from .live import load_model
            begin = time.perf_counter()
            self.policy, self.pre, self.post, runtime, assets = load_model(self.cfg)
            self.policy.reset()
            from .control import audit_processors
            self.processor_audit = audit_processors(self.pre, self.post)
            self.report.update(runtime=runtime, assets=assets, model_load_s=time.perf_counter() - begin)
            self.report["processor_audit"] = self.processor_audit
            self.event("model_loaded", **runtime, assets=assets)
            self.event("processor_audit", **self.processor_audit)

    def predict(self, task, noise_sample=None):
        import numpy as np
        import torch
        from .engine import sample_noise
        from .live import build_observation, validate_prediction
        self.load_model()
        self.recorder.check()
        observation = self.observe()
        import cv2
        # Use the lossless current camera array for model input, not the diagnostic JPEG.
        sequence, arrived, frame = self.camera.after(observation["camera_sequence"] - 1)
        with self.bus_lock:
            state = self.hardware.read()
        if state["state_warnings"]:
            raise RuntimeError("inference refused: input state would be clipped to calibration")
        if time.perf_counter() - arrived > self.limits.max_frame_age_s:
            raise RuntimeError("inference input expired")
        noise_sample = self.model_calls if noise_sample is None else noise_sample
        if type(noise_sample) is not int or noise_sample < 0:
            raise ValueError("noise_sample must be a nonnegative integer")
        noise = sample_noise(self.policy.config, self.cfg.noise_seed, noise_sample, "cuda")
        torch.cuda.synchronize()
        begin = time.perf_counter()
        batch = self.pre(build_observation(frame, state["state"], task))
        with torch.inference_mode(), torch.autocast("cuda", enabled=self.cfg.use_amp):
            generated = self.policy.predict_action_chunk(batch, noise=noise)
            actions = self.post(generated).detach().cpu().numpy()
        torch.cuda.synchronize()
        validate_prediction(actions, self.policy.config.chunk_size)
        call_id = self.model_calls
        self.model_calls += 1
        path = self.folder / f"prediction-{call_id:04d}.npz"
        # Preserve exact RGB source separately to make input/action attribution reproducible.
        image_path = self.folder / f"prediction-{call_id:04d}-input.png"
        if not cv2.imwrite(str(image_path), frame):
            raise OSError("could not save exact model input")
        np.savez_compressed(path, predicted=actions[0], normalized=generated.detach().cpu().numpy()[0],
                            state=np.asarray(state["state"]), frame_sequence=sequence)
        self.event("prediction", call_id=call_id, task=task, observation=state,
                   frame_sequence=sequence, frame_received_monotonic=arrived, input_image=str(image_path),
                   input_image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                   noise_seed=self.cfg.noise_seed, noise_sample=noise_sample,
                   prediction_path=str(path), first_action=actions[0, 0].tolist(),
                   inference_s=time.perf_counter() - begin)
        return actions[0], observation, call_id

    def launch(self, operation, arguments):
        if not self.job_lock.acquire(blocking=False):
            raise RuntimeError("another model/execution job is running")
        try:
            if operation == "start_task":
                self._check_task(arguments)
            self.cancel.clear()
            job_id = uuid.uuid4().hex[:12]
            self.job = {"id": job_id, "operation": operation, "state": "running", "arguments": arguments}
            self.worker = threading.Thread(target=self._work, args=(operation, arguments), daemon=True)
            self.flush()
            self.worker.start()
            return dict(self.job)
        except BaseException:
            self.job_lock.release()
            raise

    def _check_task(self, args):
        from .control import validate_start
        if not self.allow_motion:
            raise RuntimeError("server was started without --allow-motion")
        if self.fault:
            raise RuntimeError(f"latched watchdog fault: {self.fault}")
        seconds = args.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds <= self.limits.max_burst_s:
            raise ValueError("invalid bounded execution duration")
        reviewed = self.observations.get(args.get("observation_id"))
        if reviewed is None or time.perf_counter() - reviewed["observed_monotonic"] > 120:
            raise RuntimeError("a visually reviewed observation from the last 120 seconds is required")
        from .live_hardware import JOINTS
        active = args.get("active_joints", [])
        if not active or len(set(active)) != len(active) or any(j not in JOINTS for j in active):
            raise ValueError("explicit nonempty active_joints required")
        if not args.get("task", "").strip() or not args.get("reason", "").strip():
            raise ValueError("task and LLM decision rationale are required")
        with self.bus_lock:
            state = self.hardware.read()
        validate_start(state["raw"], self.hardware.calibration, self.limits)
        if max(abs(state["raw"][j] - reviewed["raw"][j]) for j in JOINTS) > 24:
            raise RuntimeError("robot moved since visual review; observe again")
        controller = args.get("controller", "vla")
        if controller == "vla":
            if self.policy is None:
                raise RuntimeError("load and preview the model before requesting motion")
            if not self.processor_audit["ready_for_vla_execution"]:
                raise RuntimeError("VLA execution refused: " + "; ".join(self.processor_audit["issues"]))
        elif controller == "wrist_nod":
            import math
            amplitude = args.get("amplitude_deg", 2.5)
            if active != ["wrist_flex"] or isinstance(amplitude, bool) or not isinstance(amplitude, (int, float)):
                raise ValueError("wrist_nod requires only wrist_flex and a numeric amplitude")
            if not 0 < amplitude <= 3 or 2 * math.pi * amplitude / seconds > self.limits.joint_speed_deg_s:
                raise ValueError("nod amplitude/duration exceeds the bounded skill speed")
        else:
            raise ValueError("unsupported controller")

    def _work(self, operation, args):
        try:
            self.event("llm_decision", operation=operation, actor="external_llm", arguments=args)
            if operation == "load_model":
                self.load_model()
                result = {"model_loaded": True, "processor_audit": self.processor_audit}
            elif operation == "preview":
                actions, observation, call_id = self.predict(args["task"], args.get("noise_sample"))
                result = {"call_id": call_id, "observation_id": observation["observation_id"],
                          "first_action": actions[0].tolist(), "last_action": actions[-1].tolist(),
                          "per_axis_min": actions.min(axis=0).tolist(), "per_axis_max": actions.max(axis=0).tolist()}
            elif operation == "start_task":
                result = self._nod(args) if args.get("controller") == "wrist_nod" else self._execute(args)
            else:
                raise ValueError("unknown job")
            self.job.update(state="cancelled" if self.cancel.is_set() else "completed", result=result)
        except Exception as error:
            self.job.update(state="failed", error=str(error))
            try:
                self.event("job_failed", error=str(error))
            except Exception:
                pass
            with self.bus_lock:
                failures = self.hardware.release()
            self.job["torque_release_errors"] = failures
        finally:
            try:
                self.event("job_finished", job=dict(self.job))
                self.flush()
            finally:
                self.job_lock.release()

    def _nod(self, args):
        """An explicitly labelled deterministic hardware skill, independent of the VLA."""
        import math
        from .control import bounded_targets
        with self.bus_lock:
            if self.cancel.is_set():
                return {"commands_sent": 0, "cancelled_before_arming": True}
            self.lease_deadline = time.perf_counter() + 60
            before = self.hardware.read() if self.hardware.owns_torque else self.hardware.arm()
        previous = {j: float(v) for j, v in before["raw"].items()}
        start = previous_tick = time.perf_counter()
        samples, wrist = [], "wrist_flex"
        while not self.cancel.is_set():
            tick = time.perf_counter()
            phase = min(1., (tick - start) / args["seconds"])
            requested = dict(before["raw"])
            requested[wrist] += args.get("amplitude_deg", 2.5) * 4095 / 360 * math.sin(2 * math.pi * phase)
            self.recorder.check()
            _, arrived, _ = self.camera.after(0)
            if time.perf_counter() - arrived > self.limits.max_frame_age_s:
                raise RuntimeError("nod refused: camera stale")
            with self.bus_lock:
                measured = self.hardware.read()
                targets, reasons = bounded_targets(requested, previous, measured["raw"], self.origin,
                                                    self.hardware.calibration, tick - previous_tick or 1e-6,
                                                    self.limits)
                if time.perf_counter() - tick > self.limits.max_io_s or self.cancel.is_set():
                    raise RuntimeError("nod IO interval expired or cancelled")
                self.hardware.send(targets)
            self.commands_sent += 1
            samples.append(measured["raw"][wrist])
            self.event("control_tick", source="deterministic_wrist_nod", model_action=None,
                       active_joints=[wrist], observation=measured, requested_raw=requested,
                       commanded_raw={j: round(v) for j, v in targets.items()}, constraints=reasons,
                       elapsed_s=time.perf_counter() - start)
            previous, previous_tick = targets, tick
            if phase >= 1:
                break
            self.cancel.wait(max(0, 1 / self.limits.control_hz - (time.perf_counter() - tick)))
        with self.bus_lock:
            after = self.hardware.read()
        self.lease_deadline = time.perf_counter() + 60
        return {"controller": "deterministic_wrist_nod", "vla_actions_executed": 0,
                "commands_sent": len(samples), "before": before, "after": after,
                "wrist_observed_span_deg": (max(samples) - min(samples)) * 360 / 4095 if samples else 0,
                "wrist_return_error_deg": (after["raw"][wrist] - before["raw"][wrist]) * 360 / 4095}

    def _execute(self, args):
        from .control import bounded_targets
        # First prediction must be available and valid before enabling torque.
        actions, _, call_id = self.predict(args["task"], args.get("noise_sample"))
        with self.bus_lock:
            if self.cancel.is_set():
                return {"commands_sent": 0, "cancelled_before_arming": True}
            before = self.hardware.read()
            active = set(args["active_joints"])
            first = dict(before["raw"])
            selected = [float(v) if j in active else before["state"][i]
                        for i, (j, v) in enumerate(zip(before["raw"], actions[0]))]
            self.hardware.action_to_raw(selected)
            self.lease_deadline = time.perf_counter() + 60
            if not self.hardware.owns_torque:
                before = self.hardware.arm()
            previous = {j: float(v) for j, v in before["raw"].items()}
        start = previous_tick = time.perf_counter()
        chunk_start = start
        sent = 0
        while time.perf_counter() - start < args["seconds"] and not self.cancel.is_set():
            tick = time.perf_counter()
            index = int((tick - chunk_start) * self.limits.policy_hz)
            # Re-observe after <= 10 predicted steps instead of consuming a whole 50-step block.
            if index >= min(10, len(actions)):
                actions, _, call_id = self.predict(args["task"])
                if self.cancel.is_set():
                    break
                tick = time.perf_counter()
                if tick - start >= args["seconds"]:
                    break
                chunk_start, index = tick, 0
                # The arm held its previous command during model generation. Do not catch up that time.
                previous_tick = tick - 1 / self.limits.control_hz
            self.recorder.check()
            _, arrived, _ = self.camera.after(0)
            if tick - arrived > self.limits.max_frame_age_s:
                raise RuntimeError("motion refused: camera stale")
            with self.bus_lock:
                measured = self.hardware.read()
                selected = [float(v) if j in active else before["state"][i]
                            for i, (j, v) in enumerate(zip(before["raw"], actions[index]))]
                requested = self.hardware.action_to_raw(selected)
                requested.update({j: before["raw"][j] for j in requested if j not in active})
                targets, reasons = bounded_targets(requested, previous, measured["raw"], self.origin,
                                                    self.hardware.calibration, tick - previous_tick or 1e-6,
                                                    self.limits)
                if time.perf_counter() - tick > self.limits.max_io_s or self.cancel.is_set():
                    break
                self.hardware.send(targets)
            self.event("control_tick", call_id=call_id, action_index=index, active_joints=sorted(active),
                       model_action=actions[index].tolist(), selected_action=selected,
                       observation=measured, requested_raw=requested, commanded_raw={j: round(v) for j, v in targets.items()},
                       constraints=reasons, elapsed_s=time.perf_counter() - start)
            previous, previous_tick = targets, tick
            self.commands_sent += 1
            sent += 1
            self.cancel.wait(max(0, 1 / self.limits.control_hz - (time.perf_counter() - tick)))
        with self.bus_lock:
            after = self.hardware.read()
        self.lease_deadline = time.perf_counter() + 60
        result = {"commands_sent": sent, "before": before, "after": after,
                  "delta_degrees": {j: (after["raw"][j] - first[j]) * 360 / 4095 for j in active if j != "gripper"},
                  "torque_state": "holding until stop or independent supervision/session timeout"}
        return result

    def status(self):
        self.lease_deadline = time.perf_counter() + 60
        return {"folder": str(self.folder), "job": dict(self.job), "model_calls": self.model_calls,
                "commands_sent": self.commands_sent, "torque_owned": self.hardware.owns_torque,
                "processor_audit": self.processor_audit, "watchdog_fault": self.fault,
                "recording_frames": self.recorder.frames, "recording_error": self.recorder.error,
                "session_remaining_s": max(0, self.limits.max_session_s - (time.perf_counter() - self.started))}

    def stop(self, reason="LLM stop"):
        self.cancel.set()
        with self.bus_lock:
            failures = self.hardware.release()
        try:
            self.event("stop", reason=reason, torque_release_errors=failures)
        except Exception as error:
            self.report["stop_log_error"] = str(error)
        return {"stopped": not failures, "torque_release_errors": failures}

    def close(self):
        self.shutdown.set()
        try:
            self.stop("server shutdown")
        except Exception as error:
            self.report["stop_error"] = str(error)
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=10)
        if self.monitor:
            self.monitor.join(timeout=3)
        if self.recorder:
            try:
                self.recorder.close()
            except Exception as error:
                self.report["recording_close_error"] = str(error)
        self.camera.close()
        with self.bus_lock:
            self.report["torque_release_errors"] = self.hardware.close()
        self.report.update(status="closed", finished=now(),
                           motor_register_writes=self.hardware.register_writes,
                           recording_frames=self.recorder.frames if self.recorder else 0)
        self.flush()


def serve(args):
    from .control import Limits
    from .live import DEFAULT_CONFIG, load_config
    cfg = load_config(args.config or DEFAULT_CONFIG)
    folder = cfg.output_dir.parent / "supervised" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True)
    token = secrets.token_urlsafe(32)
    runtime = Runtime(cfg, folder, Limits(), args.allow_motion)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *values):
            pass

        def do_POST(self):
            if self.headers.get("Authorization") != "Bearer " + token:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("invalid request size")
                request = json.loads(self.rfile.read(length))
                method, params = request["method"], request.get("params", {})
                runtime.event("tool_request", method=method, params=params)
                if method == "observe":
                    result = runtime.observe()
                elif method == "status":
                    result = runtime.status()
                elif method == "stop":
                    result = runtime.stop(params.get("reason", "LLM stop"))
                elif method == "shutdown":
                    result = runtime.stop("LLM shutdown")
                    runtime.shutdown.set()
                elif method in ("load_model", "preview", "start_task"):
                    result = runtime.launch(method, params)
                elif method == "annotate":
                    runtime.event("llm_observation_analysis", **params)
                    result = {"saved": True}
                else:
                    raise ValueError("unknown tool")
                response = {"ok": True, "result": result}
            except Exception as error:
                response = {"ok": False, "error": str(error)}
            data = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.timeout = .1
            runtime.open()
            save_json(args.session_file, {"url": f"http://127.0.0.1:{server.server_port}",
                                          "token": token, "folder": str(folder)})
            print(json.dumps({"ready": True, "folder": str(folder), "session_file": str(args.session_file)}), flush=True)
            while not runtime.shutdown.is_set():
                server.handle_request()
    finally:
        runtime.close()


def call(session_file, method, params):
    session = json.loads(session_file.read_text(encoding="utf-8"))
    request = urllib.request.Request(session["url"], method="POST",
                                     data=json.dumps({"method": method, "params": params}, ensure_ascii=False).encode(),
                                     headers={"Authorization": "Bearer " + session["token"], "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, default=Path("outputs/supervised-session.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve")
    server.add_argument("--config", type=Path)
    server.add_argument("--port", type=int, default=8766)
    server.add_argument("--allow-motion", action="store_true")
    commands.add_parser("tools", help="print the external LLM tool input schemas; no device access")
    client = commands.add_parser("call")
    client.add_argument("method", choices=["observe", "load_model", "preview", "start_task", "status", "stop", "shutdown", "annotate"])
    client.add_argument("--params", default="{}", help="JSON tool arguments, or @path to a JSON file")
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args)
        return 0
    if args.command == "tools":
        print(Path(__file__).with_name("tool_contract.json").read_text(encoding="utf-8"))
        return 0
    params = json.loads(Path(args.params[1:]).read_text(encoding="utf-8") if args.params.startswith("@") else args.params)
    return call(args.session_file, args.method, params)


if __name__ == "__main__":
    raise SystemExit(main())
