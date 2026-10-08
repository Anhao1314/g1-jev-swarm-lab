import {finite, clamp, formatNumber, formatTime, sampleAt, mediaFrame, frameForSimulationTime, nodeAt, runtimeDecisionsAt, visibleNodeOutcome, statusKind, trajectoryBounds, plotTransform, nearestSample, playbackRange, requestedRunTime, firstWalkDisplaySample} from "./data.js";
import {armColors, renderAuthority, renderMechanismCharts} from "./mechanism.js";

const $ = id => document.getElementById(id);
const state = {runs: [], catalog: null, walkFocus: false, active: 0, compare: false, time: 0, playing: false, rate: 1, startWall: 0, startTime: 0, frame: 0, lastDraw: 0, evidence: new Map(), lastFocus: null};
const svgNS = "http://www.w3.org/2000/svg";
const skillLabels = {stand: "Stand", walk_forward: "Walk", turn: "Turn", turn_in_place: "Turn", stop: "Stop"};
const skillLabel = value => skillLabels[value] ?? value ?? "Unavailable";
const metricDefinitions = [
  {key: "skill", label: "Current skill", format: skillLabel},
  {key: "time_s", label: "Simulation time", format: value => formatNumber(value, 2, " s")},
  {key: "actual_heading_deg", label: "Actual heading", format: value => formatNumber(value, 2, "°"), description: "Robot yaw in the world frame."},
  {key: "commanded_heading_deg", label: "Commanded heading", format: value => formatNumber(value, 2, "°"), description: "Frozen ideal mission heading."},
  {key: "reference_heading_deg", label: "Correction reference", format: value => formatNumber(value, 2, "°"), description: "Walking correction heading. Unavailable outside a Walk node."},
  {key: "local_lateral_m", label: "Local lateral error", format: value => formatNumber(value, 3, " m"), description: "Signed displacement in the historical actual node-start frame. Display only; no new scoring."},
  {key: "reference_lateral_m", label: "Reference-frame lateral", format: value => formatNumber(value, 3, " m"), description: "Signed offset from the fixed first-Walk correction reference. This is distinct from the local strict measurement frame."},
  {key: "global_endpoint_error_m", label: "Global endpoint error", format: value => formatNumber(value, 3, " m"), description: "World distance to the frozen commanded endpoint of this node; first-Walk target in Walk focus."},
  {key: "residual_action", label: "Residual action (normalized)", format: value => Array.isArray(value) ? `[${value.map(v => formatNumber(v, 2)).join(", ")}]` : "Unavailable"},
  {key: "global_lateral_m", label: "Global lateral error", format: value => formatNumber(value, 3, " m"), description: "Signed displacement relative to the planned route and commanded axis. Display only."},
  {key: "heading_error_deg", label: "Ideal heading error", format: value => formatNumber(value, 2, "°"), description: "Wrapped actual heading minus commanded heading."},
];

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = String(text);
  return item;
}
function svgElement(tag, attributes = {}) {
  const item = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, String(value));
  return item;
}
function statusPill(label, value) {
  const display = typeof value === "boolean" ? (value ? "PASS" : "FAIL") : (value ?? "Unavailable");
  return element("span", `status-pill ${statusKind(display)}`, `${label} ${display}`);
}
function announce(message) { $("announcement").textContent = message; }
function showError(message) {
  $("error-banner").textContent = message;
  $("error-banner").hidden = false;
}
async function getJSON(url) {
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) throw new Error(`${response.status} while reading ${url}`);
  return response.json();
}
function currentRun() { return state.runs[state.active]; }
function visibleRuns() { return state.compare ? state.runs : [currentRun()].filter(Boolean); }
function timeRange() { return playbackRange(visibleRuns(), state.walkFocus); }
function duration() { return timeRange().end; }
function displayTime(time) { return time - timeRange().start; }
function videoFor(run) { return document.querySelector(`video[data-run-index="${state.runs.indexOf(run)}"]`); }
function mediaTime(run, time) {
  return frameForSimulationTime(run.frame_map, run.frame_fps, time)?.media_time_s ?? Math.max(0, time - (run.video_time_offset_s ?? 0));
}
function recordedSample(run) {
  const video = videoFor(run);
  const presentedTime = video?._presentedMediaTime;
  const mediaClock = finite(presentedTime) ? presentedTime : video?.currentTime;
  const frame = video?.readyState > 0 ? mediaFrame(run.frame_map, run.frame_fps, mediaClock) : frameForSimulationTime(run.frame_map, run.frame_fps, state.time);
  const sample = frame && run.samples.length === run.frame_map.length ? {...run.samples[frame.index], sample_index: frame.index} : sampleAt(run.samples, frame?.time_s ?? requestedRunTime(run, state.time, state.walkFocus));
  if (state.walkFocus) return firstWalkDisplaySample(run, sample);
  return sample;
}

