import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {formatNumber, formatTime, sampleAt, mediaFrame, frameForSimulationTime, nodeAt, runtimeDecisionsAt, runtimeDecisionForEvent, visibleNodeOutcome, trajectoryBounds, plotTransform, nearestSample, statusKind, playbackRange, requestedRunTime, firstWalkDisplaySample} from "./data.js";

test("shows an actual retained sample instead of interpolating an observation", () => {
  const samples = [
    {time_s: 0, node_index: 0, skill: "Walk", x: 0, y: 0, local_lateral_m: -.2, actual_heading_deg: 179},
    {time_s: 1, node_index: 0, skill: "Walk", x: 2, y: 1, local_lateral_m: .2, actual_heading_deg: -179},
  ];
  const display = sampleAt(samples, .5);
  assert.equal(display.x, 0);
  assert.equal(display.local_lateral_m, -.2);
  assert.equal(display.actual_heading_deg, 179);
  assert.equal(display.time_s, 0);
  assert.equal(display.sample_index, 0);
  assert.equal(samples[0].x, 0);
});

test("maps recorded video frames to exact simulation time including the appended final pose", () => {
  const frameMap = [0, .05, .10, .132];
  assert.deepEqual(mediaFrame(frameMap, 20, .11), {index: 2, time_s: .10, media_time_s: .10});
  assert.deepEqual(frameForSimulationTime(frameMap, 20, .132), {index: 3, time_s: .132, media_time_s: .15});
  assert.equal(frameForSimulationTime(frameMap, 20, .126).index, 3);
  assert.equal(frameForSimulationTime(frameMap, 20, .069).index, 1);
});

test("does not invent transitions or unavailable correction signals", () => {
  const samples = [
    {time_s: 0, node_index: 0, skill: "Stand", x: 0, reference_heading_deg: null},
    {time_s: 1, node_index: 1, skill: "Walk", x: 10, reference_heading_deg: 0},
  ];
  assert.equal(sampleAt(samples, .9).skill, "Stand");
  assert.equal(sampleAt(samples, .9).x, 0);
  assert.equal(sampleAt(samples, .9).reference_heading_deg, null);
  assert.equal(sampleAt(samples, 1).skill, "Walk");
  assert.equal(sampleAt([], 1), null);
});

test("route coordinates share a world scale and are not recentered per treatment", () => {
  const runs = [
    {ideal_route: [[0, 0], [12, -4]], samples: [{x: 12, y: -5.8}]},
    {ideal_route: [[0, 0], [12, -4]], samples: [{x: 12, y: -5.1}]},
  ];
  const bounds = trajectoryBounds(runs);
  const plot = plotTransform(bounds, 600, 240);
  const world = [12, -5.8];
  const restored = plot.world(...plot.point(...world));
  assert.ok(Math.abs(restored[0] - world[0]) < 1e-12);
  assert.ok(Math.abs(restored[1] - world[1]) < 1e-12);
  assert.ok(plot.point(12, -5.8)[1] > plot.point(12, -5.1)[1]);
  assert.equal(nearestSample(runs[0].samples, 12, -5.8).y, -5.8);
});

test("source node outcomes are read without evaluating instantaneous drift", () => {
  const run = {nodes: [{index: 0, start_s: 0, end_s: 1, strict_status: "FAIL"}, {index: 1, start_s: 1, end_s: 2, strict_status: "PASS"}]};
  assert.equal(nodeAt(run, .5, {node_index: 0, local_lateral_m: 0}).strict_status, "FAIL");
  assert.equal(statusKind("FAIL"), "fail");
  assert.equal(statusKind("SUCCESS"), "pass");
  assert.equal(statusKind(undefined), "unknown");
});

test("unknown data remains unavailable and signed errors stay signed", () => {
  assert.equal(formatNumber(undefined), "Unavailable");
  assert.equal(formatNumber(null), "Unavailable");
  assert.equal(formatNumber(-1.840337, 3, " m"), "-1.840 m");
  assert.equal(formatTime(53.806), "00:53.81");
});

test("shares first-Walk time but freezes each arm at its own source completion", () => {
  const runs = [{duration_s: 54, authority: {walk_start_s: 10, walk_end_s: 27.1}},
                {duration_s: 53, authority: {walk_start_s: 10, walk_end_s: 26.7}}];
  assert.deepEqual(playbackRange(runs, true), {start: 10, end: 27.1});
  assert.equal(requestedRunTime(runs[1], 27, true), 26.7);
  assert.equal(requestedRunTime(runs[0], 12, true), 12);
  assert.deepEqual(playbackRange(runs, false), {start: 0, end: 54});
  assert.equal(requestedRunTime(runs[1], 27, false), 27);
});

test("nearest completion frame keeps Walk axes without hiding its captured Turn identity", () => {
  const run = {authority: {reference_heading_rad: 0}, samples: [{node_index:1,commanded_heading_deg:10}]};
  const source = {node_index:2,skill:"turn",commanded_heading_deg:-80,actual_heading_deg:7,
    local_lateral_m:0,first_walk_local_lateral_m:.37,first_walk_reference_lateral_m:-.005,first_walk_global_endpoint_error_m:.58};
  const view = firstWalkDisplaySample(run, source);
  assert.equal(view.node_index, 2); assert.equal(view.skill,"turn");
  assert.equal(view.commanded_heading_deg,10); assert.equal(view.heading_error_deg,-3);
  assert.equal(view.local_lateral_m,.37); assert.equal(view.reference_lateral_m,-.005);
  assert.equal(source.commanded_heading_deg,-80); assert.equal(source.local_lateral_m,0);
});

