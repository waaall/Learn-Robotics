import { useState } from "react";
import { TimeSeries } from "./timeseries";
import { SupportPlot } from "./humanoid";
import type { MicroduckObservation, MicroduckSettings, Sample, Settings } from "./types";

const JOINTS = ["左髋偏航", "左髋侧摆", "左髋俯仰", "左膝", "左踝", "颈部俯仰", "头部俯仰", "头部偏航", "头部侧倾", "右髋偏航", "右髋侧摆", "右髋俯仰", "右膝", "右踝"];
const FOCUS: Record<string, string> = {
  "microduck-structure": "关节与浮动基座", "microduck-head": "头颈运动与舵机响应",
  "microduck-contact": "质心与双脚承重", "microduck-walking": "行走策略与速度响应",
  "microduck-sitstand": "姿态命令与坐站过程", "microduck-robustness": "外力与物理条件响应",
};
const number = (x: number, digits = 3) => x.toFixed(digits);

export function MicroduckControls({ settings, set, mode }: { settings: Settings; set: (s: Settings) => void; mode: string }) {
  const m = settings.microduck!;
  const update = (patch: Partial<MicroduckSettings>) => set({ ...settings, microduck: { ...m, ...patch } });
  const field = (key: keyof MicroduckSettings, label: string, min: number, max: number, step: number) =>
    <label className="g1-field" key={key}><span>{label}</span><input type="number" value={m[key] as number}
      min={min} max={max} step={step} onChange={e => update({ [key]: +e.target.value })} /></label>;
  const head = () => m.head.map((v, i) => <label className="g1-field" key={i}><span>{JOINTS[i + 5]}增量 / rad</span>
    <input type="number" value={v} min={-([.2, .2, .6, .2][i])} max={[.2, .2, .6, .2][i]} step={.05}
      onChange={e => update({ head: m.head.map((x, j) => j === i ? +e.target.value : x) })} /></label>);
  return <section className="panel controls g1-controls"><div className="panel-heading"><h3>实验参数</h3></div>
    {mode === "microduck-structure" && <><label className="g1-field"><span>运动关节</span>
      <select value={m.joint_index} onChange={e => update({ joint_index: +e.target.value })}>{JOINTS.map((s, i) => <option value={i} key={i}>{s}</option>)}</select></label>
      {field("joint_offset", "相对默认站姿增量 / rad", -.25, .25, .025)}</>}
    {mode === "microduck-head" && head()}
    {mode === "microduck-contact" && <>{field("shift", "侧倾关节增量 / rad", -.08, .08, .01)}{field("friction", "地面滑动摩擦系数", .1, 2, .1)}</>}
    {["microduck-walking", "microduck-robustness"].includes(mode) && m.command.map((v, i) =>
      <label className="g1-field" key={i}><span>{["前进 / m·s⁻¹", "侧移 / m·s⁻¹", "转向 / rad·s⁻¹"][i]}</span>
        <input type="number" value={v} min={-([.4, .2, 1][i])} max={[.4, .2, 1][i]} step={.05}
          onChange={e => update({ command: m.command.map((x, j) => j === i ? +e.target.value : x) })} /></label>)}
    {mode !== "microduck-sitstand" && field("duration", "目标过渡时间 / s", 1, 6, .5)}
    {mode === "microduck-robustness" && <>{field("push_force", "外力峰值 / N", -5, 5, .5)}
      {field("push_duration", "施力时长 / s", .1, 1, .1)}{field("friction", "地面滑动摩擦系数", .1, 2, .1)}
      {field("voltage", "电池电压 / V", 6.5, 8.2, .1)}</>}
    {["microduck-walking", "microduck-sitstand"].includes(mode) && <details><summary>头颈姿态命令</summary>{head()}</details>}
    <p className="panel-note">应用参数后执行。暂停时保留物理状态，单步或继续后观察变化。</p>
  </section>;
}

export function MicroduckActions({ mode, ready, busy, paused, act }: {
  mode: string; ready: boolean; busy: boolean; paused: boolean; act: (s: string) => void;
}) {
  const actions = [["configure", "应用参数"],
    ...(["microduck-walking", "microduck-robustness"].includes(mode) ? [["walk", "启动行走策略"], ["walk-stop", "平滑减速"]] : []),
    ...(mode === "microduck-sitstand" ? [["sit", "坐下"], ["stand", "站起"]] : []),
    ...(mode === "microduck-robustness" ? [["push", "施加外力"]] : []),
    ["pause", paused ? "继续" : "暂停"], ["step", "单步 2 ms"], ["reset", "恢复初态"]];
  return <div className="panel g1-actions" aria-label="Microduck 实验操作">{actions.map(([id, label]) =>
    <button key={id} className={`button ${id === "configure" ? "primary" : ""}`} disabled={!ready || busy} onClick={() => act(id)}>{label}</button>)}</div>;
}

