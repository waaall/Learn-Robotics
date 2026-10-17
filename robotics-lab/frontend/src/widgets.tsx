import katex from "katex";
import {
  HOME,
  LIMITS,
  num,
  type Lesson,
  type Observation,
  type Sample,
  type Settings,
} from "./types";

export function Theory({ lesson }: { lesson: Lesson }) {
  return (
    <article
      className="theory"
      id="lesson-theory"
      tabIndex={-1}
      aria-label="原理讲解"
    >
      <div className="question">
        <span className="section-label">本课问题</span>
        <h3>{lesson.question}</h3>
        <p>前置知识：{lesson.prerequisites}</p>
      </div>
      {lesson.concepts.map((c, i) => (
        <section className="concept" key={c.title}>
          <p className="section-label">原理 {i + 1}</p>
          <h3>{c.title}</h3>
          <p>{c.text}</p>
          <div
            className="formula"
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(c.formula, {
                displayMode: true,
                throwOnError: false,
                strict: false,
                trust: false,
              }),
            }}
          />
        </section>
      ))}
      <section className="lesson-section">
        <p className="section-label">操作步骤</p>
        <ol>
          {lesson.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      </section>
      <section className="lesson-section">
        <p className="section-label">观察与分析</p>
        <ul>
          {lesson.observations.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </section>
      <section className="exercise">
        <span className="section-label">尝试与思考</span>
        <p>{lesson.exercise}</p>
      </section>
      <details className="sources">
        <summary>来源与适用条件</summary>
        <p>模型与算法在本课场景、初态和参数下使用。改变条件后需重新验证。</p>
        {lesson.sources.map((s) => (
          <a key={s.url} href={s.url} target="_blank" rel="noreferrer">
            {s.title} ↗
          </a>
        ))}
      </details>
    </article>
  );
}
export function Matrix({ values }: { values: number[][] }) {
  return (
    <div className="matrix-wrap">
      <table className="matrix">
        <tbody>
          {values.map((row, i) => (
            <tr key={i}>
              {row.map((v, j) => (
                <td key={j}>{num(v, 3)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Chart({
  samples,
  joint,
  mode,
  unit = "rad",
}: {
  samples: Sample[];
  joint: number;
  mode: string;
  unit?: string;
}) {
  if (samples.length < 2)
    return <div className="empty-chart">运行实验后显示观测曲线。</div>;
  const cube = mode === "grasp";
  const series = [
    samples.map((s) =>
      cube
        ? (s.cube_height ?? s.cube_position?.[2] ?? 0)
        : (s.joints?.[joint] ?? s.value ?? 0),
    ),
  ];
  if (
    ["joint-control", "trajectory"].includes(mode) &&
    samples[0].reference_joints
  )
    series.push(samples.map((s) => s.reference_joints?.[joint] ?? 0));
  const all = series.flat(),
    lo = Math.min(...all),
    hi = Math.max(...all),
    span = Math.max(hi - lo, 0.02);
  const t0 = samples[0].time,
    t1 = samples.at(-1)!.time,
    elapsed = Math.max(t1 - t0, 0.001);
  return (
    <div className="chart">
      <div className="chart-caption">
        <span>
          {cube
            ? "方块高度 / m"
            : mode === "physics"
              ? `观测量 / ${unit}`
              : `关节 ${joint + 1} / rad`}
        </span>
        <span>
          <i />
          实际值{" "}
          {series.length > 1 && (
            <>
              <i className="reference" />
              参考值
            </>
          )}
        </span>
      </div>
      <svg
        viewBox="0 0 640 170"
        role="img"
        aria-label={cube ? "方块实际高度曲线" : "实际状态与参考曲线"}
      >
        {[30, 85, 140].map((y) => (
          <path key={y} d={`M45 ${y}H625`} className="chart-grid" />
        ))}
        {series.map((values, k) => (
          <path
            key={k}
            className={`trace ${k ? "reference-trace" : ""}`}
            d={values
              .map(
                (v, i) =>
                  `${i ? "L" : "M"}${45 + ((samples[i].time - t0) / elapsed) * 580},${135 - ((v - lo) / span) * 100}`,
              )
              .join(" ")}
          />
        ))}
        <text x="4" y="35">
          {hi.toFixed(2)}
        </text>
        <text x="4" y="140">
          {lo.toFixed(2)}
        </text>
        <text x="45" y="163">
          {t0.toFixed(1)} s
        </text>
        <text x="570" y="163">
          {t1.toFixed(1)} s
        </text>
      </svg>
    </div>
  );
}
type ControlsProps = {
  mode: string;
  settings: Settings;
  set: (value: Settings) => void;
  joint: number;
  setJoint: (n: number) => void;
};
export function Controls({
  mode,
  settings: s,
  set,
  joint,
  setJoint,
}: ControlsProps) {
  const update = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    set({ ...s, [key]: value });
  return (
    <div className="panel controls">
      <div className="panel-heading">
        <h3>实验参数</h3>
        <span className="unit-note">角度 rad · 长度 m</span>
      </div>
      {["structure", "fk", "jacobian", "joint-control", "trajectory"].includes(
        mode,
      ) && (
        <div className="joint-controls">
          {s.joints.map((v, i) => (
            <label className="range-row" key={i}>
              <span title={`限位 ${LIMITS[i][0]} 至 ${LIMITS[i][1]} rad`}>
                关节 {i + 1}
              </span>
              <input
                aria-label={`关节 ${i + 1} 目标角度`}
                type="range"
                min={LIMITS[i][0]}
                max={LIMITS[i][1]}
                step="any"
                value={v}
                onChange={(e) =>
                  update(
                    "joints",
                    s.joints.map((q, j) => (j === i ? +e.target.value : q)),
                  )
                }
              />
              <input
                className="joint-number"
                aria-label={`关节 ${i + 1} 角度数值`}
                type="number"
                min={LIMITS[i][0]}
                max={LIMITS[i][1]}
                step="0.01"
                value={Number(v.toFixed(5))}
                onChange={(e) =>
                  update(
                    "joints",
                    s.joints.map((q, j) => (j === i ? +e.target.value : q)),
                  )
                }
              />
            </label>
          ))}
        </div>
      )}
      {["structure", "fk", "joint-control"].includes(mode) && (
        <label className="range-row">
          <span>夹爪开口</span>
          <input
            aria-label="夹爪目标开口"
            type="range"
            min="0"
            max="0.08"
            step="0.001"
            value={s.gripper_width}
            onChange={(e) => update("gripper_width", +e.target.value)}
          />
          <output>{num(s.gripper_width, 3)}</output>
        </label>
      )}
      {mode === "ik" && (
        <div className="target-controls">
          {["X", "Y", "Z"].map((axis, i) => (
            <label key={axis}>
              目标 {axis} / m
              <input
                aria-label={`末端目标 ${axis}`}
                type="number"
                min="-2"
                max="2"
                step="0.01"
                value={s.target[i]}
                onChange={(e) =>
                  update(
                    "target",
                    s.target.map((v, j) => (j === i ? +e.target.value : v)),
                  )
                }
              />
            </label>
          ))}
        </div>
      )}
      {["joint-control", "trajectory"].includes(mode) && (
        <label className="range-row">
          <span>增益倍率</span>
          <input
            aria-label="增益倍率"
            type="range"
            min="0.05"
            max="1.5"
            step="0.05"
            value={s.gain_scale}
            onChange={(e) => update("gain_scale", +e.target.value)}
          />
          <output>{s.gain_scale.toFixed(2)}</output>
        </label>
      )}
      {["joint-control", "trajectory", "gravity"].includes(mode) && (
        <label className="check">
          <input
            type="checkbox"
            checked={s.compensation}
            onChange={(e) => update("compensation", e.target.checked)}
          />
          开启重力补偿
        </label>
      )}
      {mode === "jacobian" && (
        <div className="velocity-controls">
          <label>
            运动关节
            <select
              aria-label="速度输入关节"
              value={joint}
              onChange={(e) => {
                setJoint(+e.target.value);
                update("velocity", Array(7).fill(0));
              }}
            >
              {HOME.map((_, i) => (
                <option key={i} value={i}>
                  关节 {i + 1}
                </option>
              ))}
            </select>
          </label>
          <label className="range-row">
            <span>速度 rad/s</span>
            <input
              aria-label="关节速度"
              type="range"
              min="-0.2"
              max="0.2"
              step="0.01"
              value={s.velocity[joint]}
              onChange={(e) =>
                update(
                  "velocity",
                  HOME.map((_, i) => (i === joint ? +e.target.value : 0)),
                )
              }
            />
            <output>{s.velocity[joint].toFixed(2)}</output>
          </label>
        </div>
      )}
      {mode === "trajectory" && (
        <label className="select-row">
          轨迹插值
          <select
            aria-label="轨迹插值"
            value={s.profile}
            onChange={(e) => update("profile", e.target.value)}
          >
            <option value="quintic">五次插值 · 3 s</option>
            <option value="linear">线性插值 · 3 s</option>
          </select>
        </label>
      )}
      {mode === "grasp" && (
        <>
          <p className="control-description">
            任务依次控制接近、夹持、抬升与放置。方块通过实际接触运动。
          </p>
          <label className="range-row">
            <span>滑动摩擦</span>
            <input
              aria-label="抓取滑动摩擦系数"
              type="range"
              min="0.02"
              max="2"
              step="0.02"
              value={s.friction}
              onChange={(e) => update("friction", +e.target.value)}
            />
            <output>{s.friction.toFixed(2)}</output>
          </label>
        </>
      )}
      <p className="control-hint">调整参数后，使用实验区下方的操作按钮应用。</p>
    </div>
  );
}
export function ExperimentActions({
  mode,
  ready,
  busy,
  paused,
  act,
}: {
  mode: string;
  ready: boolean;
  busy: boolean;
  paused: boolean;
  act: (action: string) => void;
}) {
  return (
    <div className="panel experiment-actions" aria-label="仿真操作">
      <div className="control-actions">
        <button
          className="button primary"
          disabled={busy || !ready}
          onClick={() =>
            act(mode === "trajectory" ? "trajectory" : "configure")
          }
        >
          {mode === "ik"
            ? "求解并显示构型"
            : mode === "trajectory"
              ? "执行轨迹"
              : "应用参数"}
        </button>
        {mode === "grasp" && (
          <button
            className="button"
            disabled={busy || !ready}
            onClick={() => act("grasp")}
          >
            执行抓取
          </button>
        )}
        <button
          className="button"
          disabled={busy || !ready}
          onClick={() => act("reset")}
        >
          恢复初态
        </button>
        <button
          className="button"
          disabled={busy || !ready}
          onClick={() => act("pause")}
        >
          {paused ? "继续" : "暂停"}
        </button>
        <button
          className="button"
          disabled={busy || !ready}
          onClick={() => act("step")}
        >
          单步 1 ms
        </button>
      </div>
      {!ready && (
        <p className="control-hint">参数可预先调整；打开交互实验后应用。</p>
      )}
    </div>
  );
}
export function Readings({
  state: s,
  mode,
  live,
}: {
  state?: Observation;
  mode: string;
  live: boolean;
}) {
  if (!s)
    return (
      <div className="panel readings">
        <div className="panel-heading">
          <h3>实时观测</h3>
          <span className="unit-note">等待实验数据</span>
        </div>
        <p className="panel-note">
          打开交互实验后，这里显示本课的实际状态与观测结果。
        </p>
      </div>
    );
  return (
    <div className="panel readings">
      <div className="panel-heading">
        <h3>{live ? "实时观测" : "独立验证末态"}</h3>
        <span className="unit-note">
          {live && s.age_seconds > 2
            ? "数据暂未更新"
            : `仿真时间 ${num(s.time, 2)} s`}
        </span>
      </div>
      <div className="readings-grid">
        <div>
          <span>末端世界位置 / m</span>
          <strong>{s.tool_position.map((v) => num(v, 3)).join(" · ")}</strong>
        </div>
        <div>
          <span>夹爪实际开口 / m</span>
          <strong>{num(s.gripper_width, 4)}</strong>
        </div>
        {["joint-control", "trajectory"].includes(mode) && (
          <div>
            <span>参考跟踪误差 / rad</span>
            <strong>
              {num(
                Math.hypot(
                  ...s.joints.map((q, i) => q - s.reference_joints[i]),
                ),
              )}
            </strong>
          </div>
        )}
      </div>
      {mode === "ik" && s.ik && (
        <div
          className={`solver-state ${s.ik.converged ? "success" : "warning"}`}
        >
          {s.ik.converged ? "位置求解已收敛" : "位置求解未收敛"} ·{" "}
          {s.ik.iterations} 次迭代 · 误差 {num(s.ik.position_error_m * 1000, 3)}{" "}
          mm
        </div>
      )}
      {mode === "grasp" && (
        <div className="task-state">
          <strong>{s.phase}</strong>
          <p>
            接触数 {s.contacts} · 已抬升：{s.grasp_lifted ? "是" : "否"} ·
            放置成功：{s.place_success ? "是" : "尚未满足条件"}
          </p>
          <p>
            方块位置 / m：{s.cube_position.map((v) => num(v, 3)).join(" · ")}
          </p>
        </div>
      )}
      {["structure", "fk", "ik"].includes(mode) && (
        <details>
          <summary>末端旋转矩阵 R</summary>
          <Matrix values={s.tool_rotation} />
        </details>
      )}
      {mode === "jacobian" && (
        <>
          <p className="reading-line">
            奇异值：{s.singular_values.map((v) => num(v, 4)).join(" · ")}
          </p>
          <details>
            <summary>平移雅可比 J · 世界坐标系</summary>
            <Matrix values={s.jacobian} />
          </details>
          <p className="reading-line">
            末端速度 / m·s⁻¹：
            {s.cartesian_velocity.map((v) => num(v, 4)).join(" · ")}
          </p>
        </>
      )}
      {["joint-control", "gravity", "trajectory"].includes(mode) && (
        <details>
          <summary>关节角度、执行器力矩与重力项</summary>
          <div className="matrix-wrap">
            <table className="joint-table">
              <thead>
                <tr>
                  <th>关节</th>
                  <th>实际 rad</th>
                  <th>执行器 N·m</th>
                  <th>重力项 N·m</th>
                </tr>
              </thead>
              <tbody>
                {s.joints.map((q, i) => (
                  <tr key={i}>
                    <th>{i + 1}</th>
                    <td>{num(q, 3)}</td>
                    <td>{num(s.actuator_torque[i], 2)}</td>
                    <td>{num(s.gravity_torque[i], 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