function buildVideos() {
  $("video-grid").replaceChildren();
  for (const [index, run] of state.runs.entries()) {
    const card = element("article", "video-card");
    card.style.setProperty("--arm-color", armColors[index % armColors.length]);
    card.dataset.runIndex = index;
    const header = element("div", "video-card-header");
    const label = element("div", "video-label");
    label.append(element("span", `arm-dot${index ? " secondary" : ""}`), element("span", "", run.label));
    const identity = element("div", "video-identity");
    const caseOutcomes = element("div", "case-outcomes");
    if (run.runtime_kind === "closed_loop_mission") caseOutcomes.append(element("span", "case-outcomes-label", "Case"), element("span", "small muted", "Outcome at completion"));
    else caseOutcomes.append(element("span", "case-outcomes-label", "Case"), statusPill("Nominal", run.summary?.task_status), statusPill("Strict", run.summary?.strict_status), statusPill("Physical", run.summary?.physical_status));
    identity.append(label, caseOutcomes);
    const meta = element("div", "video-meta", run.risk_context ?? run.media_caption ?? "Residual off · derived replay");
    const focus = element("button", "video-focus", "Inspect this arm");
    focus.type = "button";
    focus.addEventListener("click", () => setActive(index));
    header.append(identity, meta, focus);
    const viewport = element("div", "video-viewport");
    const video = element("video");
    video.src = run.video_url;
    video.preload = "auto";
    video.muted = true;
    video.playsInline = true;
    video.dataset.runIndex = index;
    video.setAttribute("aria-label", `Native MuJoCo rendered Unitree G1 — ${run.label}`);
    const loading = element("div", "video-load-state", "Loading native MuJoCo visual replay…");
    video.addEventListener("loadeddata", () => { loading.hidden = true; synchronizeVideos(true); });
    video.addEventListener("seeked", () => { if (!state.playing) drawPlayhead(); });
    if (typeof video.requestVideoFrameCallback === "function") {
      const onPresentedFrame = (_wall, metadata) => {
        video._presentedMediaTime = metadata.mediaTime;
        if (state.runs.length) drawPlayhead();
        video.requestVideoFrameCallback(onPresentedFrame);
      };
      video.requestVideoFrameCallback(onPresentedFrame);
    }
    video.addEventListener("error", () => {
      loading.hidden = false;
      loading.textContent = "Video unavailable. Source evidence remains inspectable.";
      showError(`Cannot decode the verified video for ${run.label}. No substitute visual has been generated.`);
    });
    viewport.append(video, loading);
    card.append(header, viewport);
    $("video-grid").append(card);
  }
}

function updateLayout() {
  $("video-grid").classList.toggle("compare", state.compare);
  $("video-grid").style.setProperty("--arm-count", visibleRuns().length);
  $("metrics").style.setProperty("--arm-count", visibleRuns().length);
  $("node-outcomes").style.setProperty("--arm-count", visibleRuns().length);
  document.querySelectorAll(".video-card").forEach((card, index) => {
    card.hidden = !state.compare && index !== state.active;
    const focus = card.querySelector(".video-focus");
    focus.hidden = !state.compare;
    focus.classList.toggle("current", index === state.active);
    focus.textContent = index === state.active ? "Inspector focus" : "Inspect this arm";
  });
  $("single-view").classList.toggle("active", !state.compare);
  $("compare-view").classList.toggle("active", state.compare);
  $("single-view").setAttribute("aria-pressed", !state.compare);
  $("compare-view").setAttribute("aria-pressed", state.compare);
  $("metrics").classList.toggle("comparing", state.compare);
  $("seek").min = timeRange().start; $("seek").max = duration();
  $("seek").setAttribute("aria-label", state.walkFocus ? "Walk-relative time; 0s is the original first-Walk start" : "Simulation time");
  $("duration").textContent = formatTime(duration() - timeRange().start);
  drawEvents();
  synchronizeVideos(true);
  drawPlayhead();
}
function setActive(index) {
  if (!state.runs[index]) return;
  state.active = index;
  $("treatment").value = String(index);
  state.time = Math.min(state.time, duration());
  resetWallClock();
  updateLayout();
  announce(`Inspector focus: ${currentRun().label}`);
}
function setCompare(compare) {
  state.compare = compare;
  state.time = Math.min(state.time, duration());
  resetWallClock();
  updateLayout();
}
function synchronizeVideos(force = false) {
  for (const run of state.runs) {
    const video = videoFor(run);
    if (!video) continue;
    const visible = state.compare || run === currentRun();
    const target = mediaTime(run, requestedRunTime(run, state.time, state.walkFocus));
    const atEnd = state.time >= (state.walkFocus && run.authority ? run.authority.walk_end_s : run.duration_s);
    const maximum = finite(video.duration) ? Math.max(0, video.duration - .001) : target;
    if (video.readyState > 0 && (force || Math.abs(video.currentTime - target) > .12)) video.currentTime = Math.min(target, maximum);
    video.playbackRate = state.rate;
    if (state.playing && visible && !atEnd && video.paused) {
      video.play().catch(error => {
        pause();
        showError(`Playback could not start: ${error.message}. Use Play after the media has loaded.`);
      });
    } else if ((!state.playing || !visible || atEnd) && !video.paused) video.pause();
  }
}
function resetWallClock() { state.startWall = performance.now(); state.startTime = state.time; }
function play() {
  if (state.time >= duration()) state.time = timeRange().start;
  state.playing = true;
  resetWallClock();
  $("play-icon").textContent = "Ⅱ";
  $("play-label").textContent = "Pause";
  $("play").setAttribute("aria-label", "Pause replay");
  synchronizeVideos(true);
  state.frame = requestAnimationFrame(tick);
}
function pause() {
  state.playing = false;
  cancelAnimationFrame(state.frame);
  $("play-icon").textContent = "▶";
  $("play-label").textContent = "Play";
  $("play").setAttribute("aria-label", "Play replay");
  synchronizeVideos(true);
  drawPlayhead();
}
function tick(wall) {
  if (!state.playing) return;
  state.time = Math.min(duration(), state.startTime + (wall - state.startWall) / 1000 * state.rate);
  if (wall - state.lastDraw >= 50) {
    synchronizeVideos();
    drawPlayhead();
    state.lastDraw = wall;
  }
  if (state.time >= duration()) pause(); else state.frame = requestAnimationFrame(tick);
}
function seek(time) {
  state.time = clamp(Number(time), timeRange().start, duration());
  resetWallClock();
  synchronizeVideos(true);
  drawPlayhead();
}

