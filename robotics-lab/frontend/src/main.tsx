// 课程与查看器共用应用源，所有部署使用服务端返回的相对查看器地址。
import { useEffect, useReducer, useRef, useState } from "react";
import { HumanoidActions, HumanoidChart, HumanoidControls, HumanoidReadings } from "./humanoid";
import { createObservationLog, reduceObservationLog } from "./observations";
import { SystemRequests } from "./system-requests";
import {
  Chart,
  Controls,
  ExperimentActions,
  Readings,
  Theory,
} from "./widgets";
import {
  defaults,
  defaultJoint,
  canonicalLessonId,
  GEOMETRIC,
  HOME,
  type Course,
  type Observation,
  type HumanoidObservation,
  type Run,
  type Session,
  type System,
} from "./types";
type RobotObservation = Observation | HumanoidObservation;
const NEW_TRIAL_ACTIONS = new Set(["reset", "gravity-release", "gravity-hold", "jacobian-run"]);

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `请求失败（${response.status}）`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const LABELS: Record<string, string> = {
  steps: "积分步数",
  final_time: "时长 / s",
  final_speed: "末态速度范数",
  max_energy_drift_J: "最大能量变化 / J",
  mean_support_N: "末段支撑 / N",
  max_penetration_m: "最大穿透 / m",
  joint_error_rad: "参考跟踪误差 / rad",
  tool_target_error_m: "末端目标误差 / m",
  ik_solution_error_m: "IK 候选解残差 / m",
  max_cube_height_m: "方块最高高度 / m",
  joint_displacement_rad: "相对初态构型偏移 / rad",
  tool_height_change_m: "末端高度变化 / m",
  velocity_error_m_s: "预测与观测速度误差 / m·s⁻¹",
  base_height_m: "基座高度 / m",
  max_tilt_rad: "最大倾角 / rad",
  displacement_m: "平面位移 / m",
  fallen_samples: "跌倒采样数",
};

