"use strict";

const $ = (id) => document.getElementById(id);
const palette = ["#62d8d0", "#8cb5ff", "#edbd70", "#f18a97"];
const pages = {
  overview: ["Training overview", "Authoritative state, training signals and recovery evidence."],
  workers: ["Workers & shards", "Membership leases, durable progress and accepted gradient staleness."],
  recovery: ["Recovery & checkpoints", "Observed lifecycle history and verified recovery scenarios."],
  traces: ["Distributed traces", "Follow an actual training step across process boundaries."],
  benchmarks: ["Correctness evidence", "Captured runs with their original workload and source context."],
};
const eventNames = {
  training_started: "Training started", worker_joined: "Worker joined", worker_lost: "Worker unavailable",
  worker_recovered: "Worker recovered", checkpoint_completed: "Checkpoint published",
  shard_restored: "Shard restored", training_completed: "Training completed",
};
let lastState = null;
let evidence = [];
let live = true;
let fetching = false;

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
function text(id, value) {
  const target = $(id);
  if (target.textContent !== String(value)) target.textContent = String(value);
}
function number(value) {
  if (value === null || value === undefined || value === "") return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}
function format(value, digits = 2) {
  const result = number(value);
  return result === null ? "—" : result.toLocaleString(undefined, { maximumFractionDigits: digits });
}
function badge(value) {
  const known = ["healthy", "completed", "suspect", "registered", "waiting", "unavailable", "degraded"];
  return node("span", value, `badge ${known.includes(value) ? value : ""}`);
}
function empty(target, message) { target.replaceChildren(node("p", message, "empty")); }
function cells(target, values) {
  const row = node("tr");
  for (const value of values) {
    const cell = node("td");
    cell.append(value instanceof Node ? value : node("span", value));
    row.append(cell);
  }
  target.append(row);
}
function noRows(target, count, message) {
  const row = node("tr"), cell = node("td", message, "muted");
  cell.colSpan = count;
  row.append(cell);
  target.replaceChildren(row);
}
function metricValues(name, state = lastState) {
  return (state?.metrics?.[name] || []).map((series) => number(series.value?.[1])).filter((v) => v !== null);
}
function metricSum(name) {
  const values = metricValues(name);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}
