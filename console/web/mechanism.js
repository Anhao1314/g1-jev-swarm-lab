import {finite, formatNumber, sampleAt} from "./data.js";

export const armColors = ["#526f9b", "#b77a42", "#4e927b"];
const ns = "http://www.w3.org/2000/svg";
const html = (tag, cls, text) => {
  const item = document.createElement(tag); if (cls) item.className = cls;
  if (text !== undefined) item.textContent = text; return item;
};
const svg = (tag, attrs = {}) => {
  const item = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, value)); return item;
};
const color = (run, runs) => armColors[runs.indexOf(run) % armColors.length];
const metricEvent = (run, key, label, time) => ({label, metric: key, value: run.authority[key], time_s: time,
  node_index: 1, derived: true, source_comparison: true, source_locator: JSON.stringify(run.authority[`${key.replace(/_m$/, "")}_locator`] ?? run.authority.source_locators),
  derived_json_locator: `/raw/${run.id}/derived-run#authority/${key}`});

export function renderAuthority({runs, run, time, walkFocus, seek, inspect}) {
  const a = run.authority, panel = document.getElementById("mechanism-panel");
  panel.hidden = !a; document.getElementById("mechanism-charts").hidden = !a;
  if (!a) return;
  document.getElementById("walk-focus").textContent = walkFocus ? "Show full 16m sequence" : "Focus first Walk";
  const fingerprint = runs.map(arm => arm.id).join("|") + run.id + walkFocus;
  const changed = panel.dataset.identity !== fingerprint;
  const strip = document.getElementById("authority-timeline");
  if (changed) strip.replaceChildren();
  const steps = [
    ["0s · Walk starts", a.walk_start_s],
    ["Residual active", a.walk_start_s + a.window_duration_s / 2],
    [`${formatNumber(a.window_duration_s, 0)}s · authority ends`, a.window_end_s],
    ["Residual = 0 · fixed reference correction", a.window_end_s + (a.walk_end_s - a.window_end_s) / 2],
    ["Walk completion", a.walk_end_s],
  ];
  for (const [label, at] of changed ? steps : []) {
    const button = html("button", "phase-step", label); button.type = "button";
    button.addEventListener("click", () => seek(at)); strip.append(button);
  }
  const elapsed = time - a.walk_start_s;
  document.getElementById("authority-phase").textContent = elapsed < 0 ? "Before first Walk · residual off" :
    time >= a.walk_end_s ? `First Walk complete · source strict FAIL retained · later mission nodes keep their original references` :
    elapsed < a.window_duration_s - 1e-8 ? `Walk ${formatNumber(elapsed, 2)}s · authority window active; residual-off remains the paired control` :
    `Walk ${formatNumber(elapsed, 2)}s · authority ended · residual = 0 · fixed reference correction continues`;
  if (!changed) return;
  panel.dataset.identity = fingerprint;
  const cards = [];
  for (const arm of runs) {
    const section = html("article", "authority-card"); section.style.setProperty("--arm-color", color(arm, runs));
    section.append(html("h3", "", arm.label));
    section.append(html("p", "endpoint-comparison", `Source endpoint ${formatNumber(arm.authority.local_lateral_at_walk_end_m * 1000, 3)} mm / strict limit ${formatNumber(arm.authority.strict_lateral_limit_m * 1000, 3)} mm`));
    for (const [key, label, eventTime] of [
      ["local_effect_at_window_end_m", `${formatNumber(arm.authority.window_duration_s, 0)}s Δ local vs residual-off`, arm.authority.window_end_s],
      ["local_effect_at_walk_end_m", "Remaining at Walk endpoint", arm.authority.walk_end_s],
      ["strict_gap_m", "Beyond strict endpoint corridor", arm.authority.walk_end_s],
    ]) {
      const row = html("div", "authority-number");
      const button = html("button", "", formatNumber(arm.authority[key] * 1000, 3, " mm")); button.type = "button";
      button.addEventListener("click", () => { seek(eventTime); inspect(arm, metricEvent(arm, key, label, eventTime)); });
      row.append(html("span", "", label), button); section.append(row);
    }
    section.append(html("p", "small muted", "Formal source endpoint · strict FAIL retained")); cards.push(section);
  }
  document.getElementById("authority-evidence").replaceChildren(...cards);
}

