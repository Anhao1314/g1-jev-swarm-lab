"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {createState, stepTitle, requestPath, preparationPayload, reasonText, executionView} = require("./app.js");

test("only the current request can populate the displayed contract", () => {
  const state = createState();
  const first = state.begin();
  const second = state.begin();
  assert.equal(state.accept(first, {request_id: "old"}), false);
  assert.equal(state.accept(second, {request_id: "current"}), true);
  assert.equal(state.contract.request_id, "current");
});
test("editing invalidates an existing contract and in-flight response", () => {
  const state = createState();
  const first = state.begin();
  state.accept(first, {request_id: "old"});
  state.edit();
  assert.equal(state.contract, null);
  assert.equal(state.accept(first, {request_id: "late"}), false);
});
test("step labels preserve original quantities and signed angles", () => {
  assert.equal(stepTitle({skill: "walk_forward", parameters: {distance_m: 3}}), "前进 3 米");
  assert.equal(stepTitle({skill: "turn", parameters: {angle_deg: -90}}), "转向 -90°");
  assert.equal(stepTitle({skill: "stand", parameters: {duration_s: 2}}), "站立 2 秒");
  assert.equal(stepTitle({skill: "stop"}), "停止");
});
test("request identifiers cannot change endpoint path or query", () => {
  assert.equal(requestPath("../execute?yes=1"), "/api/requests/..%2Fexecute%3Fyes%3D1");
});
test("unrecognized refusal reasons remain visible rather than disappear", () => {
  assert.equal(reasonText("SOURCE_MISMATCH"), "SOURCE_MISMATCH");
  assert.match(reasonText("D011_BLOCKED"), /BLOCKED/);
});
test("UI has no activation control, unsafe HTML insertion, or replay claim", () => {
  const js = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.doesNotMatch(js, /innerHTML|insertAdjacentHTML|\/api\/(execute|authorize|dispatch)/);
  assert.match(html, /历史回放不会被当作本次执行/);
  assert.match(html, /当前没有新指令的执行画面/);
  assert.match(html, /Language Runtime \/ D011 保持 BLOCKED/);
  assert.doesNotMatch(html, /<canvas|type="checkbox"/);
  assert.match(html, /id="execution-media" hidden/);
  assert.match(html, /id="execution-video" controls preload="none"/);
  assert.match(js, /snapshot\.kind !== "NEW_MUJOCO_CAPTURE"/);
});
test("input limit and displayed counter match the 512-character server contract", () => {
  const js = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.match(html, /maxlength="512"/);
  assert.match(html, /id="character-count">0 \/ 512</);
  assert.match(js, /input\.value\.length\} \/ 512/);
  assert.doesNotMatch(js + html, /2000/);
});
test("preparation belongs to the exact current contract and expires when input changes", () => {
  const state = createState();
  const revision = state.begin();
  state.accept(revision, {contract_sha256: "current"});
  assert.equal(state.acceptPreparation(revision, "wrong", {preparation_id: "wrong"}), false);
  assert.equal(state.acceptPreparation(revision, "current", {preparation_id: "accepted"}), true);
  state.edit();
  assert.equal(state.preparation, null);
  assert.equal(state.acceptPreparation(revision, "current", {preparation_id: "late"}), false);
  const next = state.begin();
  state.accept(next, {contract_sha256: "next"});
  assert.equal(state.acceptPreparation(revision, "current", {preparation_id: "stale"}), false);
  assert.equal(state.preparation, null);
});
test("preparation sends only the bound hash and provides no authorization controls", () => {
  assert.deepEqual(preparationPayload({contract_sha256: "abc", owner: true, mission: {}, source: {}}), {contract_sha256: "abc"});
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.match(html, /准备单次仿真审查/);
  assert.match(html, /准备清单不是执行授权/);
  assert.doesNotMatch(html, /id="(?:execute|approve|authorize)[^"]*"/);
});

