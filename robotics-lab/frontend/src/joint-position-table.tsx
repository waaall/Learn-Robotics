// 按观测数组生成关节角表，不固定关节数量，也不读取尚未应用的表单参数。
import { num } from "./types";

type JointPositionTableProps = {
  joints: readonly number[];
  reference_joints: readonly number[];
  target_joints: readonly number[];
};

export function JointPositionTable({
  joints,
  reference_joints,
  target_joints,
}: JointPositionTableProps) {
  return (
    <div className="matrix-wrap">
      <table className="joint-table" aria-label="关节角度观测">
        <thead>
          <tr>
            <th scope="col">关节</th>
            <th scope="col">实际 / rad</th>
            <th scope="col">参考 / rad</th>
            <th scope="col">目标 / rad</th>
          </tr>
        </thead>
        <tbody>
          {joints.map((q, i) => (
            <tr key={i}>
              <th scope="row">{i + 1}</th>
              <td>{num(q)}</td>
              <td>{num(reference_joints[i])}</td>
              <td>{num(target_joints[i])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
