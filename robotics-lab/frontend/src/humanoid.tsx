import { useState } from "react";
import type { HumanoidObservation, HumanoidSettings, Settings } from "./types";

const number = (x: number | undefined, digits = 3) => x === undefined ? "—" : x.toFixed(digits);

export function HumanoidControls({ settings, set, mode }: {
  settings: Settings; set: (value: Settings) => void; mode: string;
}) {
  const h = settings.humanoid!;
  function field(key: keyof HumanoidSettings, label: string, min: number, max: number, step: number) {
    return <label className="g1-field" key={key}><span>{label}</span><input type="number"
      value={h[key] as number} min={min} max={max} step={step}
      onChange={e => set({ ...settings, humanoid: { ...h, [key]: +e.target.value } })} /></label>;
  }
  return <section className="panel controls g1-controls"><div className="panel-heading"><h3>实验参数</h3></div>
    {!["g1-walking", "g1-recovery"].includes(mode) && <>
      {field("squat", "下蹲增量 / rad", 0, .35, .025)}
      {field("lean", "前倾目标 / rad", -.12, .12, .01)}
      {field("shift", "侧倾目标 / rad", -.12, .12, .01)}
    </>}
    {["g1-walking", "g1-recovery"].includes(mode) && h.command.map((v, i) =>
      <label className="g1-field" key={i}><span>{["前进 / m·s⁻¹", "侧移 / m·s⁻¹", "转向 / rad·s⁻¹"][i]}</span>
        <input type="number" value={v} min={-([.8, .3, .8][i])} max={[.8, .3, .8][i]} step={.05}
          onChange={e => set({ ...settings, humanoid: { ...h, command: h.command.map((x, j) => j === i ? +e.target.value : x) } })} />
      </label>)}
    {field("duration", "运动过渡时间 / s", 1, 8, .5)}
    {field("friction", "地面滑动摩擦系数", .1, 2, .1)}
    {mode === "g1-recovery" && <>
      {field("push_force", "外力峰值 / N", -100, 100, 5)}
      {field("push_duration", "施力时长 / s", .1, 2, .1)}
      {field("payload", "机身附加载荷 / kg", 0, 5, .5)}
    </>}
    <p className="panel-note">应用参数后连续运动。暂停时仅更新目标，单步或继续后执行。</p>
  </section>;
}

export function HumanoidActions({ mode, ready, busy, paused, act }: {
  mode: string; ready: boolean; busy: boolean; paused: boolean; act: (action: string) => void;
}) {
  const actions = [["configure", "应用参数并连续运动"],
    ...(["g1-walking", "g1-recovery"].includes(mode) ? [["walk", "启动学习策略"], ["walk-stop", "平滑减速"]] : []),
    ...(mode === "g1-recovery" ? [["push", "施加平滑外力"]] : []),
    ["pause", paused ? "继续" : "暂停"], ["step", "单步 2 ms"], ["reset", "恢复初态"]];
  return <div className="panel g1-actions" aria-label="人形实验操作">{actions.map(([action, title]) =>
    <button key={action} className={`button ${action === "configure" ? "primary" : ""}`}
      disabled={!ready || busy} onClick={() => act(action)}>{title}</button>)}</div>;
}

function SupportPlot({ state }: { state: HumanoidObservation }) {
  const points = [...state.support_polygon, state.com.slice(0, 2)];
  const cx = points.reduce((a, p) => a + p[0], 0) / points.length;
  const cy = points.reduce((a, p) => a + p[1], 0) / points.length;
  const radius = Math.max(.22, ...points.map(p => Math.max(Math.abs(p[0]-cx), Math.abs(p[1]-cy)))) * 1.2;
  const point = (p: number[]) => [160 - (p[1]-cy)*100/radius, 105 - (p[0]-cx)*90/radius];
  const com = point(state.com);
  return <div className="g1-support"><svg viewBox="0 0 320 210" role="img" aria-label="质心投影与实际足底接触区域">
    <path d="M160 10V200M20 105H300" className="chart-grid" />
    {state.support_polygon.length >= 3 && <polygon points={state.support_polygon.map(p => point(p).join(",")).join(" ")} fill="#dce9e5" stroke="#247b69" strokeWidth="2" />}
    {state.support_polygon.map((p, i) => { const [x,y] = point(p); return <circle key={i} cx={x} cy={y} r="3" fill="#247b69" />; })}
    <circle cx={com[0]} cy={com[1]} r="6" fill="#cd603f" /><text x={com[0]+9} y={com[1]-8}>质心</text>
    <text x="164" y="18">前 +X</text><text x="12" y="99">左 +Y</text>
  </svg><p className="panel-note">地面俯视 · 支撑区域取实际受力接触点。几何距离仅用于静态、准静态分析。</p></div>;
}