export function App() {
  const [courses, setCourses] = useState<Course[]>([]),
    [selected, setSelected] = useState(
      canonicalLessonId(location.hash.slice(1)) || "panda-structure",
    );
  const [system, setSystem] = useState<System | null>(null);
  const [systemRequests] = useState(() => new SystemRequests<System>(
    signal => request<System>("/api/system", { signal }), setSystem,
  ));
  const [observations, dispatchObservation] = useReducer(
    reduceObservationLog<RobotObservation>, undefined, () => createObservationLog<RobotObservation>(),
  );
  const { current: state, history } = observations;
  const [settings, setSettings] = useState(() => defaults());
  const [run, setRun] = useState<Run | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const [directoryOpen, setDirectoryOpen] = useState(() => {
    try {
      return localStorage.getItem("robotics-lab.directory-open.v1") === "true";
    } catch {
      return false;
    }
  });
  const [joint, setJoint] = useState(0),
    [motionJoint, setMotionJoint] = useState(1),
    [completed, setCompleted] = useState<string[]>(() => {
      try {
        const saved = JSON.parse(
          localStorage.getItem("robotics-lab.completed") || "[]",
        );
        return Array.isArray(saved)
          ? [
              ...new Set(
                saved
                  .filter((id): id is string => typeof id === "string")
                  .map(canonicalLessonId),
              ),
            ]
          : [];
      } catch {
        return [];
      }
    });
  const selection = useRef(selected),
    actions = useRef<unknown[]>([]);
  const inspector = useRef<HTMLElement | null>(null);
  selection.current = selected;
  const course =
    courses.find((c) => c.lessons.some((l) => l.id === selected)) || courses[0];
  const lesson =
    course?.lessons.find((l) => l.id === selected) || course?.lessons[0];
  const index = course?.lessons.findIndex((l) => l.id === lesson?.id) ?? 0;
  const session = system?.session,
    mode = lesson?.mode || "structure",
    panda = lesson?.adapter === "panda",
    humanoid = lesson?.adapter === "humanoid",
    controlled = panda || humanoid;
  const ready =
    session?.status === "ready" &&
    session.experiment_id === lesson?.experiment_id;
  const viewerUrl = session?.url;
  const latest = state || run?.state;
  const pandaLatest = latest && !("robot" in latest) ? latest : null;
  const humanoidLatest = latest && "robot" in latest ? latest : null;
  const controlPanel = humanoid && settings.humanoid ? (
    <HumanoidControls mode={mode} settings={settings} set={setSettings} />
  ) : (
    <Controls
      mode={mode}
      settings={settings}
      set={setSettings}
      joint={motionJoint}
      setJoint={setMotionJoint}
    />
  );

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      request<Course[]>("/api/courses", { signal: controller.signal }),
      systemRequests.read({ signal: controller.signal }),
    ])
      .then(([items]) => {
        if (controller.signal.aborted) return;
        // 初始课程请求可能慢于后续系统轮询，选课时使用最近已接受的系统状态。
        const info = systemRequests.current();
        setCourses(items);
        const lessons = items.flatMap((c) => c.lessons);
        const initialLesson =
          lessons.find((l) =>
            info?.session
              ? l.experiment_id === info.session.experiment_id
              : l.id === selection.current,
          ) || lessons[0];
        setSelected(initialLesson.id);
        setSettings(defaults(initialLesson));
        setJoint(defaultJoint(initialLesson.mode));
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(String(e));
      });
    const timer = setInterval(
      () =>
        systemRequests.read({ signal: controller.signal })
          .catch(() => {}),
      2000,
    );
    return () => {
      controller.abort();
      systemRequests.cancel();
      clearInterval(timer);
    };
  }, [systemRequests]);
  useEffect(() => {
    dispatchObservation({ type: "session", sessionId:
      session && session.experiment_id === selected && controlled ? session.id : null });
    if (!session || session.experiment_id !== selected || !controlled) return;
    const controller = new AbortController();
    const read = () =>
      request<RobotObservation | null>("/api/sessions/current/state", {
        signal: controller.signal,
      })
        .then((s) => {
          if (
            controller.signal.aborted ||
            !s ||
            s.session_id !== session.id ||
            selection.current !== selected
          )
            return;
          dispatchObservation({ type: "receive", observation: s });
        })
        .catch(() => {});
    read();
    const timer = setInterval(read, 200);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [session?.id, selected, controlled]);
  useEffect(() => {
    historyReplace(selected);
    inspector.current?.scrollTo(0,0);
  }, [selected]);
  useEffect(() => {
    if (!directoryOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") showDirectory(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [directoryOpen]);
  useEffect(() => {
    const onHash = () => {
      const id = canonicalLessonId(location.hash.slice(1));
      if (
        id &&
        id !== selection.current &&
        courses.some((c) => c.lessons.some((l) => l.id === id))
      )
        void changeLesson(id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  });
  function historyReplace(id: string) {
    window.history.replaceState(null, "", `#${id}`);
  }
  function showDirectory(open: boolean) {
    setDirectoryOpen(open);
    if (!open)
      document
        .getElementById("directory-toggle")
        ?.focus({ preventScroll: true });
    try {
      localStorage.setItem("robotics-lab.directory-open.v1", String(open));
    } catch {
      /* 目录仍可正常展开和收起。 */
    }
  }
  async function perform(name: string, action: () => Promise<void>) {
    setBusy(name);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  async function changeLesson(id: string) {
    if (id === selected || busy) return;
    await perform("switch", () => systemRequests.change(async change => {
      if (session) await request("/api/sessions/current", { method: "DELETE" });
      systemRequests.update(prev => prev ? { ...prev, session: null } : prev, change);
      setSelected(id);
      setSettings(
        defaults(
          courses.flatMap((c) => c.lessons).find((l) => l.id === id),
        ),
      );
      dispatchObservation({ type: "clear" });
      setRun(null);
      setJoint(defaultJoint(courses.flatMap((c) => c.lessons).find((l) => l.id === id)?.mode ?? ""));
      setMotionJoint(1);
      actions.current = [];
      if (window.matchMedia("(max-width: 1100px)").matches)
        showDirectory(false);
      window.scrollTo(0, 0);
    }));
  }
  async function command(action: string, extra = {}, id = session?.id) {
    if (!id) throw new Error("请先打开交互实验");
    const result = await request<RobotObservation>(
      "/api/sessions/current/commands",
      post({ session_id: id, action, settings: humanoid ? settings.humanoid : settings, ...extra }),
    );
    actions.current.push({
      action,
      time: result.time,
      settings: { ...settings },
      ...extra,
    });
    dispatchObservation({ type: "receive", observation: result,
      restartHistory: NEW_TRIAL_ACTIONS.has(action) });
    return result;
  }
  async function openExperiment() {
    await perform("open", () => systemRequests.change(async change => {
      const created = await request<Session>(
        "/api/sessions",
        post({ experiment_id: lesson!.experiment_id }),
      );
      systemRequests.update(prev => prev ? { ...prev, session: created } : prev, change);
      if (!controlled) return;
      dispatchObservation({ type: "session", sessionId: created.id });
      for (let i = 0; i < 100; i++) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        const info = await systemRequests.read({ change });
        if (!info) throw new Error("会话操作已失效");
        if (info.session?.id !== created.id) throw new Error("实验会话已改变");
        if (info.session.status === "failed")
          throw new Error(info.session.error || "仿真启动失败");
        if (info.session.status === "ready") {
          await command("configure", {}, created.id);
          return;
        }
      }
      throw new Error("仿真启动超时");
    }));
  }
  async function closeExperiment() {
    await perform("stop", () => systemRequests.change(async change => {
      await request("/api/sessions/current", { method: "DELETE" });
      systemRequests.update(prev => prev ? { ...prev, session: null } : prev, change);
      dispatchObservation({ type: "session", sessionId: null });
    }));
  }
  async function control(action: string) {
    await perform(action, async () => {
      if (action === "grasp") await command("configure");
      const result = await command(
        action,
        action === "pause" ? { paused: !state?.paused } : {},
      );
      if (action === "reset") {
        setSettings(defaults(lesson));
        setJoint(defaultJoint(mode));
        setMotionJoint(1);
      }
      if ((action === "gravity-release" || action === "gravity-hold") && "compensation" in result) {
        setSettings({ ...defaults(lesson), compensation: result.compensation });
      }
    });
  }
  function toggleCompleted() {
    const next = completed.includes(selected)
      ? completed.filter((id) => id !== selected)
      : [...completed, selected];
    setCompleted(next);
    try {
      localStorage.setItem("robotics-lab.completed", JSON.stringify(next));
    } catch {
      /* 学习页面仍可使用 */
    }
  }
  function exportLive() {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            lesson_id: selected,
            session_id: session?.id,
            actions: actions.current,
            observations: history,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
      anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${selected}-observations.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="app">
      <header className="topbar">
        <button
          className="button directory-toggle"
          id="directory-toggle"
          aria-expanded={directoryOpen}
          aria-controls="course-directory"
          onClick={() => showDirectory(!directoryOpen)}
        >
          <span aria-hidden="true">☰</span> 课程目录
        </button>
        <a
          className="brand"
          href="#panda-structure"
          onClick={(e) => {
            e.preventDefault();
            void changeLesson("panda-structure");
          }}
        >
          ROBOTICS<span>LAB</span>
        </a>
        <span className="product-name">机器人交互实验室</span>
        <span className="runtime">
          {system
            ? `${system.viewer.platform} · MuJoCo ${system.viewer.mujoco}`
            : "检查运行环境…"}
        </span>
      </header>
      <div className="layout" data-directory-open={directoryOpen}>
        {directoryOpen && (
          <button
            className="directory-backdrop"
            aria-label="收起课程目录"
            onClick={() => showDirectory(false)}
          />
        )}
        <aside
          className="sidebar"
          id="course-directory"
          hidden={!directoryOpen}
          aria-label="课程目录"
        >
          <p className="eyebrow">交互课程</p>
          <h2>
            在实验中理解
            <br />
            机器人的运动。
          </h2>
          <label className="course-label" htmlFor="course">
            课程目录
          </label>
          <select
            id="course"
            aria-label="选择课程"
            value={course?.id || ""}
            disabled={!!busy}
            onChange={(e) =>
              void changeLesson(
                courses.find((c) => c.id === e.target.value)!.lessons[0].id,
              )
            }
          >
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <p className="course-subtitle">{course?.subtitle}</p>
          <nav aria-label="课时目录">
            {course?.lessons.map((item, n) => (
              <button
                key={item.id}
                className={`lesson-link ${item.id === selected ? "selected" : ""}`}
                disabled={!!busy}
                aria-current={item.id === selected ? "step" : undefined}
                onClick={() => void changeLesson(item.id)}
              >
                <span className="lesson-number">
                  {completed.includes(item.id)
                    ? "✓"
                    : String(n + 1).padStart(2, "0")}
                </span>
                <span>{item.title}</span>
              </button>
            ))}
          </nav>
          <div className="course-progress">
            <span>已标记完成</span>
            <strong>
              {course?.lessons.filter((l) => completed.includes(l.id)).length ||
                0}{" "}
              / {course?.lessons.length || 0}
            </strong>
          </div>
          <p className="sidebar-note">
            按课时学习，也可以直接进入感兴趣的实验。切换课时会结束当前交互会话。
          </p>
          <div className="sidebar-footer">
            原理 · 操作 · 观测 · 分析
            <br />
            Robotics Lab v{system?.version || "0.2.0"}
          </div>
        </aside>
        <main className="course-main">
          <div className="breadcrumb">
            {course?.title}
            <span>/</span>第 {index + 1} 课
            <span className="level">{course?.level}</span>
          </div>
          <div className="lesson-heading">
            <div>
              <p className="eyebrow">
                LESSON {String(index + 1).padStart(2, "0")}
              </p>
              <h1>{lesson?.title || "正在加载课程"}</h1>
              <p>{lesson?.summary}</p>
            </div>
            <div className="lesson-actions">
              <div className="lesson-navigation" aria-label="切换课时">
                <button
                  className="button small"
                  disabled={index <= 0 || !!busy}
                  onClick={() =>
                    void changeLesson(course!.lessons[index - 1].id)
                  }
                >
                  ← 上一课
                </button>
                <button
                  className="button small"
                  disabled={
                    !course || index === course.lessons.length - 1 || !!busy
                  }
                  onClick={() =>
                    void changeLesson(course!.lessons[index + 1].id)
                  }
                >
                  下一课 →
                </button>
              </div>
              <button
                className="text-button theory-link"
                onClick={() => {
                  const theory = document.getElementById("lesson-theory");
                  theory?.scrollIntoView({ block: "start" });
                  theory?.focus({ preventScroll: true });
                }}
              >
                原理与操作步骤 ↓
              </button>
              <button
                className={`button completion ${completed.includes(selected) ? "done" : ""}`}
                onClick={toggleCompleted}
              >
                {completed.includes(selected) ? "✓ 已标记完成" : "标记本课完成"}
              </button>
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <div className="lesson-content">
            <section className="lab" aria-label="交互实验">
              <div className="experiment-workspace" data-has-inspector={controlled}>
                <div className="panel viewer-panel">
                  <div className="panel-heading">
                    <div>
                      <span className={`indicator ${ready ? "ready" : ""}`} />
                      <strong>
                        {ready
                          ? "交互实验已就绪"
                          : session?.status === "starting"
                            ? "正在加载仿真"
                            : "交互实验"}
                      </strong>
                    </div>
                    <div className="toolbar">
                      {ready && (
                        <a href={viewerUrl} target="_blank" rel="noreferrer">
                          独立窗口 ↗
                        </a>
                      )}
                      {session ? (
                        <button
                          className="button small"
                          disabled={!!busy}
                          onClick={() => void closeExperiment()}
                        >
                          结束实验
                        </button>
                      ) : (
                        <button
                          className="button primary small"
                          disabled={
                            !!busy || !system?.viewer.available || !lesson
                          }
                          onClick={() => void openExperiment()}
                        >
                          {busy === "open" ? "正在启动…" : "打开交互实验"}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="viewer-surface">
                    {ready ? (
                      <iframe
                        title="官方交互仿真窗口"
                        src={viewerUrl}
                        allow="fullscreen"
                      />
                    ) : (
                      <div className="viewer-placeholder">
                        <div className="axis-graphic">
                          <span>X</span>
                          <span>Y</span>
                          <span>Z</span>
                        </div>
                        <h3>
                          {panda
                            ? "Panda 机械臂实验工作台"
                            : humanoid ? "G1 人形机器人实验工作台"
                            : "基础物理实验工作台"}
                        </h3>
                        <p>
                          {session?.error ||
                            (system?.viewer.available
                              ? "打开三维场景，将本课原理与实际观测对应。"
                              : system?.viewer.reason || "正在检查运行组件…")}
                        </p>
                      </div>
                    )}
                  </div>
                  <p className="viewer-caption">
                    {controlled
                      ? GEOMETRIC.includes(mode)
                        ? "几何实验 · 直接更新构型与运动学观测"
                        : "动力学实验 · 执行器、重力与接触共同决定运动"
                      : "使用官方窗口中的暂停、步进和初态恢复控件"}
                    {controlled && <span>高级面板可从查看器 View 菜单展开</span>}
                  </p>
                </div>
                {controlled && (
                  <aside
                    ref={inspector}
                    className="experiment-inspector"
                    aria-label="实验观测与参数"
                  >
                    {mode === "jacobian" && controlPanel}
                    {humanoid ? <HumanoidReadings mode={mode} state={humanoidLatest} live={!!state} /> : <Readings
                      state={pandaLatest ?? undefined}
                      mode={mode}
                      live={!!state}
                      joint={mode === "jacobian" ? motionJoint : joint}
                    />}
                    {mode !== "jacobian" && controlPanel}
                  </aside>
                )}
              </div>
              {humanoid && <HumanoidActions mode={mode} ready={ready} busy={!!busy}
                paused={!!state?.paused} act={action => void control(action)} />}
              {panda && (
                <ExperimentActions
                  mode={mode}
                  ready={ready}
                  busy={!!busy}
                  paused={!!state?.paused}
                  act={(action) => void control(action)}
                />
              )}
              {controlled && (
                <div className="panel live-chart">
                  <div className="panel-heading">
                    <h3>交互过程记录</h3>
                    <div className="toolbar">
                      {panda && mode !== "structure" && mode !== "grasp" && mode !== "jacobian" && (
                        <select
                          aria-label="曲线关节"
                          value={joint}
                          onChange={(e) => setJoint(+e.target.value)}
                        >
                          {HOME.map((_, i) => (
                            <option key={i} value={i}>
                              关节 {i + 1}
                            </option>
                          ))}
                        </select>
                      )}
                      <button
                        className="text-button"
                        disabled={!history.length}
                        onClick={exportLive}
                      >
                        导出观测 ↗
                      </button>
                    </div>
                  </div>
                  {humanoid ? <HumanoidChart key={selected} mode={mode} samples={history} /> : <Chart
                    samples={history.map((s) => ({
                      ...s,
                      cube_height: "cube_position" in s ? s.cube_position[2] : 0,
                    }))}
                    joint={joint}
                    mode={mode}
                  />}
                  <p className="panel-note">
                    记录当前交互会话最近的观测；暂停与恢复初态可用于对照。
                  </p>
                </div>
              )}
            </section>
            {lesson && <Theory lesson={lesson} />}
            <div className="panel independent">
              <div className="panel-heading">
                <div>
                  <p className="section-label">独立数值验证</p>
                  <h3>从预设初态重新计算</h3>
                </div>
                <button
                  className="button"
                  disabled={!!busy || !lesson}
                  onClick={() =>
                    void perform("run", async () => {
                      setRun(null);
                      setRun(
                        await request<Run>(
                          "/api/runs",
                          post({
                            experiment_id: lesson!.experiment_id,
                            settings: humanoid ? settings.humanoid : panda ? settings : null,
                          }),
                        ),
                      );
                    })
                  }
                >
                  {busy === "run" ? "正在计算…" : "运行独立验证"}
                </button>
              </div>
              <p className="panel-note">
                使用本页参数和本课预设初态，单独计算一次；结果不读取或改变上方交互会话。
              </p>
              {run && (
                <>
                  {humanoid ? <HumanoidChart key={selected} mode={mode} samples={run.samples} /> : <Chart
                    samples={run.samples}
                    joint={joint}
                    mode={mode}
                    unit={run.experiment.observable_unit}
                  />}
                  <div className="metrics">
                    {Object.entries(run.metrics).map(([key, value]) => (
                      <div key={key}>
                        <span>{LABELS[key] || key}</span>
                        <strong>
                          {Number.isInteger(value)
                            ? value
                            : value.toPrecision(5)}
                        </strong>
                      </div>
                    ))}
                  </div>
                  <a
                    className="download"
                    href={`/api/runs/${run.id}`}
                    download={`${selected}-${run.id}.json`}
                  >
                    下载本次数值记录 ↗
                  </a>
                </>
              )}
            </div>
          </div>
          <footer className="lesson-footer">
            <button
              className="button"
              disabled={index <= 0 || !!busy}
              onClick={() => void changeLesson(course!.lessons[index - 1].id)}
            >
              ← 上一课
            </button>
            <span>
              第 {index + 1} / {course?.lessons.length || 0} 课
            </span>
            <button
              className="button"
              disabled={
                !course || index === course.lessons.length - 1 || !!busy
              }
              onClick={() => void changeLesson(course!.lessons[index + 1].id)}
            >
              下一课 →
            </button>
          </footer>
        </main>
      </div>
    </div>
  );
}
