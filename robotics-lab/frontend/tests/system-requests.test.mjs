// 单独检查请求取消、发布队列和操作退出路径，补充实际应用的网络交错测试。
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { loadFrontendModule } from "./helpers/frontend-module.mjs";

let loaded, SystemRequests;
before(async () => {
  loaded = await loadFrontendModule("/src/system-requests.ts");
  ({ SystemRequests } = loaded.module);
});
after(async () => { await loaded?.close(); });

function harness() {
  const pending = [], publications = [];
  let state = null;
  const requests = new SystemRequests(signal => new Promise((resolve, reject) => {
    pending.push({ signal, resolve, reject });
  }), update => publications.push(update));
  return {
    requests, pending,
    flush() { for (const update of publications.splice(0)) state = update(state); return state; },
  };
}

test("操作前已排队但尚未执行的 React 发布不能覆盖操作结果", async () => {
  const h = harness();
  const read = h.requests.read();
  h.pending[0].resolve({ version: "test", session: null });
  await read;
  await h.requests.change(async change => {
    h.requests.update(previous => ({ ...previous, session: "new-session" }), change);
  });
  assert.deepEqual(h.flush(), { version: "test", session: "new-session" });
});

test("调用方取消请求后，忽略取消信号的迟到响应仍不能发布", async () => {
  const h = harness(), controller = new AbortController();
  const read = h.requests.read({ signal: controller.signal });
  controller.abort();
  assert.ok(h.pending[0].signal.aborted);
  h.pending[0].resolve({ session: "old-session" });
  assert.equal(await read, null);
  assert.equal(h.flush(), null);
});

test("取消组件生命周期时，未完成的请求及排队发布都失效", async () => {
  const h = harness();
  const first = h.requests.read();
  h.pending[0].resolve({ session: "old-session" });
  await first;
  const second = h.requests.read();
  h.requests.cancel();
  h.pending[1].resolve({ session: "another-old-session" });
  assert.equal(await second, null);
  assert.equal(h.flush(), null);
});

test("真实网络错误正常上报，后续系统请求仍能完成", async () => {
  const h = harness();
  const failed = h.requests.read();
  h.pending[0].reject(new Error("network failed"));
  await assert.rejects(failed, /network failed/);
  const recovered = h.requests.read();
  h.pending[1].resolve({ session: null });
  await recovered;
  assert.deepEqual(h.flush(), { session: null });
});

test("同一时刻只允许一个会话操作，失败后解除限制", async () => {
  const h = harness();
  let release, token;
  const change = h.requests.change(async current => {
    token = current;
    await new Promise(resolve => { release = resolve; });
    throw new Error("operation failed");
  });
  await assert.rejects(h.requests.change(async () => {}), /正在进行/);
  assert.equal(await h.requests.read(), null);
  release();
  await assert.rejects(change, /operation failed/);
  assert.throws(() => h.requests.update(() => ({}), token), /已失效/);
  const read = h.requests.read();
  assert.equal(h.pending.length, 1);
  h.pending[0].resolve({ session: null });
  await read;
});

test("操作结束时取消未等待的内部查询，普通轮询可以重新开始", async () => {
  const h = harness();
  let pendingRead;
  await h.requests.change(async change => { pendingRead = h.requests.read({ change }); });
  assert.ok(h.pending[0].signal.aborted);
  h.pending[0].resolve({ session: "outdated" });
  assert.equal(await pendingRead, null);
  const read = h.requests.read();
  h.pending[1].resolve({ session: "current" });
  await read;
  assert.deepEqual(h.flush(), { session: "current" });
});
