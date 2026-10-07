// Only display transforms live here. Frozen evidence, thresholds, and scores stay on disk.
export const finite = value => typeof value === "number" && Number.isFinite(value);
export const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
export const formatNumber = (value, decimals = 3, unit = "") => finite(value) ? `${value.toFixed(decimals)}${unit}` : "Unavailable";
export function formatTime(value) {
  if (!finite(value)) return "--:--.--";
  const time = Math.max(0, value);
  return `${Math.floor(time / 60).toString().padStart(2, "0")}:${(time % 60).toFixed(2).padStart(5, "0")}`;
}
export function wrapDegrees(value) { return ((value + 180) % 360 + 360) % 360 - 180; }
export function sampleAt(samples, time) {
  if (!samples?.length) return null;
  let lo = 0, hi = samples.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (samples[mid].time_s <= time) lo = mid; else hi = mid - 1;
  }
  // Show a recorded sample, never a synthetic interpolated observation.
  return {...samples[lo], sample_index: lo};
}
export function mediaFrame(frameMap, fps, mediaTime) {
  if (!frameMap?.length || !finite(fps) || fps <= 0) return null;
  const index = clamp(Math.floor(mediaTime * fps + 1e-7), 0, frameMap.length - 1);
  return {index, time_s: frameMap[index], media_time_s: index / fps};
}
export function frameForSimulationTime(frameMap, fps, time) {
  if (!frameMap?.length || !finite(fps) || fps <= 0) return null;
  let lo = 0, hi = frameMap.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (frameMap[mid] <= time) lo = mid; else hi = mid - 1;
  }
  const next = Math.min(lo + 1, frameMap.length - 1);
  const index = Math.abs(frameMap[next] - time) < Math.abs(frameMap[lo] - time) ? next : lo;
  return {index, time_s: frameMap[index], media_time_s: index / fps};
}
export function nodeAt(run, time, sample = null) {
  const fromSample = run.nodes?.find(node => node.index === sample?.node_index);
  return fromSample ?? run.nodes?.find(node => node.start_s <= time && time <= node.end_s) ?? null;
}
export function statusKind(value) {
  const name = String(value ?? "").toUpperCase();
  if (["PASS", "SUCCESS", "TRUE", "SUCCEEDED"].includes(name)) return "pass";
  if (["FAIL", "FAILED", "FALSE", "FAILURE", "EXCESSIVE_DRIFT"].includes(name)) return "fail";
  return "unknown";
}
export function trajectoryBounds(runs) {
  const points = runs.flatMap(run => [...(run.ideal_route ?? []), ...(run.samples ?? []).map(sample => [sample.x, sample.y])]).filter(point => finite(point[0]) && finite(point[1]));
  if (!points.length) return {minX: -1, maxX: 1, minY: -1, maxY: 1};
  const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
  const padding = .6;
  return {minX: Math.min(...xs) - padding, maxX: Math.max(...xs) + padding, minY: Math.min(...ys) - padding, maxY: Math.max(...ys) + padding};
}
export function plotTransform(bounds, width, height, padding = 24) {
  const spanX = Math.max(.01, bounds.maxX - bounds.minX), spanY = Math.max(.01, bounds.maxY - bounds.minY);
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const left = (width - spanX * scale) / 2, top = (height - spanY * scale) / 2;
  return {
    scale,
    point: (x, y) => [left + (x - bounds.minX) * scale, height - top - (y - bounds.minY) * scale],
    world: (x, y) => [bounds.minX + (x - left) / scale, bounds.minY + (height - top - y) / scale],
  };
}
export function nearestSample(samples, x, y) {
  let match = null, distance = Infinity;
  for (const sample of samples ?? []) {
    if (!finite(sample.x) || !finite(sample.y)) continue;
    const squared = (sample.x - x) ** 2 + (sample.y - y) ** 2;
    if (squared < distance) { distance = squared; match = sample; }
  }
  return match;
}