export function HumanoidReadings({ state, live }: { state: HumanoidObservation | null; live: boolean }) {
  if (!state) return <section className="panel"><div className="panel-heading"><h3>人形状态观测</h3></div><p className="panel-note">打开交互实验或运行独立验证后显示观测。</p></section>;
  return <section className="panel g1-readings"><div className="panel-heading"><h3>人形状态观测</h3><span>{live ? "实时" : "独立结果"} · {number(state.time, 2)} s</span></div>
    <p className="panel-note" role="status">{state.phase}{state.fallen ? " · 已跌倒，可恢复初态" : ""}{live && state.age_seconds > 2 ? " · 观测更新延迟" : ""}</p>
    <dl className="g1-metrics">
      <div><dt>基座高度 / m</dt><dd>{number(state.base_position[2])}</dd></div>
      <div><dt>机身倾角 / °</dt><dd>{number(state.tilt_rad*180/Math.PI, 2)}</dd></div>
      <div><dt>左脚支撑 / N</dt><dd>{number(state.foot_forces[0][2], 1)}</dd></div>
      <div><dt>右脚支撑 / N</dt><dd>{number(state.foot_forces[1][2], 1)}</dd></div>
      <div><dt>静态几何距离 / m</dt><dd>{state.support_margin_m === null ? "接触不足" : number(state.support_margin_m)}</dd></div>
      <div><dt>位移 / m</dt><dd>{number(state.displacement_m)}</dd></div>
    </dl>
    <SupportPlot state={state} />
    <dl className="g1-vectors">
      <dt>基座位置 / m</dt><dd>{state.base_position.map(v => number(v)).join(" / ")}</dd>
      <dt>基座四元数 / wxyz</dt><dd>{state.base_quaternion.map(v => number(v)).join(" / ")}</dd>
      <dt>质心位置 / m</dt><dd>{state.com.map(v => number(v)).join(" / ")}</dd>
      <dt>机身速度 / m·s⁻¹</dt><dd>{state.body_velocity.map(v => number(v)).join(" / ")}</dd>
      {state.policy_active && <><dt>请求命令 / vx, vy, wz</dt><dd>{state.requested_command.map(v => number(v)).join(" / ")}</dd><dt>平滑命令 / vx, vy, wz</dt><dd>{state.command.map(v => number(v)).join(" / ")}</dd></>}
      <dt>当前外力 / N</dt><dd>{number(state.push_force_N, 1)}</dd>
    </dl>
    <details><summary>12 路关节状态与力矩</summary><div className="g1-table-scroll"><table className="joint-table"><thead><tr><th>关节</th><th>实际 / rad</th><th>参考 / rad</th><th>目标 / rad</th><th>力矩 / N·m</th></tr></thead>
      <tbody>{state.joints.map((q,i) => <tr key={i}><td>{state.joint_names[i].replace("_joint", "")}</td><td>{number(q)}</td><td>{number(state.reference_joints[i])}</td><td>{number(state.target_joints[i])}</td><td>{number(state.actuator_torque[i], 2)}</td></tr>)}</tbody></table></div></details>
    {state.policy_active && <details><summary>学习策略输入输出（47 → LSTM → 12）</summary><p className="panel-note">观测：角速度 3、重力方向 3、命令 3、位置偏差 12、速度 12、上一动作 12、相位 2。</p><p className="g1-array">输入：{state.policy_observation.map(v => number(v)).join(", ")}</p><p className="g1-array">动作：{state.policy_action.map(v => number(v)).join(", ")}</p></details>}
  </section>;
}

export function HumanoidChart({ samples }: { samples: { time: number; base_position?: number[]; command?: number[]; body_velocity?: number[]; joints?: number[]; reference_joints?: number[]; target_joints?: number[] }[] }) {
  const [view, setView] = useState("body");
  if (samples.length < 2) return <div className="empty-chart">运行后显示基座高度、前进命令与实际速度。</div>;
  const joint = Number(view);
  const series = view === "body" ? [samples.map(s => s.base_position?.[2] ?? 0), samples.map(s => s.command?.[0] ?? 0), samples.map(s => s.body_velocity?.[0] ?? 0)]
    : [samples.map(s => s.joints?.[joint] ?? 0), samples.map(s => s.reference_joints?.[joint] ?? 0), samples.map(s => s.target_joints?.[joint] ?? 0)];
  const values = series.flat(), lo = Math.min(0, ...values), span = Math.max(.1, Math.max(...values)-lo);
  const elapsed = Math.max(.002, samples.at(-1)!.time-samples[0].time);
  return <div className="chart"><label className="g1-field"><span>观测曲线</span><select value={view} aria-label="人形观测曲线" onChange={e => setView(e.target.value)}><option value="body">基座与速度</option>{samples[0].joints?.map((_,i) => <option key={i} value={i}>关节 {i+1}</option>)}</select></label><div className="chart-caption"><span>{view === "body" ? "基座高度 / m · 速度 / m·s⁻¹" : `关节 ${joint+1} / rad`}</span><span>{view === "body" ? "绿：高度　橙：命令　蓝：实际速度" : "绿：实际　橙：连续参考　蓝：目标"}</span></div>
    <svg viewBox="0 0 640 170" role="img" aria-label={view === "body" ? "基座高度、前进命令和实际速度曲线" : "关节实际角度、连续参考与目标曲线"}>
      {[30,85,140].map(y => <path key={y} d={`M45 ${y}H625`} className="chart-grid" />)}
      {series.map((values,k) => <path key={k} fill="none" stroke={["#247b69", "#cd603f", "#3f79b5"][k]} strokeWidth="2"
        d={values.map((v,i) => `${i ? "L" : "M"}${45+(samples[i].time-samples[0].time)/elapsed*580},${140-(v-lo)/span*110}`).join(" ")} />)}
      <text x="5" y="30">{number(lo+span,2)}</text><text x="5" y="140">{number(lo,2)}</text><text x="45" y="163">{number(samples[0].time,1)} s</text><text x="570" y="163">{number(samples.at(-1)!.time,1)} s</text>
    </svg></div>;
}
