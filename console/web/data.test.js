import test from "node:test";
import assert from "node:assert/strict";
import {formatNumber, formatTime, sampleAt, mediaFrame, frameForSimulationTime, nodeAt, trajectoryBounds, plotTransform, nearestSample, statusKind} from "./data.js";

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