export function MicroduckReadings({ state: s, live, mode }: { state: MicroduckObservation | null; live: boolean; mode: string }) {
  const metric = (label: string, value: number, digits = 3) => <div key={label}><dt>{label}</dt><dd>{number(value, digits)}</dd></div>;
  if (!s) return <section className="panel g1-readings"><h3>{FOCUS[mode]}</h3><p className="panel-note">打开实验或运行独立验证后显示观测。</p></section>;
  return <section className="panel g1-readings"><div className="panel-heading"><h3>{FOCUS[mode]}</h3><span>{live ? "实时" : "独立结果"} · {number(s.time, 2)} s</span></div>
    <p className="panel-note" role="status">{s.phase}{s.fallen ? " · 已倾倒，可恢复初态" : ""}{live && s.age_seconds > 2 ? " · 观测更新延迟" : ""}</p>
    <dl className="g1-metrics">{metric("基座高度 / m", s.base_position[2])}{metric("机身倾角 / °", s.tilt_rad * 180 / Math.PI, 2)}
      {mode === "microduck-walking" || mode === "microduck-robustness" ? <>{metric("前进命令 / m·s⁻¹", s.command[0])}{metric("实际前进速度 / m·s⁻¹", s.body_velocity[0])}{metric("平面位移 / m", s.displacement_m)}</> : null}
      {mode === "microduck-sitstand" && metric("姿态标志（0 站 / 1 坐）", s.posture_command, 0)}
      {mode === "microduck-robustness" && <>{metric("当前外力 / N", s.push_force_N)}{metric("峰值倾角 / °", s.max_tilt_rad * 180 / Math.PI, 2)}</>}
      {metric("左脚支撑 / N", s.foot_forces[0][2])}{metric("右脚支撑 / N", s.foot_forces[1][2])}{metric("全身重力 / N", s.weight_N)}
    </dl>
    {mode === "microduck-contact" && <SupportPlot state={s} minRadius={.07} />}
    <details><summary>14 路关节与力矩</summary><p className="panel-note">当前舵机 Kp={s.servo_kp}；位置参考通过电压环与 BAM M6 动力学执行。</p>
      <div className="g1-table-scroll"><table className="joint-table"><thead><tr><th>关节</th><th>实际 / rad</th><th>参考 / rad</th><th>力矩 / N·m</th></tr></thead><tbody>{s.joints.map((v, i) =>
        <tr key={i}><td title={s.joint_names[i]}>{JOINTS[i]}</td><td>{number(v)}</td><td>{number(s.reference_joints[i])}</td><td>{number(s.actuator_torque[i])}</td></tr>)}</tbody></table></div></details>
    {s.policy_active && <details><summary>学习策略输入输出（61 → MLP → 14）</summary><p className="panel-note">角速度 3、重力方向 3、位置偏差 14、关节速度 14、上一动作 14、命令 13。权重和归一化固定。</p>
      <p className="g1-array">输入：{s.policy_observation.map(v => number(v)).join(", ")}</p><p className="g1-array">动作：{s.policy_action.map(v => number(v)).join(", ")}</p></details>}
    <details><summary>机身与支撑区域</summary><SupportPlot state={s} minRadius={.07} /><p className="panel-note">质心：{s.com.map(v => number(v)).join(" / ")} m；静态几何距离：{s.support_margin_m === null ? "接触不足" : number(s.support_margin_m) + " m"}。</p></details>
  </section>;
}

type DuckSample = Sample & { posture_command?: number };
export function MicroduckChart({ samples, mode }: { samples: DuckSample[]; mode: string }) {
  const [joint, setJoint] = useState(mode === "microduck-head" || mode === "microduck-structure" ? 7 : 3);
  const times = samples.map(s => s.time);
  const plot = (title: string, unit: string, series: { name: string; value: (s: DuckSample) => number | null | undefined }[]) =>
    <TimeSeries title={title} unit={unit} times={times} series={series.map(s => ({ name: s.name, values: samples.map(s.value) }))} />;
  const applied = new Map<number, number>();
  if (mode === "microduck-robustness") for (const s of samples) for (const [time, force] of s.push_trace ?? []) {
    if (time >= times[0] && time <= times.at(-1)!) applied.set(time, force);
  }
  const forces = [...applied].sort((a, b) => a[0] - b[0]);
  return <div className="g1-charts">
    {["microduck-walking", "microduck-robustness"].includes(mode) && plot("前进速度", "m/s", [{ name: "命令", value: s => s.command?.[0] }, { name: "实际", value: s => s.body_velocity?.[0] }])}
    {mode === "microduck-sitstand" && plot("姿态标志", "0 / 1", [{ name: "0 站立 / 1 坐下", value: s => s.posture_command }])}
    {mode === "microduck-robustness" && forces.length > 1 && <TimeSeries title="实际外力包络" unit="N" times={forces.map(p => p[0])} series={[{ name: "世界 X 方向", values: forces.map(p => p[1]) }]} />}
    {plot("基座高度", "m", [{ name: "实际高度", value: s => s.base_position?.[2] }])}
    {plot("足底竖直支撑", "N", [{ name: "左脚", value: s => s.foot_forces?.[0]?.[2] }, { name: "右脚", value: s => s.foot_forces?.[1]?.[2] }, { name: "全身重力", value: s => s.weight_N }])}
    {plot("机身倾角", "°", [{ name: "实际倾角", value: s => s.tilt_rad == null ? null : s.tilt_rad * 180 / Math.PI }])}
    <label className="g1-field"><span>观测关节</span><select value={joint} onChange={e => setJoint(+e.target.value)}>{JOINTS.map((name, i) => <option value={i} key={i}>{name}</option>)}</select></label>
    {plot(JOINTS[joint], "rad", [{ name: "实际", value: s => s.joints?.[joint] }, { name: "参考", value: s => s.reference_joints?.[joint] }])}
  </div>;
}