function drawPlayhead() {
  if (!state.runs.length) return;
  $("seek").value = state.time;
  $("clock").textContent = formatTime(displayTime(state.time));
  const focusedSample = recordedSample(currentRun());
  for (const run of state.runs) {
    if (run.runtime_kind !== "closed_loop_mission") continue;
    const card = document.querySelector(`.video-card[data-run-index="${state.runs.indexOf(run)}"]`);
    const status = card?.querySelector(".case-outcomes");
    if (!status) continue;
    const completed = (recordedSample(run)?.time_s ?? state.time) >= run.duration_s - 1e-8;
    status.replaceChildren(element("span", "case-outcomes-label", "Case"));
    if (completed) status.append(statusPill("Nominal", run.summary?.task_status), statusPill("Strict", run.summary?.strict_status), statusPill("Physical", run.summary?.physical_status));
    else status.append(element("span", "small muted", "Outcome at completion"));
  }
  if (focusedSample) $("clock").textContent = formatTime(displayTime(focusedSample.time_s));
  $("sample-time").textContent = focusedSample ? `${currentRun().visual_source === "state_playback" ? "acquisition" : "retained replay"} ${formatTime(focusedSample.time_s)} · frame ${focusedSample.frame_index}` : "No sample";
  $("metric-context").textContent = state.compare ? "Shared playhead · each arm shows its exact recorded frame" : currentRun().label;
  drawMetrics();
  drawNodeOutcomes();
  drawRuntimeDecisions();
  if (currentRun().runtime_kind === "closed_loop_mission") drawEvents();
  drawTrajectory();
  renderAuthority({runs: state.runs, run: currentRun(), time: focusedSample?.time_s ?? state.time, walkFocus: state.walkFocus, seek: value => {pause(); seek(value);}, inspect: openInspector});
  renderMechanismCharts({runs: state.runs, run: currentRun(), time: focusedSample?.time_s ?? state.time,
    presentedTimes: Object.fromEntries(state.runs.map(run => [run.id, recordedSample(run)?.time_s ?? state.time])),
    seek: value => {pause(); seek(value);}, inspect: openInspector});
  const source = currentRun().provenance ?? {};
  $("source-context").textContent = `${currentRun().case_id} · source ${String(source.source_commit ?? "unavailable").slice(0, 8)} · protocol ${String(source.protocol_sha ?? "unavailable").slice(0, 10)}`;
}
function drawMetrics() {
  const runs = visibleRuns();
  const samples = runs.map(recordedSample);
  const rows = [];
  if (state.compare) {
    const heading = element("div", "metric-row treatment-head");
    heading.append(element("span", "metric-name", "Research signal"));
    runs.forEach((run, index) => { const label = element("span", "metric-value", run.label); label.style.color = armColors[state.runs.indexOf(run) % armColors.length]; heading.append(label); });
    rows.push(heading);
  }
  for (const metric of metricDefinitions) {
    if (!currentRun().authority && ["reference_lateral_m", "global_endpoint_error_m", "residual_action"].includes(metric.key)) continue;
    const row = element("div", "metric-row");
    const name = element("span", "metric-name", metric.label);
    if (metric.description) name.title = metric.description;
    row.append(name);
    samples.forEach((sample, index) => {
      const value = element("span", "metric-value");
      const displayValue = sample?.[metric.key];
      if (["local_lateral_m", "reference_lateral_m", "global_endpoint_error_m", "global_lateral_m", "heading_error_deg"].includes(metric.key) && finite(displayValue) && !(state.walkFocus && metric.key === "heading_error_deg")) {
        const sourceMetric = state.walkFocus ? ({local_lateral_m: "first_walk_local_lateral_m", reference_lateral_m: "first_walk_reference_lateral_m", global_endpoint_error_m: "first_walk_global_endpoint_error_m"}[metric.key] ?? metric.key) : metric.key;
        const button = element("button", "", metric.format(displayValue));
        button.type = "button";
        button.title = `Inspect ${metric.label.toLowerCase()} and its underlying evidence`;
        button.addEventListener("click", () => openInspector(runs[index], {time_s: sample?.time_s, label: metric.label, metric: sourceMetric, value: displayValue, node_index: state.walkFocus ? 1 : sample?.node_index, frame_index: sample?.frame_index ?? sample?.sample_index, source_locator: sample?.source_locator ?? `runs/${runs[index].id}/poses.npz#frame=${sample?.frame_index ?? sample?.sample_index}`, derived_json_locator: `/raw/${runs[index].id}/derived-run#samples/${sample?.frame_index ?? sample?.sample_index}/${sourceMetric}`, derived: true}));
        value.append(button);
      } else value.textContent = metric.format(displayValue);
      row.append(value);
    });
    rows.push(row);
  }
  $("metrics").replaceChildren(...rows);
}
function drawNodeOutcomes() {
  const runs = visibleRuns();
  const group = element("div");
  const focused = recordedSample(currentRun());
  const currentNode = state.walkFocus ? currentRun().nodes[1] : nodeAt(currentRun(), state.time, focused);
  const indexLabel = currentNode ? `${currentNode.index + 1} / ${currentRun().nodes.length}` : "Unavailable";
  group.append(element("div", "node-name", state.compare ? "Each arm at its captured frame" : `${skillLabel(currentNode?.skill)} · ${indexLabel}`));
  const row = element("div", "node-outcome");
  runs.forEach(run => {
    const sample = recordedSample(run);
    const node = state.walkFocus ? run.nodes[1] : nodeAt(run, state.time, sample);
    const arm = element("div", "outcome-arm");
    if (state.compare) arm.append(element("div", "outcome-arm-label", `${run.label} · ${skillLabel(node?.skill)} ${node ? `${node.index + 1}/${run.nodes.length}` : ""}`));
    const revealed = visibleNodeOutcome(run, node, sample?.time_s ?? state.time);
    if (revealed) arm.append(statusPill("Nominal", node?.task_status), document.createTextNode(" "), statusPill("Strict", node?.strict_status), document.createTextNode(" "), statusPill("Physical", node?.physical_status));
    else arm.append(element("span", "small muted", "Outcome pending at this replay time"));
    if (revealed && (finite(node?.nominal_lateral_limit_m) || finite(node?.strict_lateral_limit_m))) {
      arm.append(element("div", "small muted", `Frozen lateral limits · nominal ${formatNumber(node.nominal_lateral_limit_m, 2, " m")} / strict ${formatNumber(node.strict_lateral_limit_m, 2, " m")}`));
    }
    if (revealed && node?.strict_violations?.length) arm.append(element("div", "strict-reason", `Strict source reason: ${node.strict_violations.map(violation => typeof violation === "string" ? violation : JSON.stringify(violation)).join("; ")}`));
    if (state.walkFocus && run.authority) arm.append(element("div", "small muted", `Formal Walk end ${formatNumber(run.authority.walk_end_s - run.authority.walk_start_s, 3, "s")} · captured ${formatNumber(sample?.time_s - run.authority.walk_start_s, 3, "s")} (${skillLabel(sample?.skill)})`));
    row.append(arm);
  });
  group.append(row);
  $("node-outcomes").replaceChildren(group);
}

