import { useState } from "react";
import { TimeSeries } from "./timeseries";
import type { HumanoidObservation, HumanoidSettings, Sample, Settings } from "./types";

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
    {mode === "g1-structure" && field("squat", "下蹲增量 / rad", 0, .35, .025)}
    {mode === "g1-contact" && <>
      {field("lean", "前倾关节增量 / rad", -.12, .12, .01)}
      {field("shift", "侧倾关节增量 / rad", -.12, .12, .005)}
    </>}
    {mode === "g1-balance" && <>
      {field("squat", "下蹲增量 / rad", 0, .35, .025)}
      {field("lean", "前倾关节增量 / rad", -.12, .12, .01)}
      {field("shift", "侧倾关节增量 / rad", -.12, .12, .005)}
      {field("friction", "地面滑动摩擦系数", .1, 2, .1)}
    </>}
    {["g1-walking", "g1-recovery"].includes(mode) && h.command.map((v,i) =>
      <label className="g1-field" key={i}><span>{["前进 / m·s⁻¹", "侧移 / m·s⁻¹", "转向 / rad·s⁻¹"][i]}</span>
        <input type="number" value={v} min={-[.8,.3,.8][i]} max={[.8,.3,.8][i]} step={.05}
          onChange={e => set({...settings, humanoid: {...h, command: h.command.map((x,j) => j === i ? +e.target.value : x)}})} />
      </label>)}
    {field("duration", "运动过渡时间 / s", 1, 8, .5)}
    {mode === "g1-recovery" && <>
      {field("push_force", "外力峰值 / N", -100, 100, 5)}
      {field("push_duration", "施力时长 / s", .1, 2, .1)}
      {field("friction", "地面滑动摩擦系数", .1, 2, .1)}
      {field("payload", "机身附加载荷 / kg", 0, 5, .5)}
    </>}
    {["g1-structure", "g1-contact", "g1-walking"].includes(mode) && <details><summary>其他实验参数</summary>
      {mode === "g1-structure" && <>
        {field("lean", "前倾关节增量 / rad", -.12, .12, .01)}
        {field("shift", "侧倾关节增量 / rad", -.12, .12, .005)}
      </>}
      {mode === "g1-contact" && field("squat", "下蹲增量 / rad", 0, .35, .025)}
      {field("friction", "地面滑动摩擦系数", .1, 2, .1)}
    </details>}
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

const FOCUS: Record<string,string> = {
  "g1-structure": "基座位姿与关节运动", "g1-contact": "质心投影与足底承重",
  "g1-balance": "站立倾角与支撑变化", "g1-walking": "速度指令与策略执行",
  "g1-recovery": "外力扰动与恢复过程",
};

