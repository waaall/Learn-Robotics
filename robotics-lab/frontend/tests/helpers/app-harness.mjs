// 挂载实际应用，使用受控计时器和请求延迟检查会话界面与导出记录，不连接仿真服务。
import { act, createElement } from "react";
import { JSDOM } from "jsdom";

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const HOME = [0, 0, 0, -1.57, 0, 1.57, -0.78];
const LESSONS = ["structure", "joint-control"].map(mode => ({
  id: `panda-${mode}`, experiment_id: `panda-${mode}`, mode, adapter: "panda",
  title: `测试课 ${mode}`, question: "测试观测", summary: "用于应用级网络回归",
  prerequisites: "", concepts: [], steps: [], observations: [], exercise: "", sources: [],
  default_settings: { joints: HOME, velocity: HOME.map(() => 0) },
}));
const COURSES = [{ id: "test-course", title: "测试课程", lessons: LESSONS }];

export class MockLab {
  session = null;
  sequence = 0;
  sessionsCreated = 0;
  requests = [];
  systemHolds = [];
  createHold = null;
  coursesHold = null;
  deleteError = null;

  system() {
    return { version: "test", viewer: { available: true, platform: "test", mujoco: "test", reason: "" },
      session: this.session ? { ...this.session } : null };
  }

  startSession(experiment_id = LESSONS[0].experiment_id) {
    this.session = { id: `test-session-${++this.sessionsCreated}`, experiment_id,
      status: "ready", url: "/mock-viewer", error: null };
    this.sequence = 0;
    return this.session;
  }

  holdSystem(transform = info => info) {
    const hold = { ...deferred(), transform, requested: deferred() };
    this.systemHolds.push(hold);
    return hold;
  }

  observation() {
    if (!this.session) return null;
    const sequence = ++this.sequence;
    return {
      session_id: this.session.id, observation_sequence: sequence, time: sequence / 10,
      age_seconds: 0, phase: "测试运行", paused: false,
      joints: HOME.map(q => q + sequence / 1000), reference_joints: HOME, target_joints: HOME,
      tool_position: [0.5, sequence / 1000, 0.4], tool_rotation: [[1,0,0],[0,1,0],[0,0,1]],
      gripper_width: 0.08, actuator_torque: HOME.map(() => 0), gravity_torque: HOME.map(() => 0),
      compensation: true, cube_position: [0.45, 0, 0.225], contacts: 0,
    };
  }

  fetch = async (path, options = {}) => {
    const method = options.method ?? "GET";
    this.requests.push({ path, method, signal: options.signal });
    const response = (value, status = 200) => ({ ok: status < 400, status,
      json: async () => structuredClone(value) });
    if (path === "/api/courses") {
      if (this.coursesHold) await this.coursesHold.promise;
      return response(COURSES);
    }
    if (path === "/api/system") {
      const snapshot = this.system();
      const hold = this.systemHolds.shift();
      if (hold) {
        hold.requested.resolve();
        // 刻意不响应 AbortSignal，以确认应用还会拒绝已经进入响应处理流程的旧数据。
        await hold.promise;
        return response(hold.transform(snapshot));
      }
      return response(snapshot);
    }
    if (path === "/api/sessions" && method === "POST") {
      if (this.createHold) await this.createHold.promise;
      const { experiment_id } = JSON.parse(options.body);
      return response(this.startSession(experiment_id), 201);
    }
    if (path === "/api/sessions/current" && method === "DELETE") {
      if (this.deleteError) {
        const detail = this.deleteError;
        this.deleteError = null;
        return response({ detail }, 503);
      }
      this.session = null;
      return response(null, 204);
    }
    if (path === "/api/sessions/current/state") return response(this.observation());
    if (path === "/api/sessions/current/commands") return response(this.observation());
    throw new Error(`未配置的请求：${method} ${path}`);
  };
}

export async function mountApp(App, lab = new MockLab()) {
  const dom = new JSDOM('<!doctype html><div id="test-root"></div>', { url: "http://robotics-lab.test/#panda-structure" });
  const saved = new Map();
  const setGlobal = (name, value) => {
    saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  };
  for (const name of ["window", "document", "location", "localStorage", "navigator"]) {
    setGlobal(name, dom.window[name]);
  }
  setGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  setGlobal("fetch", lab.fetch);
  setGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  dom.window.scrollTo = () => {};
  dom.window.HTMLElement.prototype.scrollTo = () => {};
  dom.window.matchMedia = () => ({ matches: false });
  dom.window.HTMLAnchorElement.prototype.click = () => {};

  let timerId = 0;
  const intervals = new Map(), timeouts = new Map();
  setGlobal("setInterval", (callback, delay) => {
    intervals.set(++timerId, { callback, delay });
    return timerId;
  });
  setGlobal("clearInterval", id => intervals.delete(id));
  const realTimeout = globalThis.setTimeout, realClearTimeout = globalThis.clearTimeout;
  setGlobal("setTimeout", (callback, delay, ...args) => {
    // 仅控制应用启动的等待，保留 React 与测试运行器的其他计时行为。
    if (delay !== 500) return realTimeout(callback, delay, ...args);
    const id = ++timerId;
    timeouts.set(id, { callback: () => callback(...args), delay });
    return id;
  });
  setGlobal("clearTimeout", id => timeouts.delete(id) || realClearTimeout(id));

  let exported;
  const createURL = URL.createObjectURL, revokeURL = URL.revokeObjectURL;
  URL.createObjectURL = blob => { exported = blob; return "blob:test-export"; };
  URL.revokeObjectURL = () => {};
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(dom.window.document.getElementById("test-root"));
  const flush = async work => { await act(async () => { work?.(); }); };
  const button = label => [...dom.window.document.querySelectorAll("button")]
    .find(element => element.textContent.includes(label));
  const click = async label => {
    const element = button(label);
    if (!element || element.disabled) throw new Error(`按钮不可操作：${label}`);
    await flush(() => element.click());
  };
  const tick = async delay => flush(() => {
    for (const timer of [...intervals.values()]) if (timer.delay === delay) timer.callback();
    for (const [id, timer] of [...timeouts]) if (timer.delay === delay) {
      timeouts.delete(id);
      timer.callback();
    }
  });
  await flush(() => root.render(createElement(App)));
  return {
    lab, dom, button, click, tick, flush,
    async open() { await click("打开交互实验"); await tick(500); },
    async record(count = 3) { for (let i = 0; i < count; i++) await tick(200); },
    async exported() { await click("导出观测"); return JSON.parse(await exported.text()); },
    async close() {
      await flush(() => root.unmount());
      URL.createObjectURL = createURL;
      URL.revokeObjectURL = revokeURL;
      for (const [name, descriptor] of saved) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
      }
      dom.window.close();
    },
  };
}