function decisionText(value) {
  return typeof value === "string" ? value : value == null ? "Unavailable" : JSON.stringify(value);
}
function evaluationSummary(value) {
  if (typeof value !== "object" || value === null) return decisionText(value);
  const limits = value.limits ?? {};
  const parts = [value.satisfied === true ? "Strict PASS" : value.satisfied === false ? "Strict FAIL" : "Evaluation"];
  if (finite(value.lateral_drift_m) && finite(limits.lateral_drift_max_m)) parts.push(`drift ${formatNumber(value.lateral_drift_m, 3)} / ${formatNumber(limits.lateral_drift_max_m, 3)} m`);
  if (finite(value.heading_error_deg) && finite(limits.heading_error_max_deg)) parts.push(`heading ${formatNumber(value.heading_error_deg, 2)} / ${formatNumber(limits.heading_error_max_deg, 2)}°`);
  if (value.violations?.length) parts.push(value.violations.join(", "));
  return parts.join(" · ");
}
function drawRuntimeDecisions() {
  const panel = $("runtime-panel");
  const runs = visibleRuns().filter(run => run.runtime_kind === "closed_loop_mission");
  panel.hidden = !runs.length;
  if (!runs.length) return;
  const rows = [];
  for (const run of runs) {
    const time = recordedSample(run)?.time_s ?? state.time;
    for (const item of runtimeDecisionsAt(run, time)) {
      const row = element("button", "runtime-decision");
      row.type = "button";
      row.append(element("strong", "", `${run.label} · ${formatTime(item.time_s)} · node ${Number(item.node_index) + 1}`),
        element("span", "", `${evaluationSummary(item.evaluation)} · Decide: ${decisionText(item.decision)}`),
        element("span", "small muted", `Act: ${decisionText(item.action)} · Continue/Stop: ${decisionText(item.continuation)}`));
      row.addEventListener("click", () => openInspector(run, {...item, label: `Runtime decision · ${decisionText(item.decision)}`, metric: "runtime_decision", source_locator: item.source_locator}));
      rows.push(row);
    }
  }
  $("runtime-decisions").replaceChildren(...(rows.length ? rows : [element("p", "small muted", "No recorded decision yet at this replay time.")]));
}