export function HumanoidReadings({state, live, mode}: {state: HumanoidObservation | null; live: boolean; mode: string}) {
  if (!state) return <section className="panel g1-readings"><h3>{FOCUS[mode]}</h3><p className="panel-note">打开交互实验或运行独立验证后显示观测。</p></section>;
  const stance = ["g1-contact", "g1-balance"].includes(mode);
  const metric = (name: string, value: number | undefined, digits = 3) => <div key={name}><dt>{name}</dt><dd>{number(value,digits)}</dd></div>;
  return <section className="panel g1-readings"><div className="panel-heading"><h3>{FOCUS[mode]}</h3><span>{live ? "实时" : "独立结果"} · {number(state.time,2)} s</span></div>
    <p className="panel-note" role="status">{state.phase}{state.fallen ? " · 已跌倒，可恢复初态" : ""}{live && state.age_seconds > 2 ? " · 观测更新延迟" : ""}</p>
    <dl className="g1-metrics">
      {mode === "g1-structure" && <>{metric("基座高度 / m",state.base_position[2])}{metric("左膝实际角 / rad",state.joints[3])}{metric("左膝参考角 / rad",state.reference_joints[3])}{metric("机身倾角 / °",state.tilt_rad*180/Math.PI,2)}</>}
      {stance && <>{metric("左脚支撑 / N",state.foot_forces[0][2],1)}{metric("右脚支撑 / N",state.foot_forces[1][2],1)}
        {metric("竖直支撑合力 / N",state.foot_forces[0][2]+state.foot_forces[1][2],1)}{metric("全身重力 / N",state.weight_N,1)}
        <div><dt>静态几何距离 / m</dt><dd>{state.support_margin_m === null ? "接触不足" : number(state.support_margin_m)}</dd></div>
        {metric("机身倾角 / °",state.tilt_rad*180/Math.PI,2)}</>}
      {mode === "g1-walking" && <>{metric("平滑前进指令 / m·s⁻¹",state.command[0])}{metric("实际前进速度 / m·s⁻¹",state.body_velocity[0])}{metric("平面位移 / m",state.displacement_m)}{metric("机身倾角 / °",state.tilt_rad*180/Math.PI,2)}</>}
      {mode === "g1-recovery" && <>{metric("当前外力 / N",state.push_force_N,1)}{metric("已记录外力幅值峰值 / N",Math.max(0,...(state.push_trace ?? []).map(p=>Math.abs(p[1]))),1)}{metric("机身倾角 / °",state.tilt_rad*180/Math.PI,2)}{metric("本次峰值倾角 / °",state.max_tilt_rad*180/Math.PI,2)}{metric("实际前进速度 / m·s⁻¹",state.body_velocity[0])}{metric("平面位移 / m",state.displacement_m)}</>}
    </dl>
    {stance && <SupportPlot state={state} />}
    {mode === "g1-structure" && <dl className="g1-vectors"><dt>基座位置 / m</dt><dd>{state.base_position.map(v => number(v)).join(" / ")}</dd><dt>基座四元数 / wxyz</dt><dd>{state.base_quaternion.map(v => number(v)).join(" / ")}</dd></dl>}
    <details><summary>完整机身与接触观测</summary>
      {!stance && <SupportPlot state={state} />}
      <dl className="g1-vectors"><dt>质心位置 / m</dt><dd>{state.com.map(v => number(v)).join(" / ")}</dd><dt>机身速度 / m·s⁻¹</dt><dd>{state.body_velocity.map(v => number(v)).join(" / ")}</dd><dt>左右脚竖直支撑 / N</dt><dd>{state.foot_forces.map(f => number(f[2],1)).join(" / ")}</dd>
      {state.policy_active && <><dt>请求命令 / vx, vy, wz</dt><dd>{state.requested_command.map(v => number(v)).join(" / ")}</dd><dt>平滑命令 / vx, vy, wz</dt><dd>{state.command.map(v => number(v)).join(" / ")}</dd></>}
      <dt>当前外力 / N</dt><dd>{number(state.push_force_N,1)}</dd></dl>
    </details>
    <details><summary>12 路关节状态与力矩</summary><div className="g1-table-scroll"><table className="joint-table"><thead><tr><th>关节</th><th>实际 / rad</th><th>参考 / rad</th><th>目标 / rad</th><th>力矩 / N·m</th></tr></thead><tbody>
      {state.joints.map((q,i) => <tr key={i}><td>{state.joint_names[i].replace("_joint", "")}</td><td>{number(q)}</td><td>{number(state.reference_joints[i])}</td><td>{number(state.target_joints[i])}</td><td>{number(state.actuator_torque[i],2)}</td></tr>)}
    </tbody></table></div></details>
    {state.policy_active && <details><summary>学习策略输入输出（47 → LSTM → 12）</summary><p className="panel-note">观测：角速度 3、重力方向 3、命令 3、位置偏差 12、速度 12、上一动作 12、相位 2。</p><p className="g1-array">输入：{state.policy_observation.map(v => number(v)).join(", ")}</p><p className="g1-array">动作：{state.policy_action.map(v => number(v)).join(", ")}</p></details>}
  </section>;
}