test("closed-loop decisions and outcomes appear only after their recorded times", () => {
  const run = {runtime_kind: "closed_loop_mission", runtime_decisions: [
    {time_s: 1, decision: "CONTINUE"}, {time_s: 3, decision: "STOP"}]};
  const node = {end_s: 2, strict_status: "FAIL"};
  assert.deepEqual(runtimeDecisionsAt(run, .5), []);
  assert.deepEqual(runtimeDecisionsAt(run, 1.5).map(item => item.decision), ["CONTINUE"]);
  assert.deepEqual(runtimeDecisionsAt(run, 3).map(item => item.decision), ["CONTINUE", "STOP"]);
  assert.equal(visibleNodeOutcome(run, node, 1.99), false);
  assert.equal(visibleNodeOutcome(run, node, 2), true);
  assert.equal(visibleNodeOutcome({}, node, 0), true);
});

test("Inspector distinguishes same-time handoff refusals by exact source identity", () => {
  const decisions = [
    {node_index: null, time_s: 14, source_locator: "lifecycle_events.json#/5", decision: "trusted_handoff_rejected", evaluation: {reason: "PLAN_CHANGED"}},
    {node_index: null, time_s: 14, source_locator: "lifecycle_events.json#/6", decision: "trusted_handoff_rejected", evaluation: {reason: "PRINCIPAL_INVALID"}},
    {node_index: null, time_s: 14, source_locator: "qualification.json", decision: "QUALIFICATION_RECORDED", evaluation: {physics_steps_delta: 0}},
  ];
  const run = {runtime_kind: "closed_loop_mission", runtime_decisions: decisions};
  assert.equal(runtimeDecisionForEvent(run, {...decisions[1]}), decisions[1]);
  assert.equal(runtimeDecisionForEvent(run, {...decisions[2]}), decisions[2]);
  assert.equal(runtimeDecisionForEvent(run, {node_index: null, time_s: 14, source_locator: "unknown.json"}), null);
  assert.equal(runtimeDecisionForEvent(run, {node_index: null, time_s: 14}), decisions[0]);
});

test("physical halt status and request remain distinct from task block", () => {
  const run = {runtime_kind: "closed_loop_mission", runtime_decisions: [
    {time_s: 12, decision: "STOP_DEPENDENTS"},
    {time_s: 12, decision: "PHYSICAL_HALT_REQUESTED"},
    {time_s: 13.4, decision: "HALT_SUCCEEDED"}]};
  assert.deepEqual(runtimeDecisionsAt(run, 11.9), []);
  assert.deepEqual(runtimeDecisionsAt(run, 12).map(item => item.decision),
    ["STOP_DEPENDENTS", "PHYSICAL_HALT_REQUESTED"]);
  assert.deepEqual(runtimeDecisionsAt(run, 13.4).map(item => item.decision),
    ["STOP_DEPENDENTS", "PHYSICAL_HALT_REQUESTED", "HALT_SUCCEEDED"]);
  assert.equal(statusKind("HALT_SUCCEEDED"), "pass");
  assert.equal(statusKind("HALT_FAILED"), "fail");
});

test("lifecycle authorization is revealed at its recorded time and keeps mission identities distinct", () => {
  const run = {runtime_kind: "closed_loop_mission", runtime_decisions: [
    {time_s: 12, mission_id: "original", decision: "STOP_DEPENDENTS"},
    {time_s: 14, mission_id: "original", decision: "HALT_SUCCEEDED"},
    {time_s: 14, mission_id: "new", decision: "new_mission_authorized"},
    {time_s: 26, mission_id: "new", decision: "new_mission_completed"}]};
  assert.equal(runtimeDecisionsAt(run, 13.9).length, 1);
  assert.deepEqual(runtimeDecisionsAt(run, 14).map(item => item.mission_id), ["original", "original", "new"]);
  assert.equal(runtimeDecisionsAt(run, 25.99).some(item => item.decision === "new_mission_completed"), false);
});

test("range seek preserves the appended non-grid final state and reveals completion", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const seek = html.match(/<input\b[^>]*id="seek"[^>]*>/)?.[0];
  assert.ok(seek?.includes('step="any"'), "range input must not round final physics time to a centisecond");
  const finalTime = 26.255999999996327;
  const frame = frameForSimulationTime([26.20, 26.25, finalTime], 20, finalTime);
  assert.equal(frame.time_s, finalTime);
  const run = {runtime_kind: "closed_loop_mission", runtime_decisions: [{time_s: finalTime, decision: "new_mission_completed"}]};
  assert.equal(runtimeDecisionsAt(run, 26.25).length, 0);
  assert.equal(runtimeDecisionsAt(run, frame.time_s)[0].decision, "new_mission_completed");
});
