import {finite, clamp, formatNumber, formatTime, sampleAt, mediaFrame, frameForSimulationTime, nodeAt, statusKind, trajectoryBounds, plotTransform, nearestSample} from "./data.js";

const $ = id => document.getElementById(id);
const state = {runs: [], active: 0, compare: false, time: 0, playing: false, rate: 1, startWall: 0, startTime: 0, frame: 0, lastDraw: 0, evidence: new Map(), lastFocus: null};
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
function duration() { return Math.max(0, ...visibleRuns().map(run => run.duration_s)); }
function videoFor(run) { return document.querySelector(`video[data-run-index="${state.runs.indexOf(run)}"]`); }
function mediaTime(run, time) {
  return frameForSimulationTime(run.frame_map, run.frame_fps, time)?.media_time_s ?? Math.max(0, time - (run.video_time_offset_s ?? 0));
}
function recordedSample(run) {
  const video = videoFor(run);
  const presentedTime = video?._presentedMediaTime;
  const mediaClock = finite(presentedTime) ? presentedTime : video?.currentTime;
  const frame = video?.readyState > 0 ? mediaFrame(run.frame_map, run.frame_fps, mediaClock) : frameForSimulationTime(run.frame_map, run.frame_fps, state.time);
  if (frame && run.samples.length === run.frame_map.length) return {...run.samples[frame.index], sample_index: frame.index};
  return sampleAt(run.samples, frame?.time_s ?? Math.min(state.time, run.duration_s));
}

