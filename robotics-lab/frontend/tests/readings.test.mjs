// 通过实际 React 组件的静态渲染核对观测内容，复用 Vite 的 TSX 转换且不启动网络服务。
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { loadFrontendModule } from "./helpers/frontend-module.mjs";

let loaded;
let Readings;
let Chart;

before(async () => {
  loaded = await loadFrontendModule("/src/widgets.tsx");
  ({ Readings, Chart } = loaded.module);
});

after(async () => {
  await loaded?.close();
});

function observation(count = 7) {
  const joints = Array.from({ length: count }, (_, i) => (i - count) / 10);
  return {
    time: 0.2,
    age_seconds: 0,
    joints,
    reference_joints: joints.map(q => q + 0.01),
    target_joints: joints.map(q => q + 0.02),
    tool_position: [0.5, 0, 0.4],
    tool_rotation: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    gripper_width: 0.04,
    actuator_torque: joints.map(() => 0),
    gravity_torque: joints.map(() => 0),
  };
}

function readings(state, live = true) {
  return renderToStaticMarkup(createElement(Readings, { state, mode: "structure", live }));
}

function jointTable(html) {
  const match = html.match(/<table\b[^>]*aria-label="关节角度观测"[^>]*>[\s\S]*?<\/table>/);
  assert.ok(match, "结构课应提供实际、参考和目标关节角观测");
  return match[0];
}

for (const live of [true, false]) {
  test(`结构课${live ? "实时" : "独立末态"}提供默认折叠的关节角表`, () => {
    const html = readings(observation(), live);
    const table = jointTable(html);
    for (const label of ["实际 / rad", "参考 / rad", "目标 / rad"]) {
      assert.ok(table.includes(label));
    }
    assert.match(html, /<details><summary>关节实际角、参考角与目标角<\/summary>/);
  });
}

for (const count of [3, 9]) {
  test(`关节角表按观测生成 ${count} 行，三列分别读取对应状态`, () => {
    const state = observation(count);
    const body = jointTable(readings(state)).match(/<tbody>([\s\S]*?)<\/tbody>/)[1];
    const rows = [...body.matchAll(/<tr>([\s\S]*?)<\/tr>/g)];
    assert.equal(rows.length, count);
    // 三组状态刻意取不同值，防止把目标或参考误显示为实际角度。
    rows.forEach((row, i) => {
      const cells = [...row[1].matchAll(/<t[dh]\b[^>]*>(.*?)<\/t[dh]>/g)].map(cell => cell[1]);
      assert.deepEqual(cells, [
        String(i + 1),
        state.joints[i].toFixed(4),
        state.reference_joints[i].toFixed(4),
        state.target_joints[i].toFixed(4),
      ]);
    });
  });
}

test("没有观测时保留等待提示，不生成关节角表", () => {
  const html = readings(undefined);
  assert.ok(html.includes("等待实验数据"));
  assert.doesNotMatch(html, /aria-label="关节角度观测"/);
});

test("旧正运动学模式也保留关节角观测", () => {
  const html = renderToStaticMarkup(createElement(Readings, {
    state: observation(), mode: "fk", live: true,
  }));
  jointTable(html);
});

test("结构课主图继续显示末端三轴世界位置", () => {
  const state = observation();
  const samples = [state, { ...state, time: 0.4 }];
  const html = renderToStaticMarkup(createElement(Chart, { samples, mode: "structure", joint: 1 }));
  assert.match(html, /aria-label="末端世界位置 \/ m"/);
  for (const axis of ["X", "Y", "Z"]) assert.ok(html.includes(`>${axis}</span>`));
  assert.doesNotMatch(html, /aria-label="关节 /);
});

test("关节控制课保留既有观测表，不新增结构课的折叠表", () => {
  const html = renderToStaticMarkup(createElement(Readings, {
    state: observation(), mode: "joint-control", live: true, joint: 0,
  }));
  assert.ok(html.includes("关节角度、执行器力矩与重力项"));
  assert.doesNotMatch(html, /aria-label="关节角度观测"/);
});