function observed(overrides = {}) {
  return {request_id: "request-one", preparation_sha256: "preparation-one", run_id: null,
    status: "AWAITING_OWNER", kind: null, physics_steps: 0, policy_calls: 0, result: null, media: null, ...overrides};
}
const contract = {request_id: "request-one", contract_sha256: "contract-one"};
const preparation = {preparation_sha256: "preparation-one"};

test("observation refuses a different request or preparation identity", () => {
  assert.throws(() => executionView(observed({request_id: "another"}), contract, preparation), /不匹配/);
  assert.throws(() => executionView(observed({preparation_sha256: "stale"}), contract, preparation), /不匹配/);
  assert.throws(() => executionView(observed(), contract, {}), /不匹配/);
});
test("input edits invalidate both stored execution and in-flight observations", () => {
  const state = createState();
  const revision = state.begin();
  state.accept(revision, contract);
  state.acceptPreparation(revision, "contract-one", preparation);
  assert.equal(state.acceptExecution(revision, observed()).status, "AWAITING_OWNER");
  state.edit();
  assert.equal(state.execution, null);
  assert.equal(state.acceptExecution(revision, observed()), false);
  const js = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  assert.match(js, /video\.pause\(\);\s*video\.removeAttribute\("src"\);\s*video\.load\(\)/);
});
test("unknown or malformed execution counts never become measured zero", () => {
  for (const count of [null, undefined, "0", -1, 2.5, Infinity]) {
    const view = executionView(observed({physics_steps: count, policy_calls: count}), contract, preparation);
    assert.equal(view.physics, "UNKNOWN");
    assert.equal(view.policy, "UNKNOWN");
  }
  assert.equal(executionView(observed(), contract, preparation).physics, "0");
});
test("synthetic receipts cannot supply robot media or imply physical mission completion", () => {
  const snapshot = observed({run_id: "test-run", status: "CAPTURE_FINISHED", kind: "SYNTHETIC_NONPHYSICAL_BACKEND"});
  const view = executionView(snapshot, contract, preparation);
  assert.match(view.title, /非物理测试替身/);
  assert.equal(view.media, null);
  assert.throws(() => executionView({...snapshot, media: {url: "/historic.mp4"}}, contract, preparation), /拒绝展示/);
});
test("new media requires matching request path and complete raw-state provenance", () => {
  const media = {url: "/api/requests/request-one/media", kind: "NEW_RUN_STATE_PLAYBACK",
    sha256: "a".repeat(64), source_pose_sha256: "b".repeat(64)};
  const snapshot = observed({run_id: "new-run", status: "CAPTURE_FINISHED", kind: "NEW_MUJOCO_CAPTURE", media});
  assert.equal(executionView(snapshot, contract, preparation).media, media);
  assert.match(executionView(snapshot, contract, preparation).title, /任务是否成功以原始结果为准/);
  for (const changed of [{url: "/api/requests/another/media"}, {source_pose_sha256: null}, {kind: "HISTORICAL_REPLAY"}]) {
    assert.throws(() => executionView({...snapshot, media: {...media, ...changed}}, contract, preparation), /拒绝展示/);
  }
});
test("failure and partial receipt details remain visible without synthesizing success", () => {
  const result = {status: "TECHNICAL_PARTIAL", reason: "WORKER_TIMEOUT", stages: [{strict: false}]};
  const view = executionView(observed({run_id: "partial", kind: "NEW_MUJOCO_CAPTURE",
    status: "REFUSED_FAILED_OR_PARTIAL", physics_steps: null, result}), contract, preparation);
  assert.equal(view.result, result);
  assert.equal(view.physics, "UNKNOWN");
  assert.match(view.title, /拒绝、失败或未完成/);
  assert.throws(() => executionView(observed({status: "SUCCESS"}), contract, preparation), /未知执行状态/);
  assert.throws(() => executionView(observed({run_id: "contradiction"}), contract, preparation), /不一致/);
});
