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
  tool_rotation: number[][];
  gripper_width: number;
  actuator_torque: number[];
  gravity_torque: number[];
  jacobian: number[][];
  cartesian_velocity: number[];
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
  } | null;
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
export const GEOMETRIC = ["structure", "fk", "jacobian", "ik"];
export function defaults(mode = "structure"): Settings {
  return {
    joints: [...HOME],
    target: [0.45, 0.12, 0.42],
    gripper_width: 0.08,
    gain_scale: ["joint-control", "trajectory"].includes(mode) ? 0.2 : 1,
    compensation: true,
    velocity: Array(7).fill(0),
    profile: "quintic",
    friction: 1,
  };
}
export const num = (value: number, digits = 4) => value.toFixed(digits);
