// 按会话和发布序号统一更新当前状态与历史；仿真时间仅用于记录真实的时间重置。
export type SequencedObservation = {
  session_id: string;
  observation_sequence: number;
  time: number;
  age_seconds?: number;
};

export type ObservationLog<T extends SequencedObservation> = {
  sessionId: string | null;
  current: T | null;
  history: T[];
  limit: number;
};

export type ObservationAction<T extends SequencedObservation> =
  | { type: "session"; sessionId: string | null }
  | { type: "receive"; observation: T; restartHistory?: boolean }
  | { type: "clear" };

export function createObservationLog<T extends SequencedObservation>(limit = 400): ObservationLog<T> {
  if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("观测记录上限需要正整数");
  return { sessionId: null, current: null, history: [], limit };
}

export function reduceObservationLog<T extends SequencedObservation>(
  previous: ObservationLog<T>,
  action: ObservationAction<T>,
): ObservationLog<T> {
  if (action.type === "clear") return createObservationLog<T>(previous.limit);
  if (action.type === "session") {
    if (action.sessionId === previous.sessionId) return previous;
    return {
      ...createObservationLog<T>(previous.limit),
      sessionId: action.sessionId,
      // 结束会话后仍可导出已有记录；打开新会话时不混入上一会话的数据。
      history: action.sessionId === null ? previous.history : [],
    };
  }
  const next = action.observation;
  if (next.session_id !== previous.sessionId || !Number.isFinite(next.time)
    || !Number.isSafeInteger(next.observation_sequence) || next.observation_sequence < 1) return previous;

  // 新试验的命令应答也可能迟到，只删除该命令之前的采样，保留已收到的后续观测。
  let history = previous.history;
  if (action.restartHistory) {
    const kept = history.filter(sample => sample.observation_sequence >= next.observation_sequence);
    if (kept.length !== history.length) history = kept;
  }
  if (previous.current && next.observation_sequence <= previous.current.observation_sequence) {
    let current = previous.current;
    // 同一发布的重复读取仅刷新数据年龄，保留停滞提示，不回写任何物理状态。
    if (next.observation_sequence === current.observation_sequence && next.age_seconds !== undefined
      && Number.isFinite(next.age_seconds) && next.age_seconds > (current.age_seconds ?? 0)) {
      current = { ...current, age_seconds: next.age_seconds };
      if (history.at(-1)?.observation_sequence === current.observation_sequence) {
        history = [...history.slice(0, -1), current];
      }
    }
    return history === previous.history && current === previous.current
      ? previous : { ...previous, current, history };
  }

  // 序号更新后时间才允许回退，此时是实际重置；同一时刻的新状态替换末次采样。
  if (previous.current && next.time < previous.current.time) history = [next];
  else if (history.at(-1)?.time === next.time) history = [...history.slice(0, -1), next];
  else history = [...history, next].slice(-previous.limit);
  return { ...previous, current: next, history };
}