type HumanSample = Sample;
const DEFAULT_VIEW: Record<string,string> = {"g1-structure": "structure", "g1-contact": "contact", "g1-balance": "balance", "g1-walking": "velocity", "g1-recovery": "recovery"};
export function HumanoidChart({samples, mode}: {samples: HumanSample[]; mode: string}) {
  const [selected, setSelected] = useState<string | null>(null);
  const view = selected ?? DEFAULT_VIEW[mode];
  const times = samples.map(s => s.time);
  const applied = new Map<number,number>();
  if (view === "recovery") {
    for (const sample of samples) for (const [time,force] of sample.push_trace ?? []) {
      if (time >= times[0] && time <= times.at(-1)!) applied.set(time,force);
    }
    if (applied.size > 1) {
      applied.set(times[0],samples[0].push_force_N ?? 0);
      applied.set(times.at(-1)!,samples.at(-1)?.push_force_N ?? 0);
    }
  }
  const forceTrace = [...applied].sort((a,b) => a[0]-b[0]);
  const plot = (title: string, unit: string, series: {name: string; value: (s: HumanSample) => number | null | undefined}[]) =>
    <TimeSeries times={times} title={title} unit={unit} series={series.map(s => ({name:s.name,values:samples.map(s.value)}))} />;
  const tilt = () => plot("机身倾角", "°", [{name:"实际倾角",value:s => s.tilt_rad == null ? null : s.tilt_rad*180/Math.PI}]);
  const velocity = () => <>{[0,1].map(i => <div key={i}>{plot(i === 0 ? "前进速度" : "侧移速度","m/s",[{name:"平滑指令",value:s => s.command?.[i]},{name:"实际速度",value:s => s.body_velocity?.[i]}])}</div>)}</>;
  return <div className="g1-charts"><label className="g1-field"><span>观测曲线</span><select value={view} aria-label="人形观测曲线" onChange={e => setSelected(e.target.value)}>
    <option value="structure">基座高度与膝关节</option><option value="contact">足底承重与质心</option><option value="balance">倾角与支撑距离</option><option value="velocity">速度指令与实际速度</option><option value="recovery">外力与恢复过程</option>
    {samples[0]?.joints?.map((_,i) => <option key={i} value={String(i)}>关节 {i+1}</option>)}
  </select></label>
    {view === "structure" && <>{plot("基座高度","m",[{name:"实际高度",value:s => s.base_position?.[2]}])}{plot("左膝关节","rad",[{name:"实际",value:s => s.joints?.[3]},{name:"连续参考",value:s => s.reference_joints?.[3]},{name:"终点目标",value:s => s.target_joints?.[3]}])}</>}
    {view === "contact" && <>{plot("足底竖直支撑","N",[{name:"左脚",value:s => s.foot_forces?.[0]?.[2]},{name:"右脚",value:s => s.foot_forces?.[1]?.[2]},{name:"全身重力",value:s => s.weight_N}])}
      {plot("质心平面位移（相对首个采样）","m",[0,1].map(i => ({name:i === 0 ? "前后 X" : "左右 Y",value:(s:HumanSample) => s.com && samples[0]?.com ? s.com[i]-samples[0].com[i] : null})))}</>}
    {view === "balance" && <>{tilt()}{plot("静态几何距离","m",[{name:"质心投影到接触凸包",value:s => s.support_margin_m}])}<p className="panel-note">接触不足时曲线留空；该距离仅用于静态、准静态分析。</p></>}
    {view === "velocity" && velocity()}
    {view === "recovery" && <>{forceTrace.length > 1
      ? <TimeSeries times={forceTrace.map(p=>p[0])} title="外力包络（物理线程记录）" unit="N" series={[{name:"机身沿世界 X 方向受力",values:forceTrace.map(p=>p[1])}]} />
      : plot("外力包络","N",[{name:"机身沿世界 X 方向受力",value:s => s.push_force_N}])}
      {tilt()}{plot("扰动前后前进速度","m/s",[{name:"平滑指令",value:s => s.command?.[0]},{name:"实际速度",value:s => s.body_velocity?.[0]}])}</>}
    {Number.isInteger(Number(view)) && plot("关节 " + (Number(view)+1),"rad",[{name:"实际",value:s => s.joints?.[Number(view)]},{name:"连续参考",value:s => s.reference_joints?.[Number(view)]},{name:"终点目标",value:s => s.target_joints?.[Number(view)]}])}
  </div>;
}
