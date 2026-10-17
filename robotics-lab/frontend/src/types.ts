export type Lesson = {
  id: string;
  experiment_id: string;
  title: string;
  question: string;
  summary: string;
  mode: string;
  adapter: string;
  prerequisites: string;
  concepts: { title: string; text: string; formula: string }[];
  steps: string[];
  observations: string[];
  exercise: string;
  sources: { title: string; url: string }[];
};
export type Course = {
  id: string;
  title: string;
  subtitle: string;
  robot: string;
  description: string;
  level: string;
  lessons: Lesson[];
};
export type Session = {
  id: string;
  experiment_id: string;
  status: string;
  port: number;
  url?: string | null;
  error: string | null;
};
export type System = {
  version: string;
  viewer: {
    available: boolean;
    platform: string;
    mujoco: string;
    reason: string;
  };
  session: Session | null;
};
export type Observation = {
  time: number;
  joints: number[];
  reference_joints: number[];
  target_joints: number[];
  velocities: number[];
  tool_position: number[];
  tool_target_error_m?: number;
  tool_rotation: number[][];
  gripper_width: number;
  actuator_torque: number[];
  gravity_torque: number[];
  jacobian: number[][];
  cartesian_velocity: number[];
  measured_cartesian_velocity?: number[];
  velocity_comparison?: VelocityComparison | null;
  jacobian_running?: boolean;
  joint_displacement_rad?: number;
  tool_height_change_m?: number;
  compensation_torque?: number[];
  compensation: boolean;
  singular_values: number[];
  paused: boolean;
  age_seconds: number;
  session_id: string;
  phase: string;
  cube_position: number[];
  contacts: number;
  grasp_lifted: boolean;
  place_success: boolean;
  ik: {
    converged: boolean;
    iterations: number;
    position_error_m: number;
    target_applied?: boolean;
  } | null;
};
export type VelocityComparison = {
  time: number;
  dt: number;
  joint_index: number;
  joint_velocities: number[];
  jacobian: number[][];
  predicted: number[];
  measured: number[];
  error_norm: number;
};
export type Sample = {
  time: number;
  value?: number;
  joints?: number[];
  reference_joints?: number[];
  joint_error?: number;
  cube_height?: number;
  cube_position?: number[];
  tool_position?: number[];
  cartesian_velocity?: number[];
  measured_cartesian_velocity?: number[];
};
export type Run = {
  id: string;
  samples: Sample[];
  state?: Observation;
  metrics: Record<string, number>;
  experiment: { observable_name: string; observable_unit: string };
};
export type Settings = {
  joints: number[];
  target: number[];
  gripper_width: number;
  gain_scale: number;
  damping_scale: number;
  compensation: boolean;
  velocity: number[];
  profile: string;
  friction: number;
};
export const HOME = [0, 0, 0, -1.57079, 0, 1.57079, -0.7853];
export const LIMITS = [
  [-2.8973, 2.8973],
  [-1.7628, 1.7628],
  [-2.8973, 2.8973],
  [-3.0718, -0.0698],
  [-2.8973, 2.8973],
  [-0.0175, 3.7525],
  [-2.8973, 2.8973],
];
export const GEOMETRIC = ["jacobian"];
export const canonicalLessonId = (id: string) =>
  id === "panda-fk" ? "panda-structure" : id;
export function defaults(mode = "structure"): Settings {
  return {
    joints: [...HOME],
    target: [0.45, 0.12, 0.42],
    gripper_width: 0.08,
    gain_scale: ["structure", "joint-control", "ik", "trajectory"].includes(
      mode,
    )
      ? 0.2
      : 1,
    damping_scale: ["structure", "joint-control", "ik", "trajectory"].includes(
      mode,
    )
      ? Math.sqrt(0.2)
      : 1,
    compensation: true,
    velocity: mode === "jacobian" ? [0, 0.05, 0, 0, 0, 0, 0] : Array(7).fill(0),
    profile: "quintic",
    friction: 1,
  };
}
export const num = (value: number, digits = 4) => value.toFixed(digits);