export function renderMechanismCharts({runs, run, time, presentedTimes, seek, inspect}) {
  const container = document.getElementById("mechanism-charts");
  if (!run.authority) { container.hidden = true; return; }
  container.hidden = false;
  const definitions = [
    ["first_walk_local_lateral_m", "Local drift", "Fixed actual Walk-start measurement frame", true],
    ["first_walk_reference_lateral_m", "Reference-frame lateral", "Distance from the fixed correction reference line", false],
    ["first_walk_global_endpoint_error_m", "Global endpoint error", "World distance to the original Walk8m commanded endpoint", false],
    ["delta_local", "Residual effect vs off", "Paired local difference at the same Walk time; source endpoints shown separately", false],
  ];
  const baseline = runs.find(arm => arm.probe_id === "off") ?? runs[0];
  const width = 660, height = 190, left = 50, right = 15, top = 15, bottom = 30;
  const end = Math.max(...runs.map(arm => arm.authority.walk_end_s - arm.authority.walk_start_s));
  const sections = definitions.map(([key, title, subtitle, strict]) => {
    const panel = html("article", "panel signal-panel");
    const header = html("div", "panel-header"); header.append(html("h3", "", title), html("span", "small muted", "m")); panel.append(header);
    panel.append(html("p", "signal-subtitle", subtitle));
    if (strict) panel.append(html("p", "signal-subtitle", `Dashed: frozen endpoint limit ±${formatNumber(run.authority.strict_lateral_limit_m, 3)} m · no continuous rescore`));
    const series = runs.map(arm => ({run: arm, points: arm.samples.filter(s => s.time_s >= arm.authority.walk_start_s - 1e-8 && s.time_s <= arm.authority.walk_end_s + .025).map(s => {
      const paired = sampleAt(baseline.samples, s.time_s - arm.authority.walk_start_s + baseline.authority.walk_start_s);
      return {sample: s, x: s.time_s - arm.authority.walk_start_s,
        y: key === "delta_local" ? s.first_walk_local_lateral_m - paired.first_walk_local_lateral_m : s[key]};
    }).filter(p => finite(p.y))}));
    const values = series.flatMap(s => s.points.map(p => p.y));
    if (strict) values.push(-run.authority.strict_lateral_limit_m, run.authority.strict_lateral_limit_m);
    let low = Math.min(0, ...values), high = Math.max(0, ...values);
    const margin = Math.max((high - low) * .1, .001); low -= margin; high += margin;
    const x = value => left + value / end * (width - left - right);
    const y = value => height - bottom - (value - low) / (high - low) * (height - top - bottom);
    const plot = svg("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${title} over Walk time`});
    plot.append(svg("rect", {x: x(0), y: top, width: x(run.authority.window_duration_s) - x(0), height: height - top - bottom, class: "active-window"}));
    for (let index = 0; index <= 3; index++) {
      const value = low + (high - low) * index / 3;
      plot.append(svg("line", {x1: left, x2: width - right, y1: y(value), y2: y(value), class: "signal-grid"}));
      const label = svg("text", {x: left - 7, y: y(value) + 3, "text-anchor": "end", class: "signal-label"}); label.textContent = value.toFixed(3); plot.append(label);
    }
    if (strict) for (const value of [-run.authority.strict_lateral_limit_m, run.authority.strict_lateral_limit_m]) {
      plot.append(svg("line", {x1: left, x2: width - right, y1: y(value), y2: y(value), class: "strict-guide"}));
    }
    for (const at of [0, run.authority.window_duration_s, end]) {
      const label = svg("text", {x: x(at), y: height - 7, "text-anchor": at === end ? "end" : "middle", class: "signal-label"}); label.textContent = `${at.toFixed(at === end ? 2 : 0)}s`; plot.append(label);
    }
    plot.append(svg("line", {x1: x(run.authority.window_duration_s), x2: x(run.authority.window_duration_s), y1: top, y2: height - bottom, class: "authority-cutoff"}));
    for (const line of series) {
      plot.append(svg("path", {d: line.points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(2)},${y(p.y).toFixed(2)}`).join(" "), fill: "none", stroke: color(line.run, runs), "stroke-width": 1.8}));
      const current = sampleAt(line.run.samples, Math.min(presentedTimes?.[line.run.id] ?? time, line.run.authority.walk_end_s + .025));
      const paired = sampleAt(baseline.samples, current?.time_s);
      const value = key === "delta_local" ? current?.first_walk_local_lateral_m - paired?.first_walk_local_lateral_m : current?.[key];
      if (finite(value)) plot.append(svg("circle", {cx: x(current.time_s - line.run.authority.walk_start_s), cy: y(value), r: 3, fill: color(line.run, runs)}));
    }
    const cursor = Math.max(0, Math.min(end, time - run.authority.walk_start_s));
    plot.append(svg("line", {x1: x(cursor), x2: x(cursor), y1: top, y2: height - bottom, class: "signal-cursor"}));
    plot.addEventListener("click", event => {
      const rect = plot.getBoundingClientRect();
      const elapsed = Math.max(0, Math.min(end, ((event.clientX - rect.left) * width / rect.width - left) / (width - left - right) * end));
      const sample = sampleAt(run.samples, elapsed + run.authority.walk_start_s);
      seek(sample.time_s);
      inspect(run, {label: title, metric: key, value: sample[key], time_s: sample.time_s, node_index: 1,
        frame_index: sample.frame_index, source_locator: sample.source_locator, derived: true,
        derived_json_locator: `/raw/${run.id}/derived-run#samples/${sample.frame_index}`});
    });
    panel.append(plot); return panel;
  });
  container.replaceChildren(...sections);
}