function seriesFrom(items) {
  return (items || []).map((series) => ({
    label: [series.metric?.component, series.metric?.worker_id].filter(Boolean).join(" / ") || "Observed",
    points: (series.values || []).map(([x, y]) => [Number(x), number(y)]),
  }));
}
function svgElement(tag, attributes = {}, content) {
  const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) item.setAttribute(key, String(value));
  if (content !== undefined) item.textContent = String(content);
  return item;
}
function chart(id, series, label, timeAxis = true) {
  const target = $(id);
  const points = series.flatMap((item) => item.points).filter(([x, y]) => Number.isFinite(x) && y !== null);
  if (!points.length) { empty(target, "No samples in this window."); return; }
  const width = Math.max(250, target.clientWidth - 24), height = 215;
  const left = 48, right = width - 12, top = 14, bottom = height - 30;
  const xMin = Math.min(...points.map((p) => p[0])), xMax = Math.max(...points.map((p) => p[0]));
  const yMax = Math.max(...points.map((p) => p[1])) * 1.1 || 1;
  const x = (value) => left + (value - xMin) / (xMax - xMin || 1) * (right - left);
  const y = (value) => bottom - value / yMax * (bottom - top);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
  for (let index = 0; index <= 3; index++) {
    const value = yMax * index / 3;
    svg.append(svgElement("line", { x1: left, x2: right, y1: y(value), y2: y(value), class: "gridline" }));
    svg.append(svgElement("text", { x: left - 8, y: y(value) + 3, "text-anchor": "end" }, format(value, value < 1 ? 3 : 1)));
  }
  for (const [position, anchor] of [[xMin, "start"], [xMax, "end"]]) {
    const value = timeAxis ? new Date(position * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : `Step ${position + 1}`;
    svg.append(svgElement("text", { x: x(position), y: height - 7, "text-anchor": anchor }, value));
  }
  const legend = node("div", undefined, "chart-legend");
  series.forEach((item, index) => {
    let path = "", connected = false;
    for (const [px, py] of item.points) {
      if (!Number.isFinite(px) || py === null) { connected = false; continue; }
      path += `${connected ? "L" : "M"}${x(px).toFixed(2)},${y(py).toFixed(2)} `;
      connected = true;
    }
    svg.append(svgElement("path", { d: path, fill: "none", stroke: palette[index % palette.length], "stroke-width": 1.8 }));
    const entry = node("span");
    entry.append(node("i", undefined, `legend-swatch series-${index % 4}`), node("span", item.label));
    legend.append(entry);
  });
  target.replaceChildren(svg, legend);
}
function currentWorkers(state) {
  const observed = new Map((state.coordinator.status?.workers || []).map((item) => [item.worker_id, item]));
  return (state.run.worker_ids || []).map((id) => observed.get(id) || { worker_id: id, health: "waiting" });
}
function nodeCard(name, health, detail) {
  const article = node("article", undefined, "node-card");
  const heading = node("div", undefined, "node-head");
  heading.append(node("h3", name), badge(health));
  article.append(heading, node("p", detail));
  return article;
}
function renderTopology(state, workers) {
  const target = $("topology");
  const groups = [node("div", undefined, "node-group"), node("div", undefined, "node-group"), node("div", undefined, "node-group")];
  ["Control plane", "Independent workers", "Authoritative shards"].forEach((label, index) => groups[index].append(node("div", label, "group-label")));
  groups[0].append(nodeCard("coordinator", state.coordinator.available ? "healthy" : "unavailable", "Run identity · membership · heartbeat leases"));
  for (const worker of workers) groups[1].append(nodeCard(worker.worker_id, state.coordinator.available ? worker.health : "unavailable", worker.generation ? `Step ${worker.step || 0} · generation ${worker.generation}` : "Awaiting registration"));
  for (const shard of state.shards || []) groups[2].append(nodeCard(`shard-${shard.index}`, shard.available ? "healthy" : "unavailable", shard.available ? `Version ${shard.progress.version || 0} · ${(shard.progress.pending_workers || []).length} pending` : shard.endpoint));
  if (!(state.shards || []).length) groups[2].append(nodeCard("shards", "waiting", "Waiting for the first RPC sample"));
  const arrow = (label) => { const item = node("div", "⇄", "flow-arrow"); item.append(node("small", label)); return item; };
  target.replaceChildren(groups[0], arrow("leases"), groups[1], arrow("gRPC"), groups[2]);
}
function dataPair(target, label, value) {
  const row = node("div", undefined, "data-pair");
  row.append(node("dt", label), node("dd", value));
  target.append(row);
}
function renderMembership(state, workers) {
  const body = $("workers-body"); body.replaceChildren();
  for (const worker of workers) cells(body, [worker.worker_id, badge(state.coordinator.available ? worker.health : "unavailable"), worker.generation ? worker.step || 0 : "—", worker.generation ? worker.parameter_version || 0 : "—", worker.generation ? `G${worker.generation}` : "—", worker.health === "completed" ? "Finished" : worker.generation ? `${format(worker.heartbeat_age_seconds || 0, 1)} s` : "—"]);
  const shards = $("shards-body"); shards.replaceChildren();
  for (const shard of state.shards || []) cells(shards, [`shard-${shard.index}`, badge(shard.available ? "healthy" : "unavailable"), shard.available ? shard.progress.version || 0 : "—", shard.available ? Object.entries(shard.progress.next_steps || {}).map(([id, step]) => `${id}: ${step}`).join(" · ") : "—", shard.available ? (shard.progress.pending_workers || []).join(", ") || "None" : "—"]);
  if (!(state.shards || []).length) noRows(shards, 5, "Waiting for shard samples.");
  const mode = state.run.mode;
  text("mode-badge", ({ SYNCHRONOUS: "Synchronous · barrier", ASYNCHRONOUS: "Asynchronous", BOUNDED_STALENESS: `Bounded · lag ≤ ${state.run.max_staleness || 0}` })[mode] || "Mode unknown");
  text("staleness-bound", mode === "BOUNDED_STALENESS" ? `Configured bound ≤ ${state.run.max_staleness || 0}` : "Last accepted lag per worker / shard");
}
function eventsForRun(state) { return (state.events || []).filter((item) => !item.run_id || item.run_id === state.run.run_id); }
function eventTime(timestamp) { return new Date(timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function renderEvents(state) {
  const records = eventsForRun(state).slice().reverse();
  const recent = $("recent-events"); recent.replaceChildren();
  for (const record of records.slice(0, 4)) {
    const row = node("div", undefined, "event-item"), label = node("div");
    label.append(node("span", eventNames[record.event] || record.event), node("p", record.worker_id || record.checkpoint_id || record.service));
    row.append(label, node("span", eventTime(record.timestamp), "event-time")); recent.append(row);
  }
  if (!records.length) empty(recent, "No lifecycle events observed for this run yet.");
  const filter = $("event-filter").value;
  const chosen = records.filter((item) => filter === "all" || (filter === "checkpoints" ? item.event === "checkpoint_completed" : ["worker_lost", "worker_recovered", "shard_restored"].includes(item.event)));
  const body = $("events-body"); body.replaceChildren();
  for (const record of chosen) cells(body, [eventTime(record.timestamp), eventNames[record.event] || record.event, record.service, record.worker_id || record.run_id || "—", record.step !== undefined ? `Step ${record.step}` : record.version !== undefined ? `v${record.version}` : "—"]);
  if (!chosen.length) noRows(body, 5, "No matching events in retained history.");
  text("event-status", !state.event_sink?.enabled ? "Event streaming is disabled; any retained history is shown." : state.event_sink.connected ? "NATS connected · best-effort lifecycle delivery · up to 200 events retained." : "Event stream disconnected; stored history remains available.");
  const latest = records.find((record) => record.event === "checkpoint_completed"), checkpoint = $("checkpoint-detail");
  checkpoint.replaceChildren();
  if (latest) {
    checkpoint.append(node("strong", latest.checkpoint_id));
    const details = node("dl");
    for (const [label, value] of [["Completed-step watermark", latest.step], ["Shard versions", (latest.shard_versions || []).join(", ")], ["Export duration", `${format(latest.duration_seconds, 3)} s`], ["Observed at", eventTime(latest.timestamp)]]) dataPair(details, label, value);
    checkpoint.append(details);
  } else empty(checkpoint, "No checkpoint publication has been observed for this run.");
}
function renderCharts() {
  if (lastState) for (const [id, key, label] of [["loss-chart", "loss", "Worker pre-update mean squared error"], ["throughput-chart", "throughput", "Worker steps per second"], ["versions-chart", "versions", "Authoritative shard versions"], ["staleness-chart", "staleness", "Last accepted gradient staleness"]]) chart(id, seriesFrom(lastState.history?.[key]), label);
  const reports = evidence.filter((item) => item.mode && !item.failure);
  chart("benchmark-chart", reports.map((report) => ({ label: `${report.mode} / worker-0`, points: (report.worker_results?.find((item) => item.worker_id === "worker-0")?.losses || []).map((value, index) => [index, number(value)]) })), "Recorded worker pre-update MSE by local iteration", false);
}
function renderState(state) {
  lastState = state;
  const workers = currentWorkers(state), available = state.coordinator.available;
  const active = workers.filter((worker) => worker.health === "healthy").length;
  const complete = workers.length && workers.every((worker) => worker.health === "completed");
  const phase = !available ? "unavailable" : complete ? "completed" : workers.some((worker) => ["unavailable", "suspect"].includes(worker.health)) ? "degraded" : active ? "healthy" : "waiting";
  const phaseBadge = badge(phase); phaseBadge.id = "run-phase"; $("run-phase").replaceWith(phaseBadge);
  text("run-name", state.run.run_id || "Unknown run");
  text("global-step", available ? format(state.coordinator.status?.global_step || 0, 0) : "—");
  text("active-workers", available ? `${active} / ${workers.length}` : "—");
  text("worker-health-note", complete ? "All workers completed their target" : "Healthy heartbeat leases");
  text("steps-rate", format(metricSum("steps_per_second"), 1));
  text("examples-rate", `${format(metricSum("examples_per_second"), 0)} examples / s`);
  let losses = metricValues("loss");
  if (!losses.length) losses = seriesFrom(state.history?.loss).map((series) => series.points.filter((p) => p[1] !== null).at(-1)?.[1]).filter((value) => value !== undefined);
  text("mean-loss", losses.length ? format(losses.reduce((a, b) => a + b, 0) / losses.length, 4) : "—");
  renderTopology(state, workers); renderMembership(state, workers); renderEvents(state);
  const pending = (state.shards || []).filter((item) => item.available).reduce((sum, item) => sum + (item.progress.pending_workers || []).length, 0);
  text("barrier-count", `${pending} pending shard contributions`);
  const transport = $("transport"); transport.replaceChildren();
  for (const [label, value] of [["Push latency · p95", `${format(metricValues("push_p95_seconds")[0] === undefined ? null : metricValues("push_p95_seconds")[0] * 1000, 2)} ms`], ["Pull latency · p95", `${format(metricValues("pull_p95_seconds")[0] === undefined ? null : metricValues("pull_p95_seconds")[0] * 1000, 2)} ms`], ["Client protobuf payload", `${format(metricSum("bytes_per_second") === null ? null : metricSum("bytes_per_second") / 1024, 1)} KiB / s`], ["Prometheus", state.backends.prometheus ? "Available" : "Unavailable"], ["Tempo / Loki", `${state.backends.tempo ? "Available" : "Unavailable"} / ${state.backends.loki ? "Available" : "Unavailable"}`], ["Known lost / unconfirmed events", format(metricSum("event_drops"), 0)]]) dataPair(transport, label, value);
  const errors = [];
  if (!available) errors.push("Coordinator state is unavailable.");
  if (!state.backends.prometheus) errors.push("Metrics are unavailable.");
  $("connection-error").hidden = !errors.length; text("connection-error", errors.join(" "));
  renderTraces(state); renderCharts(); updateAge();
}
function renderTraces(state) {
  const target = $("traces-list");
  if (target.contains(document.activeElement)) return;
  target.replaceChildren();
  const traces = (state.traces || []).filter((trace) => /^[a-f0-9]{32}$/.test(trace.traceID));
  for (const trace of traces) {
    const button = node("button", undefined, "trace-choice");
    button.append(node("code", trace.traceID.slice(0, 16)), node("span", `${trace.rootServiceName || "Worker"} · ${format(trace.durationMs, 2)} ms`));
    button.addEventListener("click", () => loadTrace(trace.traceID)); target.append(button);
  }
  if (!traces.length) empty(target, state.backends.tempo ? "No sampled training-step traces found yet." : "Trace backend is unavailable.");
}
async function api(path) {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store" });
  if (response.status === 401) { window.location.assign("/login"); throw new Error("Sign in required"); }
  if (!response.ok) throw new Error("Backend unavailable");
  return response.json();
}
async function loadTrace(id) {
  $("trace-panel").hidden = false; text("trace-id", id); empty($("trace-detail"), "Loading trace…");
  try {
    const result = await api(`/api/trace/${id}`), spans = [];
    for (const batch of result.batches || result.resourceSpans || []) {
      const service = (batch.resource?.attributes || []).find((attribute) => attribute.key === "service.name")?.value?.stringValue || "Unknown";
      for (const scope of batch.scopeSpans || batch.instrumentationLibrarySpans || []) for (const span of scope.spans || []) {
        spans.push({ ...span, service, start: BigInt(span.startTimeUnixNano), end: BigInt(span.endTimeUnixNano) });
      }
    }
    if (!spans.length) { empty($("trace-detail"), "This trace has no readable spans."); return; }
    spans.sort((a, b) => a.start < b.start ? -1 : a.start > b.start ? 1 : 0);
    const start = spans.reduce((min, span) => span.start < min ? span.start : min, spans[0].start);
    const end = spans.reduce((max, span) => span.end > max ? span.end : max, spans[0].end);
    const duration = Number(end - start) || 1, byId = new Map(spans.map((span) => [span.spanId, span]));
    const target = $("trace-detail"); target.replaceChildren(node("p", `${spans.length} spans · ${format(duration / 1e6, 2)} ms · sampled step`, "panel-note"));
    for (const span of spans) {
      let depth = 0, parent = span.parentSpanId; const seen = new Set([span.spanId]);
      while (byId.has(parent) && !seen.has(parent) && depth < 8) { seen.add(parent); parent = byId.get(parent).parentSpanId; depth++; }
      const row = node("div", undefined, "trace-row"), operation = node("span", span.name, `operation trace-depth-${depth}`);
      operation.title = span.name;
      const timeline = svgElement("svg", { viewBox: "0 0 500 18", role: "img", "aria-label": `${span.name}: ${format(Number(span.end - span.start) / 1e6, 3)} milliseconds` });
      timeline.append(svgElement("rect", { x: 0, y: 5, width: 500, height: 8, fill: "#202e3d" }), svgElement("rect", { x: Math.max(0, Number(span.start - start) / duration * 500), y: 5, width: Math.max(2, Number(span.end - span.start) / duration * 500), height: 8, fill: span.service.startsWith("shard") ? palette[2] : span.service === "coordinator" ? palette[1] : palette[0] }));
      row.append(node("span", span.service, "mono"), operation, node("span", `${format(Number(span.end - span.start) / 1e6, 3)} ms`), timeline); target.append(row);
    }
  } catch { empty($("trace-detail"), "Trace data is unavailable. Refresh and try another sampled step."); }
}
function renderEvidence() {
  const restore = evidence.find((report) => report.checkpoint_restored_workers), restored = $("restore-evidence");
  restored.replaceChildren();
  if (restore) {
    restored.append(node("p", `Checkpoint ${restore.checkpoint.checkpoint_id} · watermark ${restore.checkpoint.global_step} · ${restore.checkpoint.records.length} validated role records`));
    for (const worker of restore.checkpoint_restored_workers) restored.append(node("p", `${worker.worker_id}: resumed from ${worker.resumed_from}, finished ${worker.steps}; ${worker.losses.length} new loss samples`));
    restored.append(node("p", `Fresh-volume install and S3 round trip · source ${restore.source_commit.slice(0, 7)}${restore.source_dirty ? " (development tree)" : ""}. This recorded check is separate from the latest observed publication below.`, "panel-note"));
  } else empty(restored, "No recorded whole-run restore report is available.");
  const body = $("benchmark-body"); body.replaceChildren();
  for (const report of evidence.filter((item) => item.mode && !item.failure)) cells(body, [report.mode, format(report.initial_loss, 4), format(report.final_loss, 4), (report.shard_versions || []).join(", "), report.max_parameter_error === null ? "Different update semantics" : format(report.max_parameter_error, 9), node("code", (report.environment?.commit || "unknown").slice(0, 7))]);
  if (!body.children.length) noRows(body, 6, "No captured run reports are available.");
  const failures = evidence.filter((item) => item.failure), summary = $("recovery-evidence"), bars = $("failure-bars");
  summary.replaceChildren(); bars.replaceChildren();
  const maximum = Math.max(1, ...failures.map((report) => report.failure.recovery_seconds_until_progress));
  for (const report of failures) {
    const record = node("article", undefined, "failure-record"), fault = report.failure;
    record.append(node("h3", `${fault.terminated_component} · ${report.steps_per_worker} steps completed`), node("p", `Reference error ${report.max_parameter_error.toExponential(2)} · shard versions ${report.shard_versions.join(", ")}`), node("p", `Source ${(report.environment?.commit || "unknown").slice(0, 7)} · ${fault.step_delay_seconds}s deliberate step delay`)); summary.append(record);
    const article = node("article"); article.append(node("h3", fault.terminated_component));
    for (const [label, value, color] of [["Detection", fault.detection_seconds, palette[0]], ["Termination → later progress", fault.recovery_seconds_until_progress, palette[2]]]) {
      const heading = node("div", undefined, "bar-label"); heading.append(node("span", label), node("span", `${format(value, 3)} s`));
      const svg = svgElement("svg", { viewBox: "0 0 500 10", role: "img", "aria-label": `${label}: ${format(value, 3)} seconds` });
      svg.append(svgElement("rect", { width: 500, height: 10, fill: "#202e3d" }), svgElement("rect", { width: value / maximum * 500, height: 10, fill: color })); article.append(heading, svg);
    }
    article.append(node("p", "Single-run observations; process startup is included.", "panel-note")); bars.append(article);
  }
  if (!failures.length) { empty(summary, "No captured failure reports are available."); empty(bars, "No captured fault timings."); }
  renderCharts();
}
function navigate() {
  const page = location.hash.slice(1).split("?")[0];
  const current = pages[page] ? page : "overview";
  for (const target of document.querySelectorAll("[data-view]")) target.hidden = target.dataset.view !== current;
  for (const link of document.querySelectorAll("[data-nav]")) {
    if (link.dataset.nav === current) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  text("page-title", pages[current][0]); text("page-description", pages[current][1]);
  text("page-eyebrow", `CLUSTER / ${current === "benchmarks" ? "EVIDENCE" : current.toUpperCase()}`);
  renderCharts();
}
function updateAge() {
  const age = lastState?.sampled_at ? Math.max(0, Date.now() / 1000 - lastState.sampled_at) : null;
  text("sample-age", age === null ? "Not sampled" : `${age > 10 ? "Stale · " : ""}sampled ${format(age, 0)}s ago`);
}
async function refresh() {
  if (fetching) return;
  fetching = true; $("refresh").disabled = true;
  try { renderState(await api("/api/state")); }
  catch { $("connection-error").hidden = false; text("connection-error", "Unable to update. The last observation remains visible."); }
  finally { fetching = false; $("refresh").disabled = false; }
}
$("refresh").addEventListener("click", refresh);
$("live-toggle").addEventListener("click", () => { live = !live; $("live-toggle").setAttribute("aria-pressed", String(live)); text("live-toggle", live ? "Live updates" : "Updates paused"); if (live) refresh(); });
$("event-filter").addEventListener("change", () => { if (lastState) renderEvents(lastState); });
window.addEventListener("hashchange", navigate);
window.addEventListener("resize", () => requestAnimationFrame(renderCharts));
navigate(); refresh();
api("/api/benchmarks").then((reports) => { evidence = reports; renderEvidence(); }).catch(() => { empty($("recovery-evidence"), "Captured reports are unavailable."); });
setInterval(() => { if (live) refresh(); updateAge(); }, 2000);
