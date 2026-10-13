"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {createState, stepTitle, requestPath, preparationPayload, reasonText} = require("./app.js");

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
  assert.doesNotMatch(html, /<video|<canvas|type="checkbox"/);
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
