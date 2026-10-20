// 复现轮询与命令应答乱序，检查当前状态、历史及会话切换由同一更新过程维护。
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { loadFrontendModule } from "./helpers/frontend-module.mjs";

let loaded;
let createObservationLog;
let reduceObservationLog;
const SESSION = "current-session";

before(async () => {
  loaded = await loadFrontendModule("/src/observations.ts");
  ({ createObservationLog, reduceObservationLog } = loaded.module);
});
after(async () => { await loaded?.close(); });

function observation(sequence, time, extra = {}) {
  return { session_id: SESSION, observation_sequence: sequence, time, age_seconds: 0, ...extra };
}

function receive(log, next, restartHistory = false) {
  return reduceObservationLog(log, { type: "receive", observation: next, restartHistory });
}

function activeLog(limit) {
  return reduceObservationLog(createObservationLog(limit), { type: "session", sessionId: SESSION });
}

function seed() {
  return [0, 0.2, 0.4].reduce((log, time, i) => receive(log, observation(i + 1, time)), activeLog());
}

test("暂停单步应答先到，旧轮询不会覆盖当前状态或清空历史", () => {
  const stepped = receive(seed(), observation(5, 0.401, { paused: true }));
  const delayedPoll = observation(4, 0.4, { paused: true });
  const result = receive(stepped, delayedPoll);
  assert.equal(result, stepped);
  assert.equal(result.current.time, 0.401);
  assert.deepEqual(result.history.map(s => s.time), [0, 0.2, 0.4, 0.401]);
});

test("较新轮询先到时，迟到的普通命令应答也被忽略", () => {
  const polled = receive(seed(), observation(6, 0.6));
  assert.equal(receive(polled, observation(5, 0.5)), polled);
});

test("轮询乱序或缓存返回旧序号时不触发时间重置", () => {
  const latest = receive(seed(), observation(6, 0.6));
  assert.equal(receive(latest, observation(4, 0.1)), latest);
  assert.equal(receive(latest, observation(6, 0.6)), latest);
});

test("重复读取同一发布时继续更新数据年龄，但不覆盖物理状态或增加采样", () => {
  const previous = receive(seed(), observation(4, 0.4, { reference_joints: [0.3] }));
  const result = receive(previous, observation(4, 0.4, {
    age_seconds: 3, reference_joints: [99],
  }));
  assert.equal(result.current.age_seconds, 3);
  assert.deepEqual(result.current.reference_joints, [0.3]);
  assert.equal(result.history.length, previous.history.length);
  assert.equal(result.history.at(-1), result.current);
  assert.equal(receive(result, observation(4, 0.4, { age_seconds: 1 })), result);
  assert.equal(receive(result, observation(5, 0.5)).current.age_seconds, 0);
});

test("序号递增而时间回到零时开始新记录，随后旧响应不能混入", () => {
  const reset = observation(5, 0);
  const result = receive(seed(), reset);
  assert.deepEqual(result.history, [reset]);
  assert.equal(receive(result, observation(4, 0.5)), result);
  const resumed = receive(result, observation(6, 0.001));
  assert.deepEqual(resumed.history.map(s => s.time), [0, 0.001]);
});

test("较新重置应答包含零时刻，并拒绝随后迟到的重置前采样", () => {
  const result = receive(seed(), observation(5, 0), true);
  assert.deepEqual(result.history.map(s => s.observation_sequence), [5]);
  assert.equal(receive(result, observation(4, 0.5)), result);
});

test("重置应答晚于继续后的轮询时，保留重置之后的较新观测", () => {
  let log = receive(activeLog(), observation(1, 0));
  log = receive(log, observation(2, 0.001));
  // 重置后时间已经超过上一采样，仍应依照命令序号清除旧试验记录。
  log = receive(log, observation(4, 0.01));
  const result = receive(log, observation(3, 0), true);
  assert.equal(result.current, log.current);
  assert.deepEqual(result.history.map(s => s.observation_sequence), [4]);
  assert.equal(receive(result, observation(2, 0.001)), result);
});

test("雅可比等时间不归零的新试验也能过滤命令之前的历史", () => {
  let log = receive(seed(), observation(4, 0.5));
  log = receive(log, observation(6, 0.6));
  const result = receive(log, observation(5, 0.5), true);
  assert.equal(result.current.observation_sequence, 6);
  assert.deepEqual(result.history.map(s => s.observation_sequence), [6]);
});

test("暂停时同一仿真时刻的新状态替换末次采样，不产生重复时间点", () => {
  const previous = seed();
  const configured = observation(4, 0.4, { reference_joints: [0.3] });
  const result = receive(previous, configured);
  assert.equal(result.current, configured);
  assert.equal(result.history.length, previous.history.length);
  assert.equal(result.history.at(-1), configured);
  assert.equal(previous.history.at(-1).observation_sequence, 3);
});

test("同一暂停时刻重新开始试验时仍保留最新应答", () => {
  const result = receive(seed(), observation(4, 0.4), true);
  assert.deepEqual(result.history.map(s => s.observation_sequence), [4]);
});

test("切换会话后允许新会话从小序号开始，并拒绝旧会话响应", () => {
  const switched = reduceObservationLog(seed(), { type: "session", sessionId: "new-session" });
  const first = observation(1, 0, { session_id: "new-session" });
  const result = receive(switched, first);
  assert.deepEqual(result.history, [first]);
  assert.equal(receive(result, observation(99, 20), true), result);
});

test("结束会话后保留可导出历史，并拒绝所有旧观测", () => {
  const previous = seed();
  const stopped = reduceObservationLog(previous, { type: "session", sessionId: null });
  assert.equal(stopped.current, null);
  assert.equal(stopped.history, previous.history);
  assert.equal(receive(stopped, observation(9, 1)), stopped);
});

test("重复激活同一会话不清空记录，切课清空后也不接受旧响应", () => {
  const previous = seed();
  assert.equal(reduceObservationLog(previous, { type: "session", sessionId: SESSION }), previous);
  const cleared = reduceObservationLog(previous, { type: "clear" });
  assert.equal(cleared.current, null);
  assert.deepEqual(cleared.history, []);
  assert.equal(receive(cleared, observation(9, 1)), cleared);
});

test("记录长度遵循配置上限，丢弃旧采样后仍拒绝迟到响应", () => {
  let log = activeLog(3);
  for (let i = 1; i <= 8; i++) log = receive(log, observation(i, i / 10));
  assert.deepEqual(log.history.map(s => s.observation_sequence), [6, 7, 8]);
  assert.equal(receive(log, observation(1, 0.1)), log);
});

test("缺失、非法或越界发布序号不能更新状态或清空历史", () => {
  const log = seed();
  for (const sequence of [undefined, NaN, Infinity, 0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(receive(log, observation(sequence, 0), true), log);
  }
  assert.throws(() => createObservationLog(0), /正整数/);
});