function routePath(points, transform) {
  return points.filter(point => finite(point[0]) && finite(point[1])).map((point, index) => `${index ? "L" : "M"}${transform.point(...point).map(value => value.toFixed(2)).join(",")}`).join(" ");
}
function drawTrajectory() {
  const width = Math.max(340, $("trajectory").clientWidth - 28), height = Math.max(200, $("trajectory").clientHeight);
  const routeSamples = run => state.walkFocus && run.authority ? run.samples.filter(s => s.time_s >= run.authority.walk_start_s - 1e-8 && s.time_s <= run.authority.walk_end_s + .025) : run.samples;
  const bounds = trajectoryBounds(state.runs.map(run => ({samples: routeSamples(run), ideal_route: state.walkFocus ? [run.authority.measurement_origin_xy, run.authority.first_walk_ideal_endpoint_reference_xy] : run.ideal_route}))); // Shared world scale; never recenter a treatment.
  const transform = plotTransform(bounds, width, height, 27);
  const svg = svgElement("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Actual and ideal G1 route in world coordinates"});
  for (let x = Math.ceil(bounds.minX / 2) * 2; x <= bounds.maxX; x += 2) {
    const start = transform.point(x, bounds.minY), end = transform.point(x, bounds.maxY);
    svg.append(svgElement("line", {x1: start[0], y1: start[1], x2: end[0], y2: end[1], class: "route-grid"}));
    const text = svgElement("text", {x: start[0], y: height - 7, "text-anchor": "middle", class: "route-label"}); text.textContent = `${x} m`; svg.append(text);
  }
  for (let y = Math.ceil(bounds.minY / 2) * 2; y <= bounds.maxY; y += 2) {
    const start = transform.point(bounds.minX, y), end = transform.point(bounds.maxX, y);
    svg.append(svgElement("line", {x1: start[0], y1: start[1], x2: end[0], y2: end[1], class: "route-grid"}));
    const text = svgElement("text", {x: 8, y: start[1] + 3, class: "route-label"}); text.textContent = `${y}`; svg.append(text);
  }
  const ideal = state.walkFocus ? [currentRun().ideal_route[0], currentRun().authority.first_walk_ideal_endpoint_reference_xy] : currentRun().ideal_route ?? [];
  svg.append(svgElement("path", {d: routePath(ideal, transform), class: "route-ideal"}));
  if (state.walkFocus) {
    const a = currentRun().authority, origin = a.reference_origin_xy;
    const length = Math.hypot(a.first_walk_ideal_endpoint_reference_xy[0] - origin[0], a.first_walk_ideal_endpoint_reference_xy[1] - origin[1]);
    const endpoint = heading => [origin[0] + length * Math.cos(heading), origin[1] + length * Math.sin(heading)];
    svg.append(svgElement("path", {d: routePath([origin, endpoint(a.reference_heading_rad)], transform), class: "fixed-reference-line"}));
    svg.append(svgElement("path", {d: routePath([origin, endpoint(a.measurement_heading_rad)], transform), class: "measurement-line"}));
    for (const side of [-1, 1]) {
      const offset = [side * a.strict_lateral_limit_m * -Math.sin(a.measurement_heading_rad), side * a.strict_lateral_limit_m * Math.cos(a.measurement_heading_rad)];
      const start = origin.map((value, i) => value + offset[i]), end = endpoint(a.measurement_heading_rad).map((value, i) => value + offset[i]);
      svg.append(svgElement("path", {d: routePath([start, end], transform), class: "strict-guide"}));
    }
  }
  for (const run of visibleRuns()) {
    const secondary = state.runs.indexOf(run) > 0;
    const displayed = routeSamples(run), points = displayed.map(sample => [sample.x, sample.y]);
    const armColor = armColors[state.runs.indexOf(run) % armColors.length];
    const sample = recordedSample(run);
    if (run.runtime_kind !== "closed_loop_mission") svg.append(svgElement("path", {d: routePath(points, transform), class: `route-future${secondary ? " secondary" : ""}`}));
    if (sample) {
      const past = displayed.filter(point => point.time_s <= sample.time_s).map(point => [point.x, point.y]); past.push([sample.x, sample.y]);
      const actualPath = svgElement("path", {d: routePath(past, transform), class: "route-actual"}); actualPath.style.stroke = armColor; svg.append(actualPath);
      if (state.walkFocus) svg.append(svgElement("path", {d: routePath(displayed.filter(point => point.time_s <= run.authority.window_end_s).map(point => [point.x, point.y]), transform), class: "early-path", stroke: armColor}));
      if (finite(sample.x) && finite(sample.y)) {
        const position = transform.point(sample.x, sample.y);
        for (const [headingKey, className, length] of [["reference_heading_deg", "reference-arrow", .65], ["actual_heading_deg", `actual-arrow${secondary ? " secondary" : ""}`, .45]]) {
          if (!finite(sample[headingKey])) continue;
          const radians = sample[headingKey] * Math.PI / 180;
          const end = transform.point(sample.x + Math.cos(radians) * length, sample.y + Math.sin(radians) * length);
          svg.append(svgElement("line", {x1: position[0], y1: position[1], x2: end[0], y2: end[1], class: className}));
        }
        svg.append(svgElement("circle", {cx: position[0], cy: position[1], r: 4, class: `route-robot${secondary ? " secondary" : ""}`}));
      }
    }
    for (const event of run.events ?? []) {
      if (event.time_s < timeRange().start || event.time_s > timeRange().end) continue;
      if (run.runtime_kind === "closed_loop_mission" && event.time_s > (recordedSample(run)?.time_s ?? state.time) + 1e-8) continue;
      const at = sampleAt(run.samples, event.time_s);
      if (!at || !finite(at.x) || !finite(at.y)) continue;
      const position = transform.point(at.x, at.y);
      const point = svgElement("circle", {cx: position[0], cy: position[1], r: 4.5, class: `event-point${event.failure ? " failure" : ""}`, tabindex: "0", role: "button", "aria-label": `${run.label}: ${event.label} at ${formatTime(event.time_s)}`});
      const title = svgElement("title"); title.textContent = `${run.label} · ${event.label}`; point.append(title);
      const inspect = () => { seek(event.time_s); openInspector(run, event); };
      point.addEventListener("click", action => { action.stopPropagation(); inspect(); });
      point.addEventListener("keydown", action => { if (["Enter", " "].includes(action.key)) { action.preventDefault(); inspect(); } });
      svg.append(point);
    }
  }
  const axisLabel = svgElement("text", {x: width - 12, y: height - 7, "text-anchor": "end", class: "route-label"}); axisLabel.textContent = "world X / Y"; svg.append(axisLabel);
  svg.addEventListener("click", action => {
    const rect = svg.getBoundingClientRect();
    const [x, y] = transform.world((action.clientX - rect.left) * width / rect.width, (action.clientY - rect.top) * height / rect.height);
    const sample = nearestSample(routeSamples(currentRun()), x, y);
    if (!sample) return;
    pause(); seek(sample.time_s);
    openInspector(currentRun(), {time_s: sample.time_s, label: "Route sample", metric: "trajectory", node_index: sample.node_index, frame_index: sample.frame_index, source_locator: sample.source_locator ?? `runs/${currentRun().id}/poses.npz#frame=${sample.frame_index}`, derived_json_locator: `/raw/${currentRun().id}/derived-run#samples/${sample.frame_index}`, derived: true});
  });
  $("trajectory").replaceChildren(svg);
}
function drawEvents() {
  $("evidence-events").replaceChildren(); $("timeline-events").replaceChildren();
  for (const run of visibleRuns()) {
    for (const event of run.events ?? []) {
      if (event.time_s < timeRange().start || event.time_s > timeRange().end) continue;
      if (run.runtime_kind === "closed_loop_mission" && event.time_s > (recordedSample(run)?.time_s ?? state.time) + 1e-8) continue;
      const button = element("button", `event-button${event.failure ? " failure" : ""}`);
      button.type = "button";
      button.append(element("span", "", `${state.compare ? `${run.label} · ` : ""}${event.label}`), element("span", "event-time", formatTime(event.time_s)));
      button.addEventListener("click", () => { pause(); seek(event.time_s); openInspector(run, event); });
      $("evidence-events").append(button);
      const marker = element("button", `timeline-marker${event.failure ? " failure" : ""}`);
      marker.type = "button"; marker.style.left = `${clamp((event.time_s - timeRange().start) / (duration() - timeRange().start) * 100, 0, 100)}%`;
      marker.title = `${run.label} · ${event.label} · ${formatTime(event.time_s)}`;
      marker.setAttribute("aria-label", marker.title);
      marker.addEventListener("click", () => { pause(); seek(event.time_s); openInspector(run, event); });
      $("timeline-events").append(marker);
    }
  }
}

