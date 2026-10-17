import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Experiment = {
  id: string;
  title: string;
  topic: string;
  robot: string;
  summary: string;
  explanation: string;
  observations: string[];
  observable_name: string;
  observable_unit: string;
  duration: number;
};
type Session = {
  id: string;
  experiment_id: string;
  port: number;
  status: string;
  error: string | null;
};
type System = {
  version: string;
  viewer: {
    available: boolean;
    reason: string;
    platform: string;
    mujoco: string;
  };
  session: Session | null;
};
type Run = {
  id: string;
  duration: number;
  metrics: Record<string, number>;
  samples: { time: number; value: number }[];
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : `请求失败（${response.status}）`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

function SceneSketch({ id }: { id: string }) {
  return (
    <svg viewBox="0 0 100 72" aria-hidden="true">
      <path
        d="M10 60H90M18 57V63M36 57V63M54 57V63M72 57V63"
        className="sketch-ground"
      />
      {id === "pendulum" ? (
        <>
          <path d="M48 12L63 51" className="sketch-link" />
          <circle cx="48" cy="12" r="4" />
          <path d="M48 20V49M48 40Q53 40 58 37" className="sketch-guide" />
        </>
      ) : (
        <>
          <circle cx="50" cy="25" r="11" />
          <path d="M50 42V52M46 48L50 53L54 48" className="sketch-guide" />
        </>
      )}
    </svg>
  );
}

function Trace({ run, unit }: { run: Run; unit: string }) {
  const values = run.samples.map((sample) => sample.value);
  const lo = Math.min(...values),
    hi = Math.max(...values),
    span = Math.max(hi - lo, 0.001);
  const end = run.samples.at(-1)?.time || 1;
  const path = run.samples
    .map(
      (sample, index) =>
        `${index ? "L" : "M"}${(24 + (sample.time / end) * 650).toFixed(2)},${(148 - ((sample.value - lo) / span) * 115).toFixed(2)}`,
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 700 185"
      role="img"
      aria-label={`独立数值验证曲线，单位 ${unit}`}
    >
      {[33, 90, 148].map((y) => (
        <path key={y} d={`M24 ${y}H675`} className="chart-grid" />
      ))}
      <path d={path} className="trace" />
      <text x="24" y="177">
        0 s
      </text>
      <text x="625" y="177">
        {end.toFixed(2)} s
      </text>
      <text x="26" y="21">
        {hi.toPrecision(4)} {unit}
      </text>
    </svg>
  );
}

function App() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedId, setSelectedId] = useState("pendulum");
  const [system, setSystem] = useState<System | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      request<Experiment[]>("/api/catalog", { signal: controller.signal }),
      request<System>("/api/system", { signal: controller.signal }),
    ])
      .then(([items, state]) => {
        setExperiments(items);
        setSystem(state);
        if (state.session) setSelectedId(state.session.experiment_id);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason));
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const interval = window.setInterval(() => {
      request<System>("/api/system", { signal: controller.signal })
        .then(setSystem)
        .catch(() => {});
    }, 2000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, []);
  const selected = experiments.find((item) => item.id === selectedId);
  const session = system?.session;
  const viewerUrl = session
    ? `${window.location.protocol}//${window.location.hostname}:${session.port}/`
    : undefined;
  const active = session?.status === "ready" || session?.status === "starting";

  async function perform(name: string, action: () => Promise<void>) {
    setBusy(name);
    setError("");
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }
  function startViewer() {
    void perform("viewer", async () => {
      const created = await request<Session>("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ experiment_id: selectedId }),
      });
      setSystem((previous) =>
        previous ? { ...previous, session: created } : previous,
      );
    });
  }
  function stopViewer() {
    void perform("stop", async () => {
      await request<void>("/api/sessions/current", { method: "DELETE" });
      setSystem((previous) =>
        previous ? { ...previous, session: null } : previous,
      );
    });
  }
  function simulate() {
    void perform("run", async () => {
      setRun(null);
      setRun(
        await request<Run>("/api/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ experiment_id: selectedId }),
        }),
      );
    });
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/">
          ROBOTICS<span>LAB</span>
        </a>
        <span className="product-name">机器人交互实验室</span>
        <span className="runtime">
          {system
            ? `${system.viewer.platform} · MuJoCo ${system.viewer.mujoco}`
            : "正在检查环境"}
        </span>
      </header>
      <main className="workspace">
        <aside className="catalog">
          <p className="eyebrow">实验目录</p>
          <h1>
            从物理现象
            <br />
            研究机器人。
          </h1>
          <p className="muted">选择实验，观察运动、受力与数值结果。</p>
          <nav aria-label="实验选择">
            {experiments.map((item) => (
              <button
                key={item.id}
                className={`experiment-card ${item.id === selectedId ? "selected" : ""}`}
                disabled={active || !!busy}
                aria-pressed={item.id === selectedId}
                onClick={() => {
                  setSelectedId(item.id);
                  setRun(null);
                  setError("");
                }}
              >
                <SceneSketch id={item.id} />
                <span>
                  <small>{item.topic}</small>
                  <strong>{item.title}</strong>
                  <span>{item.robot}</span>
                </span>
              </button>
            ))}
          </nav>
          <div className="catalog-note">
            <strong>首版框架</strong>
            <p>
              已接入两项基础实验。机器人模型库与控制、AI 策略实验将在后续适配。
            </p>
            {active ? <p>结束当前交互会话后可切换实验。</p> : null}
          </div>
        </aside>
        <section className="experiment" aria-label="实验工作区">
          <div className="experiment-heading">
            <div>
              <p className="eyebrow">{selected?.topic || "加载实验"}</p>
              <h2>{selected?.title || "正在载入目录"}</h2>
              <p>{selected?.summary}</p>
            </div>
            <span className="tag">{selected?.duration ?? "—"} s 默认时长</span>
          </div>
          {error ? (
            <div className="error" role="alert">
              {error}
            </div>
          ) : null}
          <div className="viewer-toolbar">
            <span>
              <i
                className={
                  session?.status === "ready" ? "indicator ready" : "indicator"
                }
              />
              {session?.status === "ready"
                ? "交互会话已就绪"
                : session?.status === "starting"
                  ? "正在启动交互会话"
                  : "交互仿真"}
            </span>
            <div>
              {session?.status === "ready" ? (
                <a
                  className="viewer-link"
                  href={viewerUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  独立窗口 ↗
                </a>
              ) : null}
              {session ? (
                <button
                  className="button"
                  disabled={!!busy}
                  onClick={stopViewer}
                >
                  结束会话
                </button>
              ) : (
                <button
                  className="button primary"
                  disabled={!system?.viewer.available || !!busy || !selected}
                  onClick={startViewer}
                >
                  打开交互仿真
                </button>
              )}
            </div>
          </div>
          <div className="viewer-surface">
            {session?.status === "ready" ? (
              <iframe
                title="官方交互仿真窗口"
                src={viewerUrl}
                allow="fullscreen"
              />
            ) : (
              <div className="viewer-placeholder">
                <span className="axis-mark" aria-hidden="true">
                  ↗
                </span>
                <h3>
                  {session?.status === "starting"
                    ? "正在准备仿真窗口"
                    : "在三维场景中操作实验"}
                </h3>
                <p>
                  {session?.error ||
                    (system?.viewer.available
                      ? "打开后可在窗口中暂停、单步、调整关节及恢复初态。"
                      : system?.viewer.reason || "正在检查交互仿真组件。")}
                </p>
                <span className="subtle">
                  下方数值验证可独立运行，并保存结果。
                </span>
              </div>
            )}
          </div>
          <section className="results">
            <div className="section-heading">
              <div>
                <p className="eyebrow">独立数值验证</p>
                <h3>{selected?.observable_name || "观测量"}</h3>
              </div>
              <button
                className="button"
                disabled={!!busy || !selected}
                onClick={simulate}
              >
                {busy === "run" ? "正在计算…" : "运行数值验证"}
              </button>
            </div>
            <p className="muted">
              从预设初态重新计算，不读取上方交互会话的修改。
            </p>
            {run && selected ? (
              <>
                <Trace run={run} unit={selected.observable_unit} />
                <div className="metrics">
                  {Object.entries(run.metrics).map(([key, value]) => (
                    <div key={key}>
                      <span>
                        {(
                          {
                            steps: "积分步数",
                            final_time: "仿真时间 / s",
                            final_speed: "末态广义速度范数",
                            max_energy_drift_J: "最大能量变化 / J",
                            mean_support_N: "末段平均支撑 / N",
                            max_penetration_m: "最大穿透 / m",
                          } as Record<string, string>
                        )[key] || key}
                      </span>
                      <strong>
                        {Number.isInteger(value) ? value : value.toPrecision(5)}
                      </strong>
                    </div>
                  ))}
                </div>
                <a
                  className="download"
                  href={`/api/runs/${run.id}`}
                  download={`${selectedId}-${run.id}.json`}
                >
                  下载本次实验记录 ↗
                </a>
              </>
            ) : (
              <div className="empty-trace">
                运行后显示真实计算曲线、指标与可下载记录。
              </div>
            )}
          </section>
        </section>
        <aside className="lesson">
          <p className="eyebrow">实验说明</p>
          <h3>观察什么</h3>
          <p className="explanation">{selected?.explanation}</p>
          <ol>
            {selected?.observations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
          <div className="lesson-note">
            <h4>状态与运动</h4>
            <p>
              直接编辑关节位置会改变系统状态。执行器输入和外力则通过动力学影响后续运动。
            </p>
          </div>
          <div className="lesson-note">
            <h4>结果的适用条件</h4>
            <p>
              数值结果对应预设模型、初态和步长。修改条件后，需要重新运行与比较。
            </p>
          </div>
          <p className="version">
            Robotics Lab v{system?.version || "0.1.0"}
            <br />
            本地实验工作台
          </p>
        </aside>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
