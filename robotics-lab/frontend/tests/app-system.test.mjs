// 通过实际 App 的点击、轮询、查看器状态和观测导出，覆盖系统请求与会话操作的交错。
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { loadFrontendModule } from "./helpers/frontend-module.mjs";
import { deferred, MockLab, mountApp } from "./helpers/app-harness.mjs";

let loaded, App;
before(async () => {
  loaded = await loadFrontendModule("/src/main.tsx");
  ({ App } = loaded.module);
});
after(async () => { await loaded?.close(); });
const sequences = record => record.observations.map(s => s.observation_sequence);
const systemRequests = lab => lab.requests.filter(r => r.path === "/api/system").length;

test("打开前迟到的空会话系统响应不会清空同一会话的历史", async () => {
  const app = await mountApp(App);
  try {
    const old = app.lab.holdSystem();
    await app.tick(2000);
    await app.open();
    await app.record();
    const before = sequences(await app.exported());
    assert.ok(before.length >= 5);
    await app.flush(() => old.resolve());
    const keptViewer = !!app.button("结束实验");
    await app.tick(2000);
    await app.record(2);
    const after = sequences(await app.exported());
    assert.deepEqual(after.slice(0, before.length), before);
    assert.ok(keptViewer, "旧响应不能使已就绪的会话退回未打开状态");
  } finally { await app.close(); }
});

test("结束会话后迟到的旧系统响应不会恢复旧查看器或清空导出记录", async () => {
  const app = await mountApp(App);
  try {
    await app.open();
    await app.record();
    const before = sequences(await app.exported());
    const old = app.lab.holdSystem();
    await app.tick(2000);
    await app.click("结束实验");
    await app.flush(() => old.resolve());
    assert.ok(app.button("打开交互实验"));
    assert.equal(app.dom.window.document.querySelectorAll("iframe").length, 0);
    assert.deepEqual(sequences(await app.exported()), before);
  } finally { await app.close(); }
});

test("切课后旧系统响应不能恢复上一课会话或阻止新实验", async () => {
  const app = await mountApp(App);
  try {
    await app.open();
    const old = app.lab.holdSystem();
    await app.tick(2000);
    await app.click("下一课");
    await app.flush(() => old.resolve());
    assert.ok(app.dom.window.document.querySelector("h1").textContent.includes("joint-control"));
    assert.ok(app.button("打开交互实验"));
    assert.equal(app.dom.window.document.querySelectorAll("iframe").length, 0);
    await app.open();
    assert.equal(app.lab.session.experiment_id, "panda-joint-control");
    assert.ok(app.button("结束实验"));
  } finally { await app.close(); }
});

test("会话创建期间暂停普通系统轮询，完成后恢复轮询", async () => {
  const lab = new MockLab();
  const app = await mountApp(App, lab);
  try {
    lab.createHold = deferred();
    const before = systemRequests(lab);
    await app.click("打开交互实验");
    await app.tick(2000);
    assert.equal(systemRequests(lab), before);
    await app.flush(() => lab.createHold.resolve());
    await app.tick(500);
    assert.equal(systemRequests(lab), before + 1, "操作内部仍能查询启动是否就绪");
    await app.tick(2000);
    assert.equal(systemRequests(lab), before + 2);
  } finally { await app.close(); }
});

test("会话操作失败后恢复系统轮询，保留仍在运行的会话", async () => {
  const app = await mountApp(App);
  try {
    await app.open();
    app.lab.deleteError = "测试结束失败";
    await app.click("结束实验");
    assert.ok(app.dom.window.document.querySelector('[role="alert"]').textContent.includes("测试结束失败"));
    const before = systemRequests(app.lab);
    await app.tick(2000);
    assert.equal(systemRequests(app.lab), before + 1);
    assert.ok(app.button("结束实验"));
    assert.equal(app.button("结束实验").disabled, false);
  } finally { await app.close(); }
});

test("同代次系统轮询乱序时，旧响应不能将就绪状态退回正在启动", async () => {
  const app = await mountApp(App);
  try {
    await app.open();
    const old = app.lab.holdSystem(info => ({ ...info, session: { ...info.session, status: "starting" } }));
    await app.tick(2000);
    await app.tick(2000);
    await app.flush(() => old.resolve());
    assert.equal(app.dom.window.document.querySelectorAll("iframe").length, 1);
    assert.ok(app.dom.window.document.body.textContent.includes("交互实验已就绪"));
  } finally { await app.close(); }
});

test("关闭再打开后，上一会话的迟到响应不能切换当前会话或混入历史", async () => {
  const app = await mountApp(App);
  try {
    await app.open();
    const oldId = app.lab.session.id;
    const old = app.lab.holdSystem();
    await app.tick(2000);
    await app.click("结束实验");
    await app.open();
    await app.record();
    const current = await app.exported();
    assert.notEqual(current.session_id, oldId);
    await app.flush(() => old.resolve());
    const after = await app.exported();
    assert.equal(after.session_id, current.session_id);
    assert.deepEqual(sequences(after), sequences(current));
    assert.ok(after.observations.every(s => s.session_id === current.session_id));
  } finally { await app.close(); }
});

test("初始课程加载较慢时，按最新系统状态选择会话课时", async () => {
  const lab = new MockLab();
  lab.coursesHold = deferred();
  const initial = lab.holdSystem();
  const app = await mountApp(App, lab);
  try {
    lab.startSession("panda-joint-control");
    await app.tick(2000);
    await app.flush(() => { initial.resolve(); lab.coursesHold.resolve(); });
    assert.ok(app.dom.window.document.querySelector("h1").textContent.includes("joint-control"));
    assert.ok(app.dom.window.document.body.textContent.includes("交互实验已就绪"));
    assert.equal(app.dom.window.document.querySelectorAll("iframe").length, 1);
  } finally { await app.close(); }
});