function buildVideos() {
  $("video-grid").replaceChildren();
  for (const [index, run] of state.runs.entries()) {
    const card = element("article", "video-card");
    card.dataset.runIndex = index;
    const header = element("div", "video-card-header");
    const label = element("div", "video-label");
    label.append(element("span", `arm-dot${index ? " secondary" : ""}`), element("span", "", run.label));
    const identity = element("div", "video-identity");
    const caseOutcomes = element("div", "case-outcomes");
    caseOutcomes.append(element("span", "case-outcomes-label", "Case"), statusPill("Nominal", run.summary?.task_status), statusPill("Strict", run.summary?.strict_status), statusPill("Physical", run.summary?.physical_status));
    identity.append(label, caseOutcomes);
    const meta = element("div", "video-meta", "Residual off · derived replay");
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
  $("seek").max = duration();
  $("duration").textContent = formatTime(duration());
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
    const target = mediaTime(run, Math.min(state.time, run.duration_s));
    const atEnd = state.time >= run.duration_s;
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
  if (state.time >= duration()) state.time = 0;
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
  state.time = clamp(Number(time), 0, duration());
  resetWallClock();
  synchronizeVideos(true);
  drawPlayhead();
}

function drawPlayhead() {
  if (!state.runs.length) return;
  $("seek").value = state.time;
  $("clock").textContent = formatTime(state.time);
  const focusedSample = recordedSample(currentRun());
  if (focusedSample) $("clock").textContent = formatTime(focusedSample.time_s);
  $("sample-time").textContent = focusedSample ? `source sample ${formatTime(focusedSample.time_s)}` : "No sample";
  $("metric-context").textContent = state.compare ? "Shared playhead · each arm shows its exact recorded frame" : currentRun().label;
  drawMetrics();
  drawNodeOutcomes();
  drawTrajectory();
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
    runs.forEach((run, index) => heading.append(element("span", `metric-value${index ? " secondary" : ""}`, run.label)));
    rows.push(heading);
  }
  for (const metric of metricDefinitions) {
    const row = element("div", "metric-row");
    const name = element("span", "metric-name", metric.label);
    if (metric.description) name.title = metric.description;
    row.append(name);
    samples.forEach((sample, index) => {
      const value = element("span", "metric-value");
      const displayValue = sample?.[metric.key];
      if (["local_lateral_m", "global_lateral_m", "heading_error_deg"].includes(metric.key) && finite(displayValue)) {
        const button = element("button", "", metric.format(displayValue));
        button.type = "button";
        button.title = `Inspect ${metric.label.toLowerCase()} and its underlying evidence`;
        button.addEventListener("click", () => openInspector(runs[index], {time_s: sample?.time_s, label: metric.label, metric: metric.key, value: displayValue, node_index: sample?.node_index, frame_index: sample?.frame_index ?? sample?.sample_index, source_locator: sample?.source_locator ?? `runs/${runs[index].id}/poses.npz#frame=${sample?.frame_index ?? sample?.sample_index}`, derived_json_locator: `/raw/${runs[index].id}/derived-run#samples/${sample?.frame_index ?? sample?.sample_index}`, derived: true}));
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
  const currentNode = nodeAt(currentRun(), state.time, focused);
  const indexLabel = currentNode ? `${currentNode.index + 1} / ${currentRun().nodes.length}` : "Unavailable";
  group.append(element("div", "node-name", state.compare ? "Each arm at its captured frame" : `${skillLabel(currentNode?.skill)} · ${indexLabel}`));
  const row = element("div", "node-outcome");
  runs.forEach(run => {
    const sample = recordedSample(run);
    const node = nodeAt(run, state.time, sample);
    const arm = element("div", "outcome-arm");
    if (state.compare) arm.append(element("div", "outcome-arm-label", `${run.label} · ${skillLabel(node?.skill)} ${node ? `${node.index + 1}/${run.nodes.length}` : ""}`));
    arm.append(statusPill("Nominal", node?.task_status), document.createTextNode(" "), statusPill("Strict", node?.strict_status), document.createTextNode(" "), statusPill("Physical", node?.physical_status));
    if (finite(node?.nominal_lateral_limit_m) || finite(node?.strict_lateral_limit_m)) {
      arm.append(element("div", "small muted", `Frozen lateral limits · nominal ${formatNumber(node.nominal_lateral_limit_m, 2, " m")} / strict ${formatNumber(node.strict_lateral_limit_m, 2, " m")}`));
    }
    if (node?.strict_violations?.length) arm.append(element("div", "strict-reason", `Strict source reason: ${node.strict_violations.map(violation => typeof violation === "string" ? violation : JSON.stringify(violation)).join("; ")}`));
    row.append(arm);
  });
  group.append(row);
  $("node-outcomes").replaceChildren(group);
}

function routePath(points, transform) {
  return points.filter(point => finite(point[0]) && finite(point[1])).map((point, index) => `${index ? "L" : "M"}${transform.point(...point).map(value => value.toFixed(2)).join(",")}`).join(" ");
}
function drawTrajectory() {
  const width = Math.max(340, $("trajectory").clientWidth - 28), height = Math.max(200, $("trajectory").clientHeight);
  const bounds = trajectoryBounds(state.runs); // Frame never shifts when switching treatments.
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
  const ideal = currentRun().ideal_route ?? [];
  svg.append(svgElement("path", {d: routePath(ideal, transform), class: "route-ideal"}));
  for (const run of visibleRuns()) {
    const secondary = state.runs.indexOf(run) > 0;
    const points = run.samples.map(sample => [sample.x, sample.y]);
    const sample = recordedSample(run);
    svg.append(svgElement("path", {d: routePath(points, transform), class: `route-future${secondary ? " secondary" : ""}`}));
    if (sample) {
      const past = points.slice(0, sample.sample_index + 1); past.push([sample.x, sample.y]);
      svg.append(svgElement("path", {d: routePath(past, transform), class: `route-actual${secondary ? " secondary" : ""}`}));
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
    const sample = nearestSample(currentRun().samples, x, y);
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
      const button = element("button", `event-button${event.failure ? " failure" : ""}`);
      button.type = "button";
      button.append(element("span", "", `${state.compare ? `${run.label} · ` : ""}${event.label}`), element("span", "event-time", formatTime(event.time_s)));
      button.addEventListener("click", () => { pause(); seek(event.time_s); openInspector(run, event); });
      $("evidence-events").append(button);
      const marker = element("button", `timeline-marker${event.failure ? " failure" : ""}`);
      marker.type = "button"; marker.style.left = `${clamp(event.time_s / duration() * 100, 0, 100)}%`;
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
      selected.append(element("div", "small", event.derived ? "Derived instantaneous reading. Frozen source node outcomes remain the scoring authority." : "Source-bound evidence marker. Follow the raw locator to inspect the frozen metric."));
      content.push(selected);
    }
    content.push(element("span", "integrity-tag", evidence.integrity_status ?? "Source hashes bound to artifact"));
    const identity = element("section", "inspector-section");
    identity.append(element("h3", "", "Research identity"), provenanceRow("Experiment", run.experiment_id), provenanceRow("Treatment", run.treatment ?? run.label), provenanceRow("Case", run.case_id), provenanceRow("Seed", run.seed ?? provenance.seed ?? "Not applicable · residual off"), provenanceRow("Visual source", run.visual_source), provenanceRow("Protocol SHA-256", provenance.protocol_sha, true), provenanceRow("Scientific source commit", provenance.source_commit, true), provenanceRow("Base policy identity", provenance.policy_identity), provenanceRow("Base policy SHA-256", provenance.policy_sha, true), provenanceRow("Learned checkpoint SHA-256", provenance.checkpoint_sha ?? "Not applicable · residual off", true), provenanceRow("Reproducible visual producer commit", provenance.producer_commit ?? "Not yet committed · capture code hashes retained", true), provenanceRow("Producer execution base commit", provenance.producer_execution_base_commit, true), provenanceRow("Captured producer code SHA-256", provenance.captured_code_sha ?? provenance.capture_code_sha ?? provenance.producer_code_sha, true), provenanceRow("Validation code SHA-256", provenance.comparison_validation_code_sha ?? provenance.validation_code_sha ?? provenance.capture_validation_code_sha, true));
    content.push(identity);
    const locator = element("section", "inspector-section");
    locator.append(element("h3", "", "Metric → raw evidence"), provenanceRow("Selected metric", event?.metric ?? "Frozen case outcome"), provenanceRow("Selected source locator", event?.source_locator ?? provenance.source_result_locator, true), provenanceRow("Frozen result locator", provenance.source_result_locator, true), provenanceRow("Frozen trace locator", provenance.source_trace_locator, true));
    if (event?.derived_json_locator) locator.append(provenanceRow("Derived sample JSON locator", event.derived_json_locator, true));
    const node = run.nodes?.find(item => item.index === event?.node_index);
    if (node) {
      locator.append(provenanceRow("Node", `${node.index + 1} · ${node.skill}`), provenanceRow("Nominal / strict / physical", `${node.task_status ?? "Unavailable"} / ${node.strict_status ?? "Unavailable"} / ${node.physical_status ?? "Unavailable"}`));
      if (finite(node.nominal_lateral_limit_m)) locator.append(provenanceRow("Frozen nominal / strict lateral limits", `${formatNumber(node.nominal_lateral_limit_m, 3, " m")} / ${formatNumber(node.strict_lateral_limit_m, 3, " m")}`));
      if (node.strict_violations?.length) locator.append(provenanceRow("Frozen strict failure reason", node.strict_violations.map(violation => typeof violation === "string" ? violation : JSON.stringify(violation)).join("; ")));
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
    if (evidence.source_result) {
      const details = element("details", "inspector-section");
      details.append(element("summary", "small", "Frozen source result"), element("pre", "json-summary", JSON.stringify(evidence.source_result, null, 2)));
      content.push(details);
    }
    const note = element("section", "inspector-section");
    note.append(element("h3", "", "How to read this visual"), element("p", "source-explanation", "This is a derived visualization replay, not an original acquisition recording. A separate native MuJoCo execution supplies retained states; the renderer plays those states without taking simulation steps. Each encoded frame maps to an exact captured simulation time, including the final pose. Original machine results and raw locators remain the scientific authority. Playback controls never change a protocol, threshold, or result."));
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

async function init() {
  try {
    const catalog = await getJSON("/api/catalog");
    const experiment = catalog.experiments?.[0];
    if (!experiment?.arms?.length) throw new Error("No verified replay artifacts have been indexed.");
    state.runs = await Promise.all(experiment.arms.map(arm => getJSON(arm.run_url)));
    for (const run of state.runs) {
      if (!run.samples?.length || !finite(run.duration_s)) throw new Error(`Incomplete replay data: ${run.id}`);
      if (run.visual_source !== "derived_visualization_replay" && run.visual_source !== "state_playback" && run.visual_source !== "acquisition_capture") throw new Error(`Unknown visual source: ${run.id}`);
    }
    $("experiment-title").textContent = experiment.title ?? experiment.case_id;
    $("experiment-subtitle").textContent = experiment.description ?? `${experiment.case_id} · same frozen mission · source-bound visual replay`;
    for (const [index, run] of state.runs.entries()) {
      const option = element("option", "", run.label); option.value = index; $("treatment").append(option);
    }
    buildVideos(); updateLayout();
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