function provenanceRow(label, value, hash = false) {
  const row = element("div", "provenance-row");
  row.append(element("div", "provenance-label", label), element("div", `provenance-value${hash ? " hash" : ""}`, value ?? "Unavailable"));
  return row;
}
async function openInspector(run, event = null) {
  const runIndex = state.runs.indexOf(run);
  if (runIndex !== state.active) setActive(runIndex);
  pause();
  state.lastFocus = document.activeElement;
  $("inspector").classList.add("open"); $("inspector").inert = false;
  $("inspector").setAttribute("aria-hidden", "false");
  document.body.classList.add("inspector-open");
  $("inspector-content").replaceChildren(element("p", "inspector-loading", "Reading evidence provenance…"));
  $("close-inspector").focus({preventScroll: true});
  try {
    let evidence = state.evidence.get(run.id);
    if (!evidence) { evidence = await getJSON(run.evidence_url); state.evidence.set(run.id, evidence); }
    const provenance = {...(run.provenance ?? {}), ...(evidence.provenance ?? {})};
    const content = [];
    if (event) {
      const selected = element("div", `inspector-callout${event.failure ? " failure" : ""}`);
      selected.append(element("strong", "", event.label), element("div", "", `${run.label} · simulation ${formatTime(event.time_s)}`));
      const frame = frameForSimulationTime(run.frame_map, run.frame_fps, event.time_s);
      if (frame && finite(event.time_s)) selected.append(element("div", "small mono", `Selected visual frame ${formatTime(frame.time_s)} · Δ ${(frame.time_s - event.time_s).toFixed(3)} s from evidence`));
      if (event.metric) selected.append(element("div", "mono", `${event.metric}: ${finite(event.value) ? event.value.toFixed(6) : (event.value ?? "See source")}`));
      selected.append(element("div", "small", event.source_comparison ? "Source-bound paired arithmetic from the original window trace/audit or formal endpoints; not the nearest video frame." : event.derived ? "Derived instantaneous reading. Frozen source node outcomes remain the scoring authority." : "Source-bound evidence marker. Follow the raw locator to inspect the frozen metric."));
      content.push(selected);
      const decision = run.runtime_kind === "closed_loop_mission" ? run.runtime_decisions?.find(item => item.node_index === event.node_index && Math.abs(item.time_s - event.time_s) < 1e-8) : null;
      if (decision) {
        const detail = element("details", "inspector-section");
        detail.append(element("summary", "small", "Full recorded decision and evaluation"), element("pre", "json-summary", JSON.stringify(decision, null, 2)));
        content.push(detail);
      }
    }
    content.push(element("span", "integrity-tag", evidence.integrity_status ?? "Source hashes bound to artifact"));
    const identity = element("section", "inspector-section");
    identity.append(element("h3", "", "Research identity"), provenanceRow("Experiment", run.experiment_id), provenanceRow("Treatment", run.treatment ?? run.label), provenanceRow("Profile", run.profile ? `${run.profile} · deterministic bounded probe; not trained` : run.label), provenanceRow("Case", run.case_id), provenanceRow("Seed", run.seed ?? provenance.seed ?? "Not applicable · residual off"), provenanceRow("Visual source", run.visual_source), provenanceRow("Protocol SHA-256", provenance.protocol_sha, true), provenanceRow("Scientific source commit", provenance.source_commit, true), provenanceRow("Base policy identity", provenance.policy_identity), provenanceRow("Base policy SHA-256", provenance.policy_sha, true), provenanceRow("Learned checkpoint SHA-256", provenance.checkpoint_sha ?? (run.authority ? "Not applicable · deterministic probe" : "Not applicable · residual off"), true), provenanceRow("Reproducible visual producer commit", provenance.producer_commit ?? "Current Console code · exact code hashes retained", true), provenanceRow("Producer execution base commit", provenance.producer_execution_base_commit, true), provenanceRow("Producer code SHA-256", provenance.captured_code_sha ?? provenance.capture_code_sha ?? provenance.producer_code_sha, true), provenanceRow("Validation code SHA-256", provenance.comparison_validation_code_sha ?? provenance.validation_code_sha ?? provenance.capture_validation_code_sha, true));
    content.push(identity);
    const locator = element("section", "inspector-section");
    locator.append(element("h3", "", "Metric → raw evidence"), provenanceRow("Selected metric", event?.metric ?? "Frozen case outcome"), provenanceRow("Selected source locator", event?.source_locator ?? provenance.source_result_locator, true), provenanceRow("Frozen result locator", provenance.source_result_locator, true), provenanceRow("Frozen trace locator", provenance.source_trace_locator, true));
    if (event?.derived_json_locator) locator.append(provenanceRow("Derived sample JSON locator", event.derived_json_locator, true));
    const node = run.nodes?.find(item => item.index === event?.node_index);
    if (node) {
      locator.append(provenanceRow("Node", `${node.index + 1} · ${node.skill}`));
      if (visibleNodeOutcome(run, node, event?.time_s ?? state.time)) {
        locator.append(provenanceRow("Nominal / strict / physical", `${node.task_status ?? "Unavailable"} / ${node.strict_status ?? "Unavailable"} / ${node.physical_status ?? "Unavailable"}`));
        if (finite(node.nominal_lateral_limit_m)) locator.append(provenanceRow("Frozen nominal / strict lateral limits", `${formatNumber(node.nominal_lateral_limit_m, 3, " m")} / ${formatNumber(node.strict_lateral_limit_m, 3, " m")}`));
        if (node.strict_violations?.length) locator.append(provenanceRow("Frozen strict failure reason", node.strict_violations.map(violation => typeof violation === "string" ? violation : JSON.stringify(violation)).join("; ")));
      }
    }
    content.push(locator);
    const raw = element("section", "inspector-section"); raw.append(element("h3", "", "Inspect source files"));
    if (event?.derived_json_locator) {
      const derivedLink = element("a", "raw-link", "Selected derived metrics JSON ↗"); derivedLink.href = event.derived_json_locator; derivedLink.target = "_blank"; derivedLink.rel = "noopener noreferrer"; derivedLink.append(element("small", "", event.derived_json_locator)); raw.append(derivedLink);
    }
    if (event?.derived && finite(event.frame_index)) {
      const poseLocator = `/raw/${run.id}/poses#frame=${event.frame_index}`;
      const poseLink = element("a", "raw-link", "Selected captured pose archive ↗"); poseLink.href = poseLocator; poseLink.target = "_blank"; poseLink.rel = "noopener noreferrer"; poseLink.append(element("small", "", `${event.source_locator} · zero-based frame`)); raw.append(poseLink);
    }
    for (const link of evidence.raw_links ?? []) {
      const anchor = element("a", "raw-link", `${link.label} ↗`);
      anchor.href = link.url; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
      if (link.locator) anchor.append(element("small", "", link.locator));
      raw.append(anchor);
    }
    const apiLink = element("a", "raw-link", "Full provenance JSON ↗"); apiLink.href = run.evidence_url; apiLink.target = "_blank"; apiLink.rel = "noopener noreferrer"; raw.append(apiLink); content.push(raw);
    if (evidence.source_result && (run.runtime_kind !== "closed_loop_mission" || state.time >= run.duration_s - 1e-8)) {
      const details = element("details", "inspector-section");
      details.append(element("summary", "small", "Frozen source result"), element("pre", "json-summary", JSON.stringify(evidence.source_result, null, 2)));
      content.push(details);
    }
    const note = element("section", "inspector-section");
    note.append(element("h3", "", "How to read this visual"), element("p", "source-explanation", run.visual_source === "state_playback" ? "This video is render-only playback of original acquisition state samples. No controller or physics step is run. The fixed Walk measurement frame remains separate from its correction reference. Exact formal endpoint scores are not replaced by the nearest captured video frame, which can be just before or after the node boundary. Original results remain scoring authority." : "This is a derived visualization replay, not an original acquisition recording. Retained states are rendered without physics steps; original machine results remain scoring authority."));
    if (provenance.historical_pose_identity_claim) note.append(element("p", "source-explanation", provenance.historical_pose_identity_claim));
    content.push(note);
    $("inspector-content").replaceChildren(...content);
    announce(`Evidence Inspector opened for ${run.label}${event ? `, ${event.label}` : ""}.`);
  } catch (error) {
    $("inspector-content").replaceChildren(element("p", "inspector-callout failure", `Evidence could not be read: ${error.message}`));
  }
  drawTrajectory();
}
function closeInspector() {
  $("inspector").classList.remove("open"); $("inspector").inert = true;
  $("inspector").setAttribute("aria-hidden", "true"); document.body.classList.remove("inspector-open");
  if (state.lastFocus?.isConnected) state.lastFocus.focus({preventScroll: true});
  drawTrajectory();
}

