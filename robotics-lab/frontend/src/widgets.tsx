import katex from "katex";
import { useId } from "react";
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
export function Matrix({
  values,
  highlightColumn,
}: {
  values: number[][];
  highlightColumn?: number;
}) {
  return (
    <div className="matrix-wrap">
      <table className="matrix">
        {highlightColumn !== undefined && (
          <thead>
            <tr>
              <th>世界轴</th>
              {values[0].map((_, i) => (
                <th
                  key={i}
                  className={
                    i === highlightColumn ? "active-column" : undefined
                  }
                >
                  q{i + 1}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {values.map((row, i) => (
            <tr key={i}>
              {highlightColumn !== undefined && <th>{["x", "y", "z"][i]}</th>}
              {row.map((v, j) => (
                <td
                  key={j}
                  className={
                    j === highlightColumn ? "active-column" : undefined
                  }
                >
                  {num(v, 3)}
                </td>
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
  const velocity = mode === "jacobian";
  const series = [
    samples.map((s) =>
      velocity
        ? Math.hypot(...(s.cartesian_velocity ?? [0, 0, 0]))
        : cube
          ? (s.cube_height ?? s.cube_position?.[2] ?? 0)
          : (s.joints?.[joint] ?? s.value ?? 0),
    ),
  ];
  if (
    ["structure", "joint-control", "trajectory"].includes(mode) &&
    samples[0].reference_joints
  )
    series.push(samples.map((s) => s.reference_joints?.[joint] ?? 0));
  if (velocity)
    series.push(
      samples.map((s) =>
        Math.hypot(...(s.measured_cartesian_velocity ?? [0, 0, 0])),
      ),
    );
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
          {velocity
            ? "末端速度大小 / m·s⁻¹"
            : cube
              ? "方块高度 / m"
              : mode === "physics"
                ? `观测量 / ${unit}`
                : `关节 ${joint + 1} / rad`}
        </span>
        <span>
          <i />
          {velocity ? "雅可比预测" : "实际值"}{" "}
          {series.length > 1 && (
            <>
              <i className="reference" />
              {velocity ? "位置差分观测" : "参考值"}
            </>
          )}
        </span>
      </div>
      <svg
        viewBox="0 0 640 170"
        role="img"
        aria-label={
          velocity
            ? "雅可比预测与位置差分观测速度大小曲线"
            : cube
              ? "方块实际高度曲线"
              : "实际状态与参考曲线"
        }
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
  if (mode === "gravity") return null;
  const jointInputs = (
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
  );
  return (
    <div className="panel controls">
      <div className="panel-heading">
        <h3>实验参数</h3>
        <span className="unit-note">角度 rad · 长度 m</span>
      </div>
      {["structure", "fk", "jacobian", "joint-control", "trajectory"].includes(
        mode,
      ) &&
        (mode === "jacobian" ? (
          <details className="initial-configuration">
            <summary>起始关节构型 / rad</summary>
            {jointInputs}
          </details>
        ) : (
          jointInputs
        ))}
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
          <span>位置增益倍率</span>
          <input
            aria-label="位置增益倍率"
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
      {["joint-control", "trajectory"].includes(mode) && (
        <label className="range-row">
          <span>阻尼倍率</span>
          <input
            aria-label="阻尼倍率"
            type="range"
            min="0.05"
            max="2"
            step="0.01"
            value={s.damping_scale}
            onChange={(e) => update("damping_scale", +e.target.value)}
          />
          <output>{s.damping_scale.toFixed(2)}</output>
        </label>
      )}
      {["joint-control", "trajectory"].includes(mode) && (
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
                update(
                  "velocity",
                  Array.from({ length: 7 }, (_, i) =>
                    i === +e.target.value ? s.velocity[joint] || 0.05 : 0,
                  ),
                );
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
          <p className="control-hint">
            每次运行 2 秒；速度反向后，预测与观测箭头应同时反向。
          </p>
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
      <p className="control-hint">
        {mode === "structure"
          ? "输入目标角度后点击移动到目标。默认位置控制与重力补偿保持开启。"
          : "调整参数后，使用实验区下方的操作按钮应用。"}
      </p>
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
            act(
              mode === "gravity"
                ? "gravity-release"
                : mode === "jacobian"
                  ? "jacobian-run"
                  : mode === "trajectory"
                    ? "trajectory"
                    : "configure",
            )
          }
        >
          {mode === "gravity"
            ? "关闭补偿并释放"
            : mode === "jacobian"
              ? "设置构型并运行 2 秒"
              : mode === "structure" || mode === "joint-control"
                ? "移动到目标"
                : mode === "ik"
                  ? "求解并显示构型"
                  : mode === "trajectory"
                    ? "执行轨迹"
                    : "应用参数"}
        </button>
        {mode === "gravity" && (
          <button
            className="button"
            disabled={busy || !ready}
            onClick={() => act("gravity-hold")}
          >
            恢复初态并开启补偿
          </button>
        )}
        {mode === "jacobian" && (
          <button
            className="button"
            disabled={busy || !ready}
            onClick={() => act("jacobian-stop")}
          >
            停止运动
          </button>
        )}
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
function VelocityReadings({
  state: s,
  joint,
}: {
  state: Observation;
  joint: number;
}) {
  const markerId = useId().replaceAll(":", "");
  const sample = s.velocity_comparison;
  const activeJoint = sample?.joint_index ?? joint;
  const predicted = sample?.predicted ?? [0, 0, 0];
  const measured = sample?.measured ?? [0, 0, 0];
  const scale =
    76 / Math.max(Math.hypot(...predicted), Math.hypot(...measured), 0.001);
  const project = (v: number[], factor: number): [number, number] => [
    140 + (v[0] - v[1]) * 0.866 * factor,
    118 - (0.5 * (v[0] + v[1]) + v[2]) * factor,
  ];
  const colors = ["#217797", "#ce7232"];
  return (
    <section className="velocity-comparison" aria-label="雅可比预测与观测对照">
      <p className="experiment-phase">{s.phase}</p>
      <svg
        className="velocity-vectors"
        viewBox="0 0 280 200"
        role="img"
        aria-label="世界坐标下预测与位置差分观测速度的等轴投影箭头"
      >
        <defs>
          {colors.map((color, i) => (
            <marker
              key={color}
              id={`${markerId}-${i}`}
              markerUnits="userSpaceOnUse"
              markerWidth="9"
              markerHeight="9"
              refX="6"
              refY="3.5"
              orient="auto"
            >
              <path d="M0 0 L7 3.5 L0 7 Z" fill={color} />
            </marker>
          ))}
        </defs>
        {[
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ].map((axis, i) => {
          const [x, y] = project(axis, 58);
          return (
            <g key={i}>
              <line x1="140" y1="118" x2={x} y2={y} stroke="#a8bac6" />
              <text x={x + 5} y={y - 3}>
                {["x", "y", "z"][i]}
              </text>
            </g>
          );
        })}
        {[predicted, measured].map((v, i) => {
          const [x, y] = project(v, scale);
          return Math.hypot(...v) > 1e-10 ? (
            <line
              key={i}
              x1="140"
              y1="118"
              x2={x}
              y2={y}
              stroke={colors[i]}
              strokeWidth={i ? 2 : 5}
              strokeDasharray={i ? "5 3" : undefined}
              markerEnd={`url(#${markerId}-${i})`}
            />
          ) : null;
        })}
        <circle cx="140" cy="118" r="3" fill="#425e72" />
        {!sample && (
          <text x="140" y="178" textAnchor="middle">
            运行单关节运动后显示速度箭头
          </text>
        )}
      </svg>
      <div className="velocity-legend">
        <span>
          <i />
          雅可比预测
        </span>
        <span>
          <i />
          位置差分观测
        </span>
      </div>
      <p className="control-hint">
        世界坐标等轴投影，两支箭头共用缩放；三维差异请对照三轴数值与速度误差。
      </p>
      <table className="velocity-table">
        <thead>
          <tr>
            <th>m/s</th>
            <th>x</th>
            <th>y</th>
            <th>z</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>预测</th>
            {predicted.map((v, i) => (
              <td key={i}>{num(v, 5)}</td>
            ))}
          </tr>
          <tr>
            <th>观测</th>
            {measured.map((v, i) => (
              <td key={i}>{num(v, 5)}</td>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="reading-line">
        速度误差：{sample ? sample.error_norm.toExponential(2) : "—"} m/s
      </p>
      <p className="control-hint">
        {sample
          ? `采样 ${num(sample.time, 3)} s · 区间 ${num(sample.dt * 1000, 0)} ms · 关节 ${activeJoint + 1} 实际速度 ${num(sample.joint_velocities[activeJoint], 3)} rad/s${s.jacobian_running ? "" : " · 保留末次运动采样"}`
          : "点击设置构型并运行 2 秒。默认关节 2、速度 0.05 rad/s。"}
      </p>
      <p className="matrix-caption">
        采样区间起点的平移雅可比 · 高亮关节 {activeJoint + 1}
      </p>
      <Matrix
        values={sample?.jacobian ?? s.jacobian}
        highlightColumn={activeJoint}
      />
      <details>
        <summary>当前构型的平移奇异值</summary>
        <p className="reading-line">
          {s.singular_values.map((v) => num(v, 4)).join(" · ")}
        </p>
        <p className="control-hint">只描述三维平移任务。</p>
      </details>
    </section>
  );
}
export function Readings({
  state: s,
  mode,
  live,
  joint = 1,
}: {
  state?: Observation;
  mode: string;
  live: boolean;
  joint?: number;
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
      {mode === "gravity" && (
        <div className="gravity-status">
          <p className="experiment-phase">
            {s.compensation
              ? "补偿开启 · 观察构型保持"
              : "补偿关闭 · 观察自重下落"}
          </p>
          <p>
            位置伺服关闭，世界重力始终竖直向下 9.81 m/s²。观察机械臂连杆与关节。
          </p>
          <dl>
            <div>
              <dt>相对初态构型偏移</dt>
              <dd>{num(s.joint_displacement_rad ?? 0, 4)} rad</dd>
            </div>
            <div>
              <dt>末端高度变化</dt>
              <dd>{num(s.tool_height_change_m ?? 0, 4)} m</dd>
            </div>
          </dl>
          <p className="control-hint">
            两个对照按钮都会恢复相同静止初态，再切换补偿并开始运行。
          </p>
        </div>
      )}
      <div className="readings-grid">
        <div>
          <span>末端世界位置 / m</span>
          <strong>{s.tool_position.map((v) => num(v, 3)).join(" · ")}</strong>
        </div>
        <div>
          <span>夹爪实际开口 / m</span>
          <strong>{num(s.gripper_width, 4)}</strong>
        </div>
        {["structure", "joint-control", "trajectory"].includes(mode) && (
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
      {mode === "jacobian" && <VelocityReadings state={s} joint={joint} />}
      {["joint-control", "gravity", "trajectory"].includes(mode) && (
        <details>
          <summary>
            {mode === "gravity"
              ? "关节角度、重力力矩与补偿输入"
              : "关节角度、执行器力矩与重力项"}
          </summary>
          <div className="matrix-wrap">
            <table className="joint-table">
              <thead>
                <tr>
                  <th>关节</th>
                  <th>实际 rad</th>
                  <th>{mode === "gravity" ? "补偿 N·m" : "执行器 N·m"}</th>
                  <th>重力项 N·m</th>
                </tr>
              </thead>
              <tbody>
                {s.joints.map((q, i) => (
                  <tr key={i}>
                    <th>{i + 1}</th>
                    <td>{num(q, 3)}</td>
                    <td>
                      {num(
                        (mode === "gravity"
                          ? s.compensation_torque?.[i]
                          : s.actuator_torque[i]) ?? 0,
                        2,
                      )}
                    </td>
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