async function loadExperiment(experiment) {
    if (state.runs.length) { pause(); closeInspector(); }
    state.runs = await Promise.all(experiment.arms.map(arm => getJSON(arm.run_url)));
    state.active = state.runs[0]?.authority ? 1 : 0;
    state.walkFocus = Boolean(state.runs[0]?.authority); state.compare = state.walkFocus;
    state.evidence.clear(); $("treatment").replaceChildren();
    $("experiment").value = experiment.id;
    $("experiment-title").textContent = experiment.title ?? experiment.case_id;
    $("experiment-subtitle").textContent = experiment.description ?? experiment.case_id;
    for (const [index, run] of state.runs.entries()) {
      if (!run.samples?.length || !finite(run.duration_s)) throw new Error(`Incomplete replay data: ${run.id}`);
      if (!["derived_visualization_replay", "state_playback", "acquisition_capture"].includes(run.visual_source)) throw new Error(`Unknown visual source: ${run.id}`);
      const option = element("option", "", run.label); option.value = index; $("treatment").append(option);
    }
    $("treatment").value = state.active;
    state.time = timeRange().start;
    const runtime = state.runs.some(run => run.runtime_kind === "closed_loop_mission");
    $("phase-label").textContent = runtime ? "M2 · CLOSED-LOOP MISSION" : "PHASE 3A · MECHANISM REPLAY";
    document.querySelector(".outcome-header h3").textContent = runtime ? "Recorded node outcomes" : "Frozen node outcomes";
    document.querySelector(".outcome-note").textContent = runtime ? "Node outcomes appear after their recorded completion. Decisions are read from the execution ledger; this replay never controls the robot." : "Instantaneous readings explain motion. Nominal and strict outcomes come from the original evidence and are never rescored by this interface.";
    $("visual-type").textContent = runtime ? "Recorded mission execution" : state.walkFocus ? "Acquisition-state playback" : "Derived visualization replay";
    $("visual-note").textContent = runtime ? "Robot video and trajectory are shown only when bound to captured execution states. Decisions and outcomes follow recorded simulation time." : state.walkFocus ? "Original acquired poses · zero new physics steps · Walk 0s is the original node start. Formal endpoints and nearest visual frames remain distinct." : "Historical acquisition unchanged · separately verified retained replay states.";
    buildVideos(); updateLayout();
}

async function init() {
  try {
    const catalog = await getJSON("/api/catalog");
    state.catalog = catalog;
    const experiment = catalog.experiments?.[0];
    if (!experiment?.arms?.length) throw new Error("No verified replay artifacts have been indexed.");
    for (const item of catalog.experiments) { const option = element("option", "", item.title); option.value = item.id; $("experiment").append(option); }
    await loadExperiment(experiment);
    $("play").disabled = false; $("seek").disabled = false; $("inspect-run").disabled = false;
    $("workspace").setAttribute("aria-busy", "false");
    const resize = new ResizeObserver(() => { if (state.runs.length) drawTrajectory(); }); resize.observe($("trajectory"));
  } catch (error) {
    showError(`Verified replay unavailable: ${error.message}`);
    $("experiment-subtitle").textContent = "The console requires source-bound native MuJoCo replay artifacts.";
    $("workspace").setAttribute("aria-busy", "false");
  }
}

$("play").addEventListener("click", () => state.playing ? pause() : play());
$("seek").addEventListener("input", event => seek(event.target.value));
$("treatment").addEventListener("change", event => setActive(Number(event.target.value)));
$("experiment").addEventListener("change", async event => {
  try { await loadExperiment(state.catalog.experiments.find(item => item.id === event.target.value)); }
  catch (error) { showError(error.message); }
});
$("walk-focus").addEventListener("click", () => {
  pause(); state.walkFocus = !state.walkFocus; state.time = timeRange().start; updateLayout();
});
$("single-view").addEventListener("click", () => setCompare(false));
$("compare-view").addEventListener("click", () => setCompare(true));
$("playback-rate").addEventListener("change", event => { state.rate = Number(event.target.value); resetWallClock(); synchronizeVideos(true); });
$("inspect-run").addEventListener("click", () => openInspector(currentRun()));
$("close-inspector").addEventListener("click", closeInspector);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeInspector();
  if (event.code === "Space" && ["BODY", "MAIN"].includes(document.activeElement.tagName)) { event.preventDefault(); state.playing ? pause() : play(); }
});
init();
