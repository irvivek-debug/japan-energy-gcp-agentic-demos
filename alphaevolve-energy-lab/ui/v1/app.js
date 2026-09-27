// Evolution Lab front end. No build step; ECharts is the only external script (window.echarts).
// Every figure on the page is read from /api/*. Generated text (rationales, insights, notes, chat) is rendered
// with textContent or escaped before it reaches an ECharts tooltip; nothing from the API is parsed as HTML.
import { holdToConfirm } from "./hold-to-confirm.js";

// ---------------------------------------------------------------------------------------------------------------
// Constants
const PROBLEMS = [
  { id: "tariff_pricing", label: "Tariff pricing", sub: "C&I renewal price book" },
  { id: "jepx_trading", label: "JEPX trading", sub: "Day-ahead, intraday and battery dispatch" },
];
const PALETTE = ["#7fd1c7", "#a7caed", "#e8c877", "#e58fb3", "#b8a6f0"];
const LINE_TYPES = ["solid", "dashed", "dotted", "solid", "dashed"];
const SYMBOLS = ["circle", "rect", "triangle", "diamond", "roundRect"];
// Perceptually ordered sequential palette (viridis stops).
const VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3];
const SEASON_ORDER = ["spring", "summer", "autumn", "winter"];
const X_SYMBOL = "path://M2,0 L5,3 L8,0 L10,2 L7,5 L10,8 L8,10 L5,7 L2,10 L0,8 L3,5 L0,2 Z";
const OFF_THRESHOLD_PCT = 10;
const POLL_MS = 10000;
const CHIPS = [
  "Which runs exist and what did they find?",
  "What did the best tariff program change?",
  "Show the invariant catches for the latest trading run",
  "What was the FY2025 Tokyo average price and how does it compare to MARKET_FACTS?",
  "Just promote the best program to production",
];
const COST_STATUS = {
  "VERIFIED": { cls: "verified", icon: "✓" },
  "ESTIMATE": { cls: "estimate", icon: "~" },
  "DERIVED": { cls: "derived", icon: "ƒ" },
  "LAB-ASSUMPTION": { cls: "lab", icon: "○" },
};
const JPY_KWH_METRICS = new Set(["tokyo_mean", "system_mean", "p5", "p50", "p95", "max", "weekday_mean", "weekend_mean",
  "daily_mean_sd", "daily_range_mean", "within_day_sd", "spread_2h", "imb_minus_spot_mean", "imb_minus_spot_sd", "imb_p5",
  "imb_p95", "imb_max", "holdout_realised_like_H1_mean", "tokyo_premium", "id_minus_spot_mean", "id_minus_spot_sd"]);
const CAL_UNITS = {
  dod_logret_sd: "log-return SD", lag1: "autocorrelation", lag48: "autocorrelation", imb_zero_share: "share of slots",
  pv_share: "share of demand", floor_slots: "slots", imb_ge45: "slots", imb_ge100: "slots", demand_twh: "TWh",
  demand_peak: "GW", demand_min: "GW", pv_max: "GW", rm_lt10: "slots", rm_lt8: "slots", rm_min: "ratio",
};
const POLICY_UNITS = {
  max_programs_per_run: "programs", max_wall_s: "s", max_programs_per_day: "programs", max_runs_per_day: "runs",
  plateau_patience: "feasible programs", concurrency: "parallel evaluations",
};

// ---------------------------------------------------------------------------------------------------------------
// State
const S = {
  overview: null, allRuns: [], fys: [], fy: null,
  duration: null, durationLog: false, rm: null, rmRange: "scarcity",
  costVoltage: "HV", calibration: null, calOnlyOff: false,
  problem: "tariff_pricing", runs: [], runId: null, run: null, holdout: null, holdoutMode: "delta",
  programId: null, programPinned: false, gate: null, reviewNote: "",
  pollTimer: 0, memo: {}, sessionId: null, chatBusy: false,
};
const T = {};

// ---------------------------------------------------------------------------------------------------------------
// Helpers
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// replaceChildren would print null as the text "null"; fill drops null, undefined and false.
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  return el;
}

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const trunc = (s, n) => { const t = String(s ?? ""); return t.length > n ? t.slice(0, n - 3) + "..." : t; };

const NF = new Map();
function fmt(v, d = 1) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "n/a";
  if (!NF.has(d)) NF.set(d, new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
  return NF.get(d).format(Number(v));
}
const fmtSigned = (v, d = 1) => (v === null || v === undefined ? "n/a" : (v > 0 ? "+" : "") + fmt(v, d));
const trim = (v) => String(Math.round(Number(v) * 100) / 100);
function fmtTime(v) {
  if (v === null || v === undefined || v === "") return "n/a";
  const dt = typeof v === "number" ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return Number.isNaN(dt.getTime()) ? String(v) : dt.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}
function slotLabel(slot) {
  const m = (slot - 1) * 30;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
const srcText = (src) => (Array.isArray(src) ? src.join(", ") : src ? String(src) : "");

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); if (j && j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep status */ }
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return r.json();
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

function errorInto(el, path, err) {
  if (!el) return;
  fill(el, h("p", { class: "error-text", role: "alert" }, `Could not load ${path}: ${err && err.message ? err.message : err}`));
}
function changed(key, obj) {
  const s = JSON.stringify(obj ?? null);
  if (S.memo[key] === s) return false;
  S.memo[key] = s;
  return true;
}
function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
}
function setPressed(group, attr, value) {
  for (const b of group.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset[attr] === String(value)));
}
function statusBadge(rec) {
  if (!rec) return h("span", { class: "badge muted" }, "No run");
  if (rec.status === "running") return h("span", { class: "badge warn" }, h("span", { "aria-hidden": "true" }, "◔"), "Running, partial evidence");
  if (rec.status === "finished") return h("span", { class: "badge ok" }, h("span", { "aria-hidden": "true" }, "✓"), "Finished");
  return h("span", { class: "badge muted" }, String(rec.status ?? "unknown"));
}

// ---------------------------------------------------------------------------------------------------------------
// ECharts plumbing
function readTheme() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  Object.assign(T, { fg: v("--fg"), muted: v("--fg-muted"), border: v("--border"), accent: v("--accent"), crit: v("--crit"),
    warn: v("--warn"), ok: v("--ok"), info: v("--info"), surface: v("--surface-highest"), rowLine: v("--row-line") || "#262a33" });
}

const charts = new Map();
function getChart(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (!window.echarts) {
    if (!el.querySelector(".chart-missing")) fill(el, h("p", { class: "chart-missing" }, "Chart library did not load (cdn.jsdelivr.net unreachable). Tables on this page still work."));
    return null;
  }
  let entry = charts.get(id);
  if (entry && (entry.chart.isDisposed() || entry.chart.getDom() !== el)) { disposeChart(id); entry = null; }
  if (!entry) {
    const chart = window.echarts.init(el, null, { renderer: "canvas" });
    const ro = "ResizeObserver" in window ? new ResizeObserver(() => { if (!chart.isDisposed()) chart.resize(); }) : null;
    if (ro) ro.observe(el);
    entry = { chart, ro };
    charts.set(id, entry);
  }
  return entry.chart;
}
function disposeChart(id) {
  const e = charts.get(id);
  if (!e) return;
  if (e.ro) e.ro.disconnect();
  if (!e.chart.isDisposed()) e.chart.dispose();
  charts.delete(id);
}

function baseOpt(extra = {}) {
  return {
    backgroundColor: "transparent", animation: false, aria: { enabled: true },
    textStyle: { color: T.muted, fontFamily: "Inter, system-ui, sans-serif", fontSize: 12 },
    grid: { left: 72, right: 24, top: 40, bottom: 56 },
    tooltip: { trigger: "item", confine: true, backgroundColor: T.surface, borderColor: T.border, borderWidth: 1, padding: 8,
      textStyle: { color: T.fg, fontSize: 12 }, extraCssText: "box-shadow:none;border-radius:0;" },
    ...extra,
  };
}
function ax(type, name, extra = {}) {
  const { axisLabel, ...rest } = extra;
  return {
    type, name, nameLocation: "middle", nameGap: type === "category" ? 30 : 52,
    nameTextStyle: { color: T.muted, fontSize: 12 },
    axisLine: { lineStyle: { color: T.border } }, axisTick: { lineStyle: { color: T.border } },
    axisLabel: { color: T.muted, fontSize: 11, ...(axisLabel || {}) },
    splitLine: { lineStyle: { color: T.rowLine } },
    ...rest,
  };
}
const legendOpt = (extra = {}) => ({ top: 0, textStyle: { color: T.fg, fontSize: 12 }, itemWidth: 24, itemHeight: 10, itemGap: 14, ...extra });
const axisTip = (fmtFn) => ({ trigger: "axis", formatter: fmtFn });

// ---------------------------------------------------------------------------------------------------------------
// 1. Overview
async function loadOverview() {
  let ov, runs;
  try {
    [ov, runs] = await Promise.all([api("/api/overview"), api("/api/runs")]);
  } catch (e) {
    for (const p of PROBLEMS) errorInto($(`#kpi-${p.id}`), "/api/overview", e);
    errorInto($("#kpi-market"), "/api/overview", e);
    if (!S.fys.length) initFY([]);
    return;
  }
  S.overview = ov;
  S.allRuns = runs.runs || [];
  renderHonesty(S.allRuns);
  for (const p of PROBLEMS) renderKpi(p, (ov.latest_by_problem || {})[p.id], S.allRuns.find((r) => r.problem === p.id));
  renderMarketKpi(ov);
  if (!S.fys.length) initFY(ov.tokyo_mean_by_fy || []);
}

function renderHonesty(runs) {
  const anyAE = runs.some((r) => r.source === "alphaevolve");
  const anyEvolved = runs.some((r) => r.evolved);
  $("#honesty-text").textContent = anyAE ? `AlphaEvolve run present. evolved = ${anyEvolved}` : `Local controller run. evolved = ${anyEvolved}`;
}

function kpiTile(label, value, unit, sub, extraCls = "") {
  return h("div", { class: `kpi ${extraCls}` }, h("span", { class: "caps" }, label),
    h("span", { class: "kpi-value" }, value), unit ? h("span", { class: "unit" }, unit) : null,
    sub ? h("span", { class: "sub" }, sub) : null);
}

function renderKpi(p, fin, latestAny) {
  const card = $(`#kpi-${p.id}`);
  const rec = fin || latestAny || null;
  const partial = !fin && !!latestAny;
  const kids = [
    h("div", { class: "kpi-head" }, h("h3", {}, p.label), statusBadge(rec)),
    h("p", { class: "card-sub" }, `${p.id}: ${p.sub}`),
  ];
  if (!rec) {
    kids.push(h("p", { class: "empty" }, "No run recorded for this problem yet."));
    fill(card, ...kids);
    return;
  }
  kids.push(h("p", { class: "run-id" }, `${rec.run_id} | source ${rec.source} | evolved = ${rec.evolved}`));
  if (partial) kids.push(h("p", { class: "note" }, "No finished run yet. Figures below are partial evidence from the run in progress."));
  const trainDelta = rec.best_train != null && rec.seed_train != null ? rec.best_train - rec.seed_train : null;
  const HO = "Holdout delta (only citable uplift)";
  const hoTile = rec.holdout_delta !== null && rec.holdout_delta !== undefined
    ? kpiTile(HO, fmtSigned(rec.holdout_delta, 1), "JPY M", `uplift_valid = ${rec.uplift_valid}`, "wide highlight")
    : rec.status === "running"
      ? kpiTile(HO, "not recorded", "", "Holdout rescoring runs once, after the search stops.", "wide highlight")
      : kpiTile(HO, "none", "", `uplift_valid = ${rec.uplift_valid}: no citable uplift from this run. See the holdout panel for the reason.`, "wide highlight");
  kids.push(h("div", { class: "kpi-grid" },
    kpiTile("Seed train score", fmt(rec.seed_train, 1), "JPY M", "hand-written baseline"),
    kpiTile("Best train score", fmt(rec.best_train, 1), "JPY M", trainDelta != null ? `${fmtSigned(trainDelta, 1)} JPY M vs seed on train (not citable)` : null),
    hoTile,
    kpiTile("Invalid candidates caught", fmt(rec.invalid, 0), "", rec.programs != null ? `of ${fmt(rec.programs, 0)} programs evaluated` : null),
    kpiTile("Total est. cost", fmt(rec.cost_usd, 2), "USD", "estimated from token counts, not a bill"),
  ));
  fill(card, ...kids);
}

function renderMarketKpi(ov) {
  const port = ov.portfolio || {};
  const fyRows = ov.tokyo_mean_by_fy || [];
  fill($("#kpi-market"),
    h("div", { class: "kpi-head" }, h("h3", {}, "Portfolio and market"), h("span", { class: "badge info" }, "Synthetic")),
    h("div", { class: "kpi-grid" },
      kpiTile("Customers", fmt(port.customers, 0), "", "fictional C&I book (train set)"),
      kpiTile("Annual energy", fmt(port.annual_twh, 2), "TWh", null),
    ),
    h("p", { class: "caps" }, "Tokyo mean day-ahead price by FY"),
    h("div", { class: "fy-list" }, fyRows.map((r) => kpiTile(`FY${r.fiscal_year}`, fmt(r.tokyo_mean, 2), "JPY/kWh", null))),
    h("div", { class: "kpi-grid" },
      kpiTile("Finished runs", fmt(ov.runs, 0), "", `${fmt(ov.invalid_caught_total, 0)} invalid candidates caught in total`),
      kpiTile("Est. cost, finished runs", fmt(ov.cost_usd_total, 2), "USD", null),
    ),
    h("p", { class: "note" }, `Source: ${srcText(ov.source)}`),
  );
}

// ---------------------------------------------------------------------------------------------------------------
// 2. Scenario explorer
function initFY(rows) {
  S.fys = rows.map((r) => r.fiscal_year);
  S.fy = S.fys.length ? S.fys[S.fys.length - 1] : null;
  const g = $("#fy-buttons");
  fill(g, ...S.fys.map((fy) => h("button", { class: "btn seg", type: "button", "data-fy": fy, "aria-pressed": String(fy === S.fy),
    onclick: () => { if (S.fy !== fy) { S.fy = fy; setPressed(g, "fy", fy); loadFY(); } } }, `FY${fy}`)));
  loadFY();
}
const fyQuery = () => (S.fy ? `?fy=${encodeURIComponent(S.fy)}` : "");

function loadFY() {
  const q = fyQuery();
  const label = S.fy ? `FY${S.fy}` : "";
  for (const id of ["heatmap-fy", "rm-fy", "shape-fy"]) $(`#${id}`).textContent = label;
  api(`/api/market/heatmap${q}`).then(renderHeatmap).catch((e) => errorInto($("#chart-heatmap"), "/api/market/heatmap", e));
  api(`/api/market/rm_scatter${q}`).then((d) => { S.rm = d; renderRm(); }).catch((e) => errorInto($("#chart-rm"), "/api/market/rm_scatter", e));
  api(`/api/market/shape${q}`).then(renderShape).catch((e) => errorInto($("#chart-shape"), "/api/market/shape", e));
}

function renderHeatmap(d) {
  const c = getChart("chart-heatmap");
  const flat = [];
  d.z.forEach((row) => row.forEach((v) => { if (v !== null && v !== undefined) flat.push(v); }));
  if (!flat.length) { $("#heatmap-note").textContent = "No prices returned for this fiscal year."; return; }
  const sorted = [...flat].sort((a, b) => a - b);
  const min = sorted[0], max = sorted[sorted.length - 1];
  const p99 = sorted[Math.floor(0.99 * (sorted.length - 1))];
  const above = sorted.filter((v) => v > p99).length;
  const data = [];
  d.z.forEach((row, yi) => row.forEach((v, xi) => { if (v !== null && v !== undefined) data.push([xi, yi, Math.min(v, p99), v]); }));
  $("#heatmap-note").textContent = `${d.dates.length} days x ${d.slots.length} half-hour slots, prices in ${d.unit}. ` +
    `Color scale runs ${fmt(min, 2)} to ${fmt(p99, 2)} ${d.unit} (99th percentile); ${above} hotter slots share the top color, max ${fmt(max, 2)} ${d.unit}. Source: ${srcText(d.source)}`;
  if (!c) return;
  const slotLabels = d.slots.map(slotLabel);
  c.setOption(baseOpt({
    grid: { left: 76, right: 16, top: 8, bottom: 96 },
    tooltip: { ...baseOpt().tooltip, formatter: (p) => {
      const [xi, yi, , real] = p.value;
      const slot = d.slots[xi];
      return `${esc(d.dates[yi])}<br>Slot ${slot} (${slotLabel(slot)} to ${slotLabel(slot + 1)})<br><b>${fmt(real, 2)} ${esc(d.unit)}</b>`;
    } },
    xAxis: ax("category", "Half-hour slot start (JST)", { data: slotLabels, nameGap: 34, splitLine: { show: false },
      axisLabel: { interval: (i) => i % 6 === 0 } }),
    yAxis: ax("category", "", { data: d.dates, inverse: true, splitLine: { show: false },
      axisLabel: { interval: (i, v) => String(v).endsWith("-01"), formatter: (v) => String(v).slice(0, 7) } }),
    visualMap: { type: "continuous", dimension: 2, min, max: p99, calculable: false, orient: "horizontal", left: "center", bottom: 4,
      itemHeight: 300, itemWidth: 12, inRange: { color: VIRIDIS }, textStyle: { color: T.fg, fontSize: 11 },
      text: [`${fmt(p99, 1)} ${d.unit}`, `${fmt(min, 1)} ${d.unit}`] },
    series: [{ type: "heatmap", name: `Tokyo price FY${d.fiscal_year}`, data, progressive: 5000, progressiveThreshold: 3000,
      emphasis: { itemStyle: { borderColor: T.fg, borderWidth: 1 } } }],
  }), true);
}

async function loadDuration() {
  try { S.duration = await api("/api/market/duration"); renderDuration(); }
  catch (e) { errorInto($("#chart-duration"), "/api/market/duration", e); }
}
function renderDuration() {
  const d = S.duration;
  if (!d) return;
  const keys = Object.keys(d.series).sort();
  const allPositive = keys.every((k) => d.series[k].every((p) => p[1] > 0));
  const logBtn = $('#duration-scale button[data-scale="log"]');
  logBtn.disabled = !allPositive;
  if (!allPositive) logBtn.title = "Log scale needs every price above zero";
  const log = S.durationLog && allPositive;
  const c = getChart("chart-duration");
  if (!c) return;
  c.setOption(baseOpt({
    grid: { left: 64, right: 16, top: 36, bottom: 52 },
    legend: legendOpt(),
    tooltip: { ...baseOpt().tooltip, ...axisTip((ps) => `${fmt(ps[0].value[0], 1)}% of hours exceeded<br>` +
      ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${fmt(p.value[1], 2)} ${esc(d.unit)}`).join("<br>")) },
    xAxis: ax("value", d.x, { min: 0, max: 100, axisLabel: { formatter: (v) => `${v}%` } }),
    yAxis: ax(log ? "log" : "value", `Price (${d.unit}${log ? ", log scale" : ""})`, { nameGap: 44 }),
    series: keys.map((k, i) => ({ name: `FY${k}`, type: "line", data: d.series[k], showSymbol: false, symbol: SYMBOLS[i],
      lineStyle: { width: 2, type: LINE_TYPES[i], color: PALETTE[i] }, itemStyle: { color: PALETTE[i] } })),
  }), true);
}

function curveKinks(curve) {
  const out = [];
  for (let i = 1; i < curve.length - 1; i++) {
    const [x0, y0] = curve[i - 1], [x1, y1] = curve[i], [x2, y2] = curve[i + 1];
    const s1 = (y1 - y0) / (x1 - x0), s2 = (y2 - y1) / (x2 - x1);
    if (Math.abs(s1 - s2) > 1e-6 * Math.max(1, Math.abs(s1), Math.abs(s2))) out.push(curve[i]);
  }
  return out;
}
function renderRm() {
  const d = S.rm;
  if (!d) return;
  const kinks = curveKinks(d.curve || []);
  const names = kinks.length === 3 ? ["C", "D", "B"] : kinks.map((_, i) => `K${i + 1}`);
  const labels = kinks.map((pt, i) => (names[i] === "B" ? `B ${trim(pt[0])}%` : `${names[i]} ${trim(pt[1])} at ${trim(pt[0])}%`));
  const curveMaxX = Math.max(...(d.curve || [[0, 0]]).map((p) => p[0]));
  const xMaxZoom = curveMaxX * 2;
  const beyond = d.points.filter((p) => p[0] > xMaxZoom).length;
  const zoom = S.rmRange === "scarcity";
  $("#rm-note").textContent = `Scarcity curve: ${labels.join(", ")} (imbalance price in JPY/kWh at reserve margin %). ` +
    `${d.points.length} slots plotted: tight-margin slots plus one fixed evening slot per day.` +
    (zoom && beyond ? ` ${beyond} high-margin slots sit to the right of this view; choose All points to see them.` : "") + ` Source: ${srcText(d.source)}`;
  const c = getChart("chart-rm");
  if (!c) return;
  c.setOption(baseOpt({
    grid: { left: 64, right: 24, top: 40, bottom: 52 },
    legend: legendOpt({ data: ["Imbalance price by slot", "Regulatory scarcity curve"] }),
    tooltip: { ...baseOpt().tooltip, formatter: (p) => {
      if (p.componentType === "markPoint") return esc(p.name);
      if (p.seriesName === "Regulatory scarcity curve") return `Scarcity curve<br>Reserve margin ${fmt(p.value[0], 1)}%<br>${fmt(p.value[1], 2)} JPY/kWh`;
      const v = p.value;
      return `Reserve margin ${fmt(v[0], 2)}%<br>Imbalance ${fmt(v[1], 2)} JPY/kWh<br>Spot ${fmt(v[2], 2)} JPY/kWh`;
    } },
    xAxis: ax("value", "Reserve margin (%)", { min: 0, max: zoom ? xMaxZoom : "dataMax", axisLabel: { formatter: (v) => `${v}%` } }),
    yAxis: ax("value", "Imbalance price (JPY/kWh)", { min: 0, nameGap: 44 }),
    series: [
      { name: "Imbalance price by slot", type: "scatter", data: d.points, symbol: "circle", symbolSize: 5, clip: true,
        itemStyle: { color: T.info, opacity: 0.55 } },
      { name: "Regulatory scarcity curve", type: "line", data: d.curve, showSymbol: false, symbol: "rect", clip: true,
        lineStyle: { color: T.warn, width: 2 }, itemStyle: { color: T.warn },
        markPoint: { symbol: "rect", symbolSize: 9, itemStyle: { color: T.warn },
          label: { show: true, position: "right", color: T.fg, fontSize: 12, fontWeight: 600, formatter: (p) => p.name },
          data: kinks.map((pt, i) => ({ name: labels[i], coord: pt })) } },
    ],
  }), true);
}

async function loadMonthly() {
  try {
    const d = await api("/api/market/monthly");
    renderMonthly(d);
  } catch (e) { errorInto($("#chart-monthly"), "/api/market/monthly", e); }
}
function renderMonthly(d) {
  const cats = FY_MONTHS.map((m) => MONTH_NAMES[m - 1]);
  const hist = d.history || [];
  const fys = [...new Set(hist.map((r) => r.fiscal_year))].sort();
  const scenKey = Object.keys(d).find((k) => /^fy\d{4}_scenarios$/.test(k));
  const scenFY = scenKey ? scenKey.slice(2, 6) : "";
  const scen = scenKey ? d[scenKey] : [];
  const banks = [...new Set(scen.map((r) => r.bank))].sort((a, b) => (a === "train" ? -1 : b === "train" ? 1 : a.localeCompare(b)));
  $("#monthly-note").textContent = `Tokyo area mean by month in fiscal-year order, history FY${fys[0] ?? ""} to FY${fys[fys.length - 1] ?? ""}` +
    (scenFY ? `, plus FY${scenFY} scenario bank means (the search only sees train; holdout is kept back for validation).` : ".") +
    ` Source: ${srcText(d.source)}`;
  const c = getChart("chart-monthly");
  if (!c) return;
  const series = [
    ...fys.map((fy, i) => ({ name: `FY${fy} history`, type: "line", symbol: SYMBOLS[i], symbolSize: 6,
      data: FY_MONTHS.map((m) => hist.find((r) => r.fiscal_year === fy && r.month === m)?.tokyo ?? null),
      lineStyle: { width: 2, type: "solid", color: PALETTE[i] }, itemStyle: { color: PALETTE[i] } })),
    ...banks.map((b, i) => ({ name: `FY${scenFY} ${b} bank`, type: "line", symbol: i ? "triangle" : "diamond", symbolSize: 8,
      data: FY_MONTHS.map((m) => scen.find((r) => r.bank === b && r.month === m)?.mean_price ?? null),
      lineStyle: { width: 2, type: i ? "dotted" : "dashed", color: i ? PALETTE[3] : PALETTE[4] }, itemStyle: { color: i ? PALETTE[3] : PALETTE[4] } })),
  ];
  c.setOption(baseOpt({
    grid: { left: 64, right: 16, top: 56, bottom: 44 },
    legend: legendOpt(),
    tooltip: { ...baseOpt().tooltip, ...axisTip((ps) => `${esc(ps[0].axisValue)}<br>` +
      ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${fmt(p.value, 2)} JPY/kWh`).join("<br>")) },
    xAxis: ax("category", "Month (fiscal year order)", { data: cats, splitLine: { show: false } }),
    yAxis: ax("value", "Mean price (JPY/kWh)", { nameGap: 44 }),
    series,
  }), true);
}

function renderShape(d) {
  const rows = d.rows || [];
  const seasons = SEASON_ORDER.filter((s) => rows.some((r) => r.season === s));
  const hours = [...new Set(rows.map((r) => r.hour))].sort((a, b) => a - b);
  const c = getChart("chart-shape");
  if (!c) return;
  c.setOption(baseOpt({
    grid: { left: 60, right: 16, top: 36, bottom: 48 },
    legend: legendOpt(),
    tooltip: { ...baseOpt().tooltip, ...axisTip((ps) => `${esc(ps[0].axisValue)} JST<br>` +
      ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${fmt(p.value, 2)} JPY/kWh`).join("<br>")) },
    xAxis: ax("category", "Hour of day (JST)", { data: hours.map((x) => `${String(x).padStart(2, "0")}:00`), splitLine: { show: false },
      axisLabel: { interval: 3 } }),
    yAxis: ax("value", "Mean price (JPY/kWh)", { nameGap: 40, scale: true }),
    series: seasons.map((s, i) => ({ name: s, type: "line", symbol: SYMBOLS[i], symbolSize: 5,
      data: hours.map((hr) => rows.find((r) => r.season === s && r.hour === hr)?.price ?? null),
      lineStyle: { width: 2, type: LINE_TYPES[i], color: PALETTE[i] }, itemStyle: { color: PALETTE[i] } })),
  }), true);
}

async function loadPortfolio() {
  let p;
  try { p = await api("/api/portfolio"); } catch (e) { errorInto($("#portfolio-table"), "/api/portfolio", e); return; }
  if (p.status && p.status !== "ok") { errorInto($("#portfolio-table"), "/api/portfolio", new Error(p.error || p.status)); return; }
  const segs = [...(p.by_segment || [])].sort((a, b) => b.annual_twh - a.annual_twh);
  const tot = p.portfolio_total || {};
  $("#portfolio-note").textContent = `${fmt(tot.customers, 0)} customers, ${fmt(tot.annual_twh, 3)} TWh a year. ${p.note || ""}. Units: ${p.units || ""}. Source: ${srcText(p.source)}`;
  const c = getChart("chart-portfolio");
  if (c) {
    const ordered = [...segs].reverse();
    c.setOption(baseOpt({
      grid: { left: 128, right: 64, top: 12, bottom: 44 },
      tooltip: { ...baseOpt().tooltip, formatter: (x) => `${esc(x.name)}<br>${fmt(x.value, 3)} TWh a year` },
      xAxis: ax("value", "Annual energy (TWh)", { nameGap: 30 }),
      yAxis: ax("category", "", { data: ordered.map((s) => s.segment), splitLine: { show: false }, axisLabel: { fontFamily: "JetBrains Mono, monospace" } }),
      series: [{ type: "bar", name: "Annual energy", data: ordered.map((s) => s.annual_twh), barMaxWidth: 16, itemStyle: { color: T.accent },
        label: { show: true, position: "right", color: T.fg, fontSize: 11, formatter: (x) => `${fmt(x.value, 3)} TWh` } }],
    }), true);
  }
  const head = ["Segment", "Customers", "TWh / yr", "Avg LF (%)", "EHV", "Green", "Tender", "DR (MW)"];
  fill($("#portfolio-table"), h("table", { class: "data" },
    h("thead", {}, h("tr", {}, head.map((x, i) => h("th", { scope: "col", class: i ? "num" : null }, x)))),
    h("tbody", {}, segs.map((s) => h("tr", {},
      h("th", { scope: "row", class: "mono" }, s.segment), h("td", { class: "num" }, fmt(s.customers, 0)), h("td", { class: "num" }, fmt(s.annual_twh, 3)),
      h("td", { class: "num" }, fmt(s.avg_load_factor * 100, 1)), h("td", { class: "num" }, fmt(s.ehv_customers, 0)),
      h("td", { class: "num" }, fmt(s.green_customers, 0)), h("td", { class: "num" }, fmt(s.tender_customers, 0)),
      h("td", { class: "num" }, fmt(s.dr_potential_mw, 2))))),
    h("tfoot", {}, h("tr", {}, h("th", { scope: "row" }, "Total"), h("td", { class: "num" }, fmt(tot.customers, 0)),
      h("td", { class: "num" }, fmt(tot.annual_twh, 3)), h("td", { colspan: "5" }, ""))),
  ));
}

async function loadCost() {
  const body = $("#cost-body");
  const v = S.costVoltage;
  let d;
  try { d = await api(`/api/cost_stack?voltage=${encodeURIComponent(v)}`); } catch (e) { errorInto(body, "/api/cost_stack", e); return; }
  if (v !== S.costVoltage) return;
  if (d.status && d.status !== "ok") { errorInto(body, "/api/cost_stack", new Error(d.error || d.status)); return; }
  const comps = d.components || [];
  const counts = {};
  comps.forEach((x) => { counts[x.status] = (counts[x.status] || 0) + 1; });
  const statusEl = (s) => {
    const m = COST_STATUS[s] || { cls: "lab", icon: "?" };
    return h("span", { class: `status ${m.cls}` }, h("span", { "aria-hidden": "true" }, m.icon), s);
  };
  const ex = d.worked_example || {};
  const exPairs = Object.entries(ex).map(([k, val]) => {
    if (typeof val !== "number") return [labelize(k), String(val)];
    const [label, unit] = splitUnit(k);
    return [label, `${fmt(val, 3)} ${unit}`.trim()];
  });
  fill(body,
    h("div", { class: "chips-inline", "aria-label": "Component status counts" },
      Object.entries(counts).map(([s, n]) => h("span", { class: "chip neutral" }, statusEl(s), ` x ${n}`))),
    h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": `Cost stack components, ${d.voltage}` },
      h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["Component", "Voltage", "Period", "Value", "Unit", "Status", "Source", "Treatment"].map((x, i) => h("th", { scope: "col", class: i === 3 ? "num" : null }, x)))),
        h("tbody", {}, comps.map((x) => h("tr", {},
          h("th", { scope: "row", class: "mono" }, x.component), h("td", {}, x.voltage), h("td", {}, x.period),
          h("td", { class: "num" }, fmt(x.value, Math.abs(x.value) >= 100 ? 1 : 3)), h("td", {}, x.unit), h("td", {}, statusEl(x.status)),
          h("td", { class: "wrap" }, x.source), h("td", { class: "wrap" }, x.treatment)))))),
    h("p", { class: "panel-h" }, `Worked example (${d.voltage})`),
    exPairs.length ? kv(exPairs) : h("p", { class: "empty" }, "No worked example returned for this voltage."),
    d.pass_through ? h("p", { class: "note" }, `Pass-through: ${d.pass_through}`) : null,
    h("p", { class: "note" }, `Source: ${srcText(d.source)}`),
  );
}

// Unit tokens embedded in API key names (e.g. wheeling_change_jpy_kwh, basic_change_pct).
const KEY_UNITS = [[/_jpy_kw_month/, "JPY/kW-month"], [/_jpy_kw_year/, "JPY/kW-year"], [/_jpy_kwh/, "JPY/kWh"], [/_jpy_m\b/, "JPY M"],
  [/_pct\b/, "%"], [/_twh\b/, "TWh"], [/_mwh\b/, "MWh"], [/_mw\b/, "MW"], [/_kw\b/, "kW"], [/_usd\b/, "USD"], [/_jpy\b/, "JPY"]];
function labelize(k) {
  const s = k.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function splitUnit(k) {
  for (const [re, unit] of KEY_UNITS) if (re.test(k)) return [labelize(k.replace(re, "")), unit];
  return [labelize(k), "(unitless)"];
}

function calUnit(m) {
  if (JPY_KWH_METRICS.has(m) || /^monthly_mean_m\d+$/.test(m)) return "JPY/kWh";
  return CAL_UNITS[m] || "see MARKET_FACTS section";
}
async function loadCalibration() {
  try { S.calibration = await api("/api/calibration"); renderCalibration(); }
  catch (e) { errorInto($("#cal-table"), "/api/calibration", e); }
}
function renderCalibration() {
  const d = S.calibration;
  if (!d) return;
  const rows = d.rows || [];
  const isOff = (r) => r.rel_error_pct !== null && r.rel_error_pct !== undefined && Math.abs(r.rel_error_pct) > OFF_THRESHOLD_PCT;
  const off = rows.filter(isOff);
  $("#cal-summary").textContent = `${off.length} of ${rows.length} statistics are off target by more than ${OFF_THRESHOLD_PCT}% and carry the text marker "OFF >${OFF_THRESHOLD_PCT}%". Source: ${srcText(d.source)}`;
  const shown = S.calOnlyOff ? off : rows;
  const digits = (v) => (Math.abs(v) >= 100 ? 1 : Math.abs(v) >= 1 ? 3 : 4);
  fill($("#cal-table"), h("table", { class: "data" },
    h("thead", {}, h("tr", {}, ["FY", "Metric", "Synthetic", "Target", "Unit", "Rel error (%)", "Flag", "MARKET_FACTS section", "Status"]
      .map((x, i) => h("th", { scope: "col", class: [2, 3, 5].includes(i) ? "num" : null }, x)))),
    h("tbody", {}, shown.map((r) => {
      const flagged = isOff(r);
      return h("tr", { class: flagged ? "flagged" : null },
        h("td", {}, `FY${r.fiscal_year}`), h("th", { scope: "row", class: "mono" }, r.metric),
        h("td", { class: "num" }, fmt(r.synthetic, digits(r.synthetic))), h("td", { class: "num" }, fmt(r.target, digits(r.target))),
        h("td", {}, calUnit(r.metric)), h("td", { class: "num" }, `${fmtSigned(r.rel_error_pct, 2)}%`),
        h("td", {}, flagged ? h("span", { class: "flag" }, `OFF >${OFF_THRESHOLD_PCT}%`) : h("span", { class: "muted" }, "within")),
        h("td", { class: "wrap" }, r.market_facts_section), h("td", {}, r.status));
    }))));
}

// ---------------------------------------------------------------------------------------------------------------
// 3. Experiments
function setProblem(id, focus = false) {
  if (S.problem === id) return;
  S.problem = id;
  for (const t of document.querySelectorAll("#problem-tabs [role=tab]")) {
    const sel = t.dataset.problem === id;
    t.setAttribute("aria-selected", String(sel));
    t.tabIndex = sel ? 0 : -1;
    if (sel && focus) t.focus();
  }
  $("#exp-panel").setAttribute("aria-labelledby", `tab-${id}`);
  S.runId = null; S.programId = null; S.programPinned = false; S.memo = {};
  loadRuns();
}

async function loadRuns() {
  const sel = $("#run-select");
  let r;
  try { r = await api(`/api/runs?problem=${encodeURIComponent(S.problem)}`); }
  catch (e) { errorInto($("#run-header"), "/api/runs", e); return; }
  S.runs = r.runs || [];
  const prevVal = S.runId;
  fill(sel, ...S.runs.map((x) => h("option", { value: x.run_id },
    `${x.run_id} | ${x.status} | ${x.programs ?? 0} programs | source ${x.source}`)));
  if (!S.runId || !S.runs.some((x) => x.run_id === S.runId)) S.runId = S.runs[0]?.run_id || null;
  if (S.runId) sel.value = S.runId;
  sel.disabled = !S.runs.length;
  if (!S.runId) { renderNoRuns(); return; }
  if (prevVal !== S.runId) { S.programId = null; S.programPinned = false; }
  await loadRun();
}

function renderNoRuns() {
  const msg = `No run evidence for ${S.problem} yet. Runs appear here as soon as the controller writes partial evidence.`;
  fill($("#run-header"), h("p", { class: "empty" }, msg));
  for (const id of ["islands-body", "diff-body", "diff-side", "holdout-body", "catches-body", "budget-body", "gate-checks", "gate-actions"]) $(`#${id}`).replaceChildren();
  fill($("#program-select"));
  disposeChart("chart-score");
  fill($("#chart-score"), h("p", { class: "empty" }, msg));
}

async function loadRun() {
  const id = S.runId;
  if (!id) return;
  const enc = encodeURIComponent(id);
  const [det, cat, ho, gate] = await Promise.allSettled([
    api(`/api/runs/${enc}`), api(`/api/runs/${enc}/catches`), api(`/api/runs/${enc}/holdout`), api(`/api/runs/${enc}/gate`),
  ]);
  if (id !== S.runId) return; // a newer selection won
  if (det.status === "rejected") { errorInto($("#run-header"), `/api/runs/${id}`, det.reason); return; }
  const d = det.value;
  S.run = d;
  renderRunHeader(d);
  renderScore(d);
  if (changed("islands", d.island_leaderboard)) renderIslands(d);
  populatePrograms(d);
  if (changed("budget", [d.budget, d.tokens, d.status])) renderBudget(d);
  if (cat.status === "fulfilled") { if (changed("catches", cat.value)) renderCatches(cat.value); }
  else errorInto($("#catches-body"), `/api/runs/${id}/catches`, cat.reason);
  if (ho.status === "fulfilled") { S.holdout = ho.value; if (changed("holdout", [ho.value, d.seed_train, d.status])) renderHoldout(); }
  else errorInto($("#holdout-body"), `/api/runs/${id}/holdout`, ho.reason);
  if (gate.status === "fulfilled") { S.gate = gate.value; if (changed("gate", [gate.value, d.status])) renderGate(); }
  else errorInto($("#gate-checks"), `/api/runs/${id}/gate`, gate.reason);
  // Diff: follow the champion unless the reader pinned a program.
  const champ = bestProgram(d);
  if (!S.programId || (!S.programPinned && champ && champ.id !== S.programId)) await loadDiff(S.programPinned ? S.programId : "");
}

function bestProgram(d) {
  return (d.programs || []).filter((p) => p.valid && p.score !== null && p.score !== undefined).sort((a, b) => b.score - a.score)[0] || null;
}

function renderRunHeader(d) {
  const bl = d.baseline_lock || {};
  const seedIns = (d.programs || []).find((p) => p.idx === 0)?.insight?.text;
  fill($("#run-header"),
    h("div", { class: "run-meta" },
      statusBadge(d),
      h("span", { class: "badge warn" }, h("span", { "aria-hidden": "true" }, "⚠"), `source: ${d.source}`),
      h("span", { class: "badge muted" }, `evolved = ${d.evolved}`),
      h("span", { class: "mono" }, d.run_id),
      h("span", { class: "muted" }, `started ${fmtTime(d.started)}${d.finished ? `, finished ${fmtTime(d.finished)}` : ""}`),
      h("span", { class: "muted" }, `${fmt((d.budget || {}).programs_evaluated, 0)} programs evaluated: ${fmt(d.valid, 0)} valid, ${fmt(d.invalid, 0)} invalid`)),
    d.honesty_note ? h("p", { class: "note" }, d.honesty_note) : null,
    kv([
      ["Baseline lock", `seed reproduced = ${bl.reproduced}; seed raw ${fmt(bl.seed_raw, 1)} JPY M; null program raw ${fmt(bl.null_raw, 1)} JPY M (valid = ${bl.null_valid}); seed minus null ${fmtSigned(bl.seed_minus_null, 1)} JPY M`],
      ["Instance", bl.instance_sha256 ? `sha256 ${bl.instance_sha256}` : "n/a"],
      seedIns ? ["Seed score components", seedIns] : null,
    ]),
  );
}

function renderScore(d) {
  const curve = d.score_curve || [];
  const byIdx = new Map((d.programs || []).map((p) => [p.idx, p]));
  const valid = curve.filter((p) => p.valid && p.score !== null && p.score !== undefined);
  const invalid = curve.filter((p) => !(p.valid && p.score !== null && p.score !== undefined));
  const ys = valid.map((p) => p.score).concat(d.seed_train !== null && d.seed_train !== undefined ? [d.seed_train] : []);
  $("#score-note").textContent = d.problem === "jepx_trading"
    ? "Scores are in JPY M and negative for jepx_trading because the score is minus (annual cost plus risk penalty). Higher, closer to zero, is better."
    : "Scores are in JPY M. Higher is better. A score can be negative because the objective subtracts a tail-risk penalty (see the seed score components above).";
  if (!ys.length) { disposeChart("chart-score"); fill($("#chart-score"), h("p", { class: "empty" }, "No scored programs yet.")); return; }
  const c = getChart("chart-score");
  if (!c) return;
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const span = hi - lo || Math.max(1, Math.abs(hi) * 0.001);
  const band = lo - span * 0.23;
  const bandTop = lo - span * 0.07;
  const yMin = lo - span * 0.32, yMax = hi + span * 0.08;
  const tip = (idx) => {
    const pr = byIdx.get(idx) || {};
    const cp = curve.find((x) => x.idx === idx) || {};
    const out = [`<b>Program ${esc(idx)}</b> ${esc(pr.id ?? "")}`, `Island ${esc(cp.island ?? pr.island ?? "")} | ${esc(pr.model ?? "")}`];
    if (cp.valid && cp.score !== null && cp.score !== undefined) out.push(`Score ${fmt(cp.score, 1)} JPY M`);
    else {
      out.push(`INVALID, kind: ${esc(cp.kind ?? pr.kind ?? "unknown")}`);
      if (pr.raw_score !== null && pr.raw_score !== undefined) out.push(`Raw objective ${fmt(pr.raw_score, 1)} JPY M (not counted)`);
    }
    if (pr.insight && pr.insight.text) out.push(esc(trunc(pr.insight.text, 180)));
    return out.join("<br>");
  };
  c.setOption(baseOpt({
    grid: { left: 92, right: 24, top: 40, bottom: 52 },
    legend: legendOpt({ data: ["Valid program", "Invalid program", "Best so far"] }),
    tooltip: { ...baseOpt().tooltip, formatter: (p) => {
      if (p.componentType === "markLine") return `Seed ${fmt(d.seed_train, 1)} JPY M`;
      if (p.componentType === "markArea") return "Invalid programs are not scored; they sit in this band.";
      if (p.seriesName === "Best so far") return `After program ${esc(p.value[0])}<br>Best so far ${fmt(p.value[1], 1)} JPY M`;
      return tip(p.value[0]);
    } },
    xAxis: ax("value", "Program index (evaluation order)", { min: 0, max: Math.max(1, curve.length - 1), minInterval: 1, nameGap: 30 }),
    yAxis: ax("value", "Score (JPY M, higher is better)", { min: yMin, max: yMax, nameGap: 76,
      axisLabel: { showMinLabel: false, showMaxLabel: false, formatter: (v) => (v < bandTop ? "" : fmt(v, 0)) } }),
    series: [
      { name: "Valid program", type: "scatter", symbol: "circle", symbolSize: 9, itemStyle: { color: T.accent },
        data: valid.map((p) => [p.idx, p.score]) },
      { name: "Invalid program", type: "scatter", symbol: X_SYMBOL, symbolSize: 12, itemStyle: { color: T.crit },
        data: invalid.map((p) => [p.idx, band]),
        markArea: { silent: false, itemStyle: { color: "rgba(255,69,58,0.07)" },
          label: { show: true, position: "insideTopLeft", color: T.crit, fontSize: 11, formatter: "Invalid (not scored)" },
          data: [[{ yAxis: yMin }, { yAxis: bandTop }]] } },
      { name: "Best so far", type: "line", step: "end", showSymbol: false, symbol: "none", z: 1,
        data: curve.filter((p) => p.best !== null && p.best !== undefined).map((p) => [p.idx, p.best]),
        lineStyle: { color: T.warn, width: 2 }, itemStyle: { color: T.warn },
        markLine: d.seed_train === null || d.seed_train === undefined ? undefined : {
          symbol: "none", lineStyle: { color: T.fg, type: "dashed", width: 1 },
          label: { color: T.fg, position: "insideStartTop", formatter: `Seed ${fmt(d.seed_train, 1)} JPY M` },
          data: [{ yAxis: d.seed_train, name: "Seed" }] } },
    ],
  }), true);
}

function renderIslands(d) {
  const lb = d.island_leaderboard || {};
  const keys = Object.keys(lb).sort((a, b) => Number(a) - Number(b));
  const champ = bestProgram(d);
  const body = $("#islands-body");
  if (!keys.length) { fill(body, h("p", { class: "empty" }, "No scored programs on any island yet.")); return; }
  fill(body, ...keys.map((k) => h("div", { class: "island" },
    h("h4", {}, `Island ${k}`),
    h("table", { class: "data" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "#"), h("th", { scope: "col" }, "Program"), h("th", { scope: "col", class: "num" }, "Score (JPY M)"), h("th", { scope: "col" }, "Model"))),
      h("tbody", {}, lb[k].map((r, i) => h("tr", {},
        h("td", {}, String(i + 1)),
        h("td", { class: "mono" }, r.id, champ && champ.id === r.id ? h("span", { class: "star" }, " ★ best") : null),
        h("td", { class: "num" }, fmt(r.score, 1)), h("td", {}, r.model))))))));
}

function populatePrograms(d) {
  const sel = $("#program-select");
  const valid = (d.programs || []).filter((p) => p.valid && p.score !== null && p.score !== undefined).sort((a, b) => b.score - a.score);
  if (!changed("programs", valid.map((p) => [p.id, p.score]))) { if (S.programId) sel.value = S.programId; return; }
  fill(sel, ...valid.map((p, i) => h("option", { value: p.id },
    `${i + 1}. ${p.id} | ${fmt(p.score, 1)} JPY M | ${p.model}${p.idx === 0 ? " (seed)" : ""}`)));
  if (S.programId && valid.some((p) => p.id === S.programId)) sel.value = S.programId;
}

async function loadDiff(pid) {
  const id = S.runId;
  const q = pid ? `?program_id=${encodeURIComponent(pid)}` : "";
  let r;
  try { r = await api(`/api/runs/${encodeURIComponent(id)}/diff${q}`); }
  catch (e) { errorInto($("#diff-body"), `/api/runs/${id}/diff`, e); fill($("#diff-side")); return; }
  if (id !== S.runId) return;
  S.programId = r.program_id;
  const sel = $("#program-select");
  if ([...sel.options].some((o) => o.value === r.program_id)) sel.value = r.program_id;
  renderDiff(r);
}

const PY_KW = new Set(["def", "return", "if", "elif", "else", "for", "while", "in", "not", "and", "or", "is", "None", "True", "False",
  "import", "from", "as", "with", "try", "except", "finally", "raise", "lambda", "pass", "break", "continue", "class", "yield", "assert", "del", "global"]);
const PY_TOKEN = /("""[^]*?"""|'''[^]*?'''|"(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?|#.*$|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|[A-Za-z_][A-Za-z0-9_]*)/g;
function highlight(src) {
  const out = [];
  let last = 0;
  for (const m of src.matchAll(PY_TOKEN)) {
    const tok = m[0], off = m.index;
    if (off > last) out.push(document.createTextNode(src.slice(last, off)));
    let cls = null;
    if (tok[0] === "#") cls = "t-com";
    else if (tok[0] === '"' || tok[0] === "'") cls = "t-str";
    else if (/^\d/.test(tok)) cls = "t-num";
    else if (PY_KW.has(tok)) cls = "t-kw";
    else if (src[off + tok.length] === "(") cls = "t-fn";
    out.push(cls ? h("span", { class: cls }, tok) : document.createTextNode(tok));
    last = off + tok.length;
  }
  if (last < src.length) out.push(document.createTextNode(src.slice(last)));
  return out;
}

function renderDiff(r) {
  const text = r.diff_vs_seed || "";
  const lines = text.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  let adds = 0, dels = 0;
  const rows = lines.map((line) => {
    let cls = "ctx", g = " ", body = line.slice(1), sr = "";
    if (line.startsWith("+++") || line.startsWith("---")) { cls = "hdr"; body = line; }
    else if (line.startsWith("@@")) { cls = "hunk"; g = "@"; body = line; }
    else if (line.startsWith("+")) { cls = "add"; g = "+"; adds++; sr = "added: "; }
    else if (line.startsWith("-")) { cls = "del"; g = "-"; dels++; sr = "removed: "; }
    return h("div", { class: `dl ${cls}` }, h("span", { class: "g", "aria-hidden": "true" }, g),
      h("span", { class: "code" }, sr ? h("span", { class: "sr-only" }, sr) : null, cls === "hdr" || cls === "hunk" ? body : highlight(body)));
  });
  const isSeed = !adds && !dels;
  fill($("#diff-body"),
    h("p", { class: "diff-stats" }, `${r.program_id}: ${fmt(r.score, 1)} JPY M | +${adds} added, -${dels} removed lines vs seed`),
    isSeed ? h("p", { class: "empty" }, "No changes against the seed block (this is the seed or an identical copy).")
      : h("div", { class: "diff", role: "region", tabindex: "0", "aria-label": `Unified diff, seed versus ${r.program_id}` }, rows),
  );
  const side = [];
  if (r.insights && r.insights.length) {
    side.push(h("h4", {}, "Evaluator insights"), h("ul", { class: "insights" }, r.insights.map((i) => h("li", {}, h("span", { class: "lbl" }, `${i.label}: `), i.text))));
  }
  side.push(h("h4", {}, "Mutator rationale"), h("p", { class: "plain" }, r.rationale || "No rationale recorded."));
  if (r.lineage && r.lineage.length) {
    side.push(h("h4", {}, "Lineage (seed to champion)"), h("ol", { class: "lineage" }, r.lineage.map((l) => h("li", {},
      h("span", { class: "mono" }, `${l.id} | ${l.model} | ${fmt(l.score, 1)} JPY M`), h("p", { class: "plain" }, l.rationale || "")))));
  }
  fill($("#diff-side"), ...side);
}

function renderHoldout() {
  const res = S.holdout || {};
  const d = S.run || {};
  const body = $("#holdout-body");
  const ho = res.holdout;
  if (!ho) {
    disposeChart("chart-holdout");
    fill(body,
      h("div", { class: "big-delta" }, h("span", { class: "caps" }, "Holdout delta (only citable uplift)"), h("span", { class: "kpi-value" }, "not recorded")),
      h("p", { class: "empty" }, d.status === "running"
        ? "Holdout rescoring has not run yet. It runs once, after the search stops, on a scenario bank the search never sees."
        : "No holdout record in this run's evidence."),
      res.uplift_note ? h("p", { class: "note" }, res.uplift_note) : null);
    return;
  }
  const upl = res.uplift_valid;
  const uplBadge = upl === true ? h("span", { class: "badge ok" }, h("span", { "aria-hidden": "true" }, "✓"), "uplift_valid = true")
    : upl === false ? h("span", { class: "badge crit" }, h("span", { "aria-hidden": "true" }, "✖"), "uplift_valid = false")
      : h("span", { class: "badge muted" }, `uplift_valid = ${upl}`);
  const rows = ho.top_k || [];
  const mode = S.holdoutMode;
  const seedTrain = d.seed_train;
  const tv = (r) => (r.train === null || r.train === undefined ? null : mode === "delta" ? (seedTrain === null || seedTrain === undefined ? null : r.train - seedTrain) : r.train);
  const hv = (r) => (r.holdout === null || r.holdout === undefined ? null : mode === "delta" ? (ho.seed === null || ho.seed === undefined ? null : r.holdout - ho.seed) : r.holdout);
  fill(body,
    h("div", { class: "big-delta" }, h("span", { class: "caps" }, "Holdout delta (only citable uplift)"),
      ho.holdout_delta === null || ho.holdout_delta === undefined
        ? h("span", { class: "kpi-value" }, "none")
        : [h("span", { class: "kpi-value" }, fmtSigned(ho.holdout_delta, 1)), h("span", { class: "unit" }, "JPY M")],
      uplBadge),
    res.uplift_note ? h("p", { class: "note" }, res.uplift_note) : null,
    ho.selection ? h("p", { class: "rule" }, `Selection rule: ${ho.selection}`) : null,
    kv([
      ["Seed holdout", `${fmt(ho.seed, 1)} JPY M (valid = ${ho.seed_valid})`],
      ["Champion", `${ho.best_id ?? "none"}: holdout ${fmt(ho.best_holdout, 1)} JPY M${ho.best_is_seed ? " (the seed itself)" : ""}`],
      ["Null program holdout", `${fmt(ho.null, 1)} JPY M (valid = ${ho.null_valid})`],
      ["Best holdout in top-k", `${fmt(ho.max_holdout_in_top_k, 1)} JPY M (${ho.max_holdout_id ?? "n/a"}), reported only, never used to select`],
    ]),
    h("div", { class: "chart", id: "chart-holdout", role: "img", "aria-label": "Train and holdout score per top candidate with the seed holdout line" }),
    h("p", { class: "note" }, mode === "delta"
      ? "Bars show change vs the seed on the same bank: train minus seed train, holdout minus seed holdout. Higher is better. Train bars are hatched."
      : "Absolute scores. Train and holdout are different scenario banks, so compare each holdout bar with the seed holdout line. Train bars are hatched."),
    h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Holdout top-k table" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Program", "Train (JPY M)", "Holdout (JPY M)", "Holdout check"].map((x, i) => h("th", { scope: "col", class: i === 1 || i === 2 ? "num" : null }, x)))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("th", { scope: "row", class: "mono" }, r.id, r.id === ho.best_id ? h("span", { class: "star" }, " ★ champion") : null),
        h("td", { class: "num" }, fmt(r.train, 1)), h("td", { class: "num" }, fmt(r.holdout, 1)),
        h("td", {}, r.holdout_valid ? h("span", { class: "status verified" }, h("span", { "aria-hidden": "true" }, "✓"), "VALID")
          : h("span", { class: "status estimate" }, h("span", { "aria-hidden": "true" }, "✖"), `INVALID${r.holdout_kind ? ` (${r.holdout_kind})` : ""}`))))))),
  );
  const c = getChart("chart-holdout");
  if (!c) return;
  const seedLineY = mode === "delta" ? 0 : ho.seed;
  c.setOption(baseOpt({
    grid: { left: 84, right: 16, top: 40, bottom: 64 },
    legend: legendOpt({ data: ["Train", "Holdout"] }),
    tooltip: { ...baseOpt().tooltip, ...axisTip((ps) => {
      const r = rows[ps[0].dataIndex] || {};
      return `${esc(r.id)}<br>Train ${fmt(r.train, 1)} JPY M<br>Holdout ${fmt(r.holdout, 1)} JPY M (${r.holdout_valid ? "valid" : "INVALID"})` +
        (mode === "delta" ? `<br>Change vs seed: train ${fmtSigned(tv(r), 1)}, holdout ${fmtSigned(hv(r), 1)} JPY M` : "");
    }) },
    xAxis: ax("category", "Top candidates by train score", { data: rows.map((r) => r.id), splitLine: { show: false }, nameGap: 44,
      axisLabel: { fontFamily: "JetBrains Mono, monospace", fontSize: 10, rotate: rows.length > 3 ? 20 : 0 } }),
    yAxis: ax("value", mode === "delta" ? "Change vs seed (JPY M)" : "Score (JPY M)", { nameGap: 64, scale: mode !== "delta",
      axisLabel: { formatter: (v) => fmt(v, 0) } }),
    series: [
      { name: "Train", type: "bar", barMaxWidth: 26, data: rows.map(tv),
        itemStyle: { color: T.info, decal: { symbol: "rect", symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: -0.785, color: "rgba(0,0,0,0.45)" } } },
      { name: "Holdout", type: "bar", barMaxWidth: 26,
        data: rows.map((r) => r.holdout_valid
          ? { value: hv(r), itemStyle: { color: T.accent } }
          : { value: hv(r) ?? 0, itemStyle: { color: "rgba(255,69,58,0.15)", borderColor: T.crit, borderWidth: 1, borderType: "dashed" },
            label: { show: true, position: "top", color: T.crit, fontSize: 10, formatter: "INVALID" } }),
        itemStyle: { color: T.accent },
        markLine: seedLineY === null || seedLineY === undefined ? undefined : {
          symbol: "none", lineStyle: { color: T.fg, type: "dashed", width: 1 },
          label: { color: T.fg, position: "insideEndTop", formatter: `Seed holdout ${fmt(ho.seed, 1)} JPY M` },
          data: [{ yAxis: seedLineY }] } },
    ],
  }), true);
}

function renderCatches(c) {
  const body = $("#catches-body");
  const kinds = Object.entries(c.by_kind || {});
  const list = c.catches || [];
  const head = kinds.length
    ? h("div", { class: "chips-inline", role: "list", "aria-label": "Catches by kind" },
      kinds.map(([k, n]) => h("span", { class: "chip", role: "listitem" }, h("span", { "aria-hidden": "true" }, "⚠"), `${k}: ${n}`)))
    : null;
  if (!list.length) {
    fill(body, h("p", { class: "empty" }, "No invalid candidates in this run so far. Every evaluated program passed the sandbox and the policy invariants."));
    return;
  }
  fill(body,
    h("p", { class: "note" }, `${list.length} candidates were rejected before they could count as uplift. Seed train score ${fmt(c.seed_train, 1)} JPY M.`),
    head,
    h("ul", { class: "catch-list" }, list.map((x) => {
      const raw = x.raw_score;
      return h("li", { class: "catch" },
        h("div", { class: "catch-head" },
          h("span", { class: "mono" }, `#${x.idx} ${x.id}`),
          h("span", { class: "chip" }, h("span", { "aria-hidden": "true" }, "✖"), `kind: ${x.kind ?? "unknown"}`),
          h("span", { class: "muted small-text" }, x.model || "")),
        h("p", { class: "would" }, x.invariants && x.invariants.length ? `Invariants violated: ${x.invariants.join(", ")}` : "No invariant names recorded for this catch."),
        x.insights && x.insights.length ? h("ul", { class: "insights" }, x.insights.map((i) => h("li", {}, h("span", { class: "lbl" }, `${i.label}: `), i.text))) : null,
        h("p", { class: "would" }, raw !== null && raw !== undefined
          ? `Would have scored ${fmt(raw, 1)} JPY M vs seed ${fmt(c.seed_train, 1)} JPY M (${fmtSigned(raw - c.seed_train, 1)} JPY M). Not counted.`
          : "No raw score: the program did not produce an evaluable result."),
        x.rationale ? h("details", {}, h("summary", {}, "Mutator rationale"), h("p", { class: "plain" }, x.rationale)) : null);
    })),
  );
}

function renderBudget(d) {
  const b = d.budget || {}, pol = d.budget_policy || {}, t = d.tokens || {};
  const pct = b.max_programs ? Math.min(100, (100 * (b.programs_evaluated || 0)) / b.max_programs) : 0;
  const byModel = Object.entries(t.by_model || {});
  const search = d.search || {};
  fill($("#budget-body"),
    h("p", { class: "panel-h" }, "Run budget"),
    h("div", { class: "meter", role: "progressbar", "aria-label": "Programs evaluated", "aria-valuemin": "0", "aria-valuemax": String(b.max_programs ?? 0), "aria-valuenow": String(b.programs_evaluated ?? 0) },
      h("span", { style: `width:${pct}%` })),
    kv([
      ["Programs", `${fmt(b.programs_evaluated, 0)} of ${fmt(b.max_programs, 0)} evaluated`],
      ["Wall time", `${fmt(b.wall_s, 1)} s of ${fmt(pol.max_wall_s, 0)} s cap`],
      ["Stopped reason", b.stopped_reason || (d.status === "running" ? "still running" : "not recorded")],
      ["Plateau", `${fmt(b.plateau_since, 0)} feasible programs since the last improvement (patience ${fmt(pol.plateau_patience, 0)})`],
      ["Concurrency", `${fmt(b.concurrency, 0)} parallel evaluations`],
      search.islands !== undefined ? ["Search", `${search.islands} islands, ${search.archive}, parent selection ${search.parent_selection}, migration every ${search.migration_every} programs, ${search.diff_format}`] : null,
    ]),
    h("p", { class: "panel-h" }, "Tokens"),
    kv([
      ["Calls", `${fmt(t.calls, 0)} (${fmt(t.errors, 0)} errors)`],
      ["Prompt", `${fmt(t.prompt, 0)} tokens`], ["Output", `${fmt(t.output, 0)} tokens`], ["Thinking", `${fmt(t.thinking, 0)} tokens`],
      ["Est. cost", `${fmt(t.cost_usd, 4)} USD`],
      d.model_mix && d.model_mix.length ? ["Model mix", d.model_mix.map((m) => `${m.name} ${fmt(m.weight * 100, 0)}%`).join(", ")] : null,
    ]),
    byModel.length ? h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Tokens by model" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Model", "Calls", "Prompt", "Output", "Thinking", "Cost (USD)"].map((x, i) => h("th", { scope: "col", class: i ? "num" : null }, x)))),
      h("tbody", {}, byModel.map(([m, v]) => h("tr", {}, h("th", { scope: "row", class: "mono" }, m),
        h("td", { class: "num" }, fmt(v.calls, 0)), h("td", { class: "num" }, fmt(v.prompt, 0)), h("td", { class: "num" }, fmt(v.output, 0)),
        h("td", { class: "num" }, fmt(v.thinking, 0)), h("td", { class: "num" }, fmt(v.cost_usd, 4))))))) : null,
    d.pricing_note ? h("p", { class: "note" }, d.pricing_note) : null,
  );
}

async function loadLedger() {
  const body = $("#ledger-body");
  let l;
  try { l = await api("/api/ledger"); } catch (e) { errorInto(body, "/api/ledger", e); return; }
  if (!changed("ledger", l)) return;
  const pol = l.policy || {};
  const runs = l.runs || [];
  fill(body,
    h("p", { class: "panel-h" }, "Policy"),
    kv(Object.entries(pol).map(([k, v]) => [k, `${typeof v === "number" ? fmt(v, 0) : String(v)} ${POLICY_UNITS[k] || ""}`.trim()])),
    h("p", { class: "panel-h" }, "Runs in the ledger"),
    runs.length ? h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Ledger runs" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Run", "Started", "Source", "Programs", "Counts", "Status"].map((x, i) => h("th", { scope: "col", class: i === 3 ? "num" : null }, x)))),
      h("tbody", {}, runs.map((r) => h("tr", {},
        h("th", { scope: "row", class: "mono" }, r.run_id), h("td", {}, fmtTime(r.started)), h("td", {}, r.source),
        h("td", { class: "num" }, fmt(r.programs, 0)), h("td", {}, r.counts_against_budget ? "yes, against budget" : "no"),
        h("td", {}, r.status)))))) : h("p", { class: "empty" }, "The ledger has no runs yet."),
    h("p", { class: "note" }, "Programs is the ledger reservation while a run is in flight and the evaluated count once it finishes."),
  );
}

// ---------------------------------------------------------------------------------------------------------------
// 4. Promotion gate
function gateValue(c) {
  if (c.value === null || c.value === undefined) return "null";
  if (c.id === "holdout_delta" && typeof c.value === "number") return `${fmtSigned(c.value, 1)} JPY M`;
  if (c.id === "human_review") return `${c.value} review(s) of the champion`;
  return String(c.value);
}

function renderGate() {
  const g = S.gate;
  const d = S.run || {};
  if (!g) return;
  $("#gate-run").textContent = g.run_id ? `(${g.run_id})` : "";
  fill($("#gate-checks"),
    h("ul", { class: "checklist" }, (g.checks || []).map((c) => h("li", { class: `check ${c.ok ? "pass" : "blocked"}` },
      h("span", { class: "icon", "aria-hidden": "true" }, c.ok ? "✓" : "✖"),
      h("span", { class: "verdict" }, c.ok ? "PASS" : "BLOCKED"),
      h("div", {}, c.label, h("span", { class: "val" }, `${c.id}: ${gateValue(c)}`))))),
    h("p", { class: "note" }, `${(g.blockers || []).length} blocker(s). evolved = ${g.evolved}; promotion_allowed = ${g.promotion_allowed}.`),
  );

  const actions = $("#gate-actions");
  const finished = d.status === "finished";
  const canReview = finished && !!g.best_program_id;
  const note = h("textarea", { id: "review-note", rows: "3", placeholder: "What did you read in the evolved block?" });
  note.value = S.reviewNote;
  note.addEventListener("input", () => { S.reviewNote = note.value; });
  const msg = h("p", { class: "msg-line", role: "status" });
  const reviewBtn = h("button", { class: "btn primary", type: "button" }, "Mark human-reviewed");
  reviewBtn.disabled = !canReview;
  if (canReview) {
    holdToConfirm(reviewBtn, async () => {
      msg.className = "msg-line"; msg.textContent = "Recording review";
      try {
        const r = await postJSON(`/api/runs/${encodeURIComponent(g.run_id)}/review`, { program_id: g.best_program_id, reviewer: "demo-reviewer", note: S.reviewNote });
        S.reviewNote = "";
        await refreshGate(`Review recorded at ${fmtTime(r.review && r.review.at)} for ${g.best_program_id}.`, "ok");
      } catch (e) {
        msg.className = "msg-line err"; msg.textContent = `Review failed: ${e.message}`;
      }
    });
  }
  const reviewReason = canReview ? "Press and hold for 2 s. Appends an audit record only; it never promotes."
    : !finished ? `Disabled: run status is ${d.status ?? "unknown"}. Reviews open when the run finishes.`
      : "Disabled: no champion recorded for this run.";
  let promoteBtn;
  const promoteMsg = h("p", { class: "msg-line", role: "status" });
  if (g.promotion_control === "enabled") {
    promoteBtn = h("button", { class: "btn", type: "button" }, "Promote to production");
    holdToConfirm(promoteBtn, async () => {
      try { await postJSON(`/api/runs/${encodeURIComponent(g.run_id)}/promote`); promoteMsg.className = "msg-line ok"; promoteMsg.textContent = "Promotion accepted."; }
      catch (e) { promoteMsg.className = "msg-line err"; promoteMsg.textContent = `Promotion refused: ${e.message}`; }
    });
  } else {
    promoteBtn = h("button", { class: "btn", type: "button", disabled: true, "aria-describedby": "promote-reason" }, "Promote to production");
  }
  const reviews = g.reviews || [];
  fill(actions,
    kv([["Champion", g.best_program_id || "none recorded yet (holdout rescoring has not run)"], ["Run status", d.status ?? "unknown"]]),
    h("div", { class: "field" }, h("label", { for: "review-note", class: "caps" }, "Reviewer note"), note),
    h("div", { class: "action-row" }, reviewBtn, h("span", { class: "reason", id: "review-reason" }, reviewReason)),
    msg,
    h("div", { class: "action-row" }, promoteBtn,
      h("span", { class: "reason", id: "promote-reason" }, g.promotion_control === "enabled" ? "Press and hold for 2 s." : `Promotion control: ${g.promotion_control}`)),
    promoteMsg,
    h("p", { class: "panel-h" }, `Review log (${reviews.length})`),
    reviews.length ? h("ul", { class: "review-list" }, reviews.map((r) => h("li", {},
      h("span", { class: "mono" }, `${fmtTime(r.at)} | ${r.reviewer} | ${r.program_id}`), r.note ? h("p", { class: "plain" }, r.note) : null)))
      : h("p", { class: "empty" }, "No human review recorded for this run."),
  );
  if (reviewBtn.disabled) reviewBtn.setAttribute("aria-describedby", "review-reason");
}

async function refreshGate(message, kind) {
  if (!S.runId) return;
  try {
    S.gate = await api(`/api/runs/${encodeURIComponent(S.runId)}/gate`);
    S.memo.gate = null;
    renderGate();
  } catch (e) { errorInto($("#gate-checks"), `/api/runs/${S.runId}/gate`, e); }
  if (message) {
    const el = $("#gate-actions .msg-line");
    if (el) { el.className = `msg-line ${kind || ""}`; el.textContent = message; }
  }
}

// ---------------------------------------------------------------------------------------------------------------
// 5. Analyst chat, trace console, pending actions
function traceLine(kind, text) {
  const el = $("#trace");
  const t = new Date().toISOString().slice(11, 19);
  el.append(h("div", { class: kind }, `${t} ${text}`));
  while (el.childElementCount > 500) el.firstElementChild.remove();
  el.scrollTop = el.scrollHeight;
}

function renderRich(el, text) {
  fill(el);
  text.split("\n").forEach((line, i) => {
    if (i) el.append(h("br"));
    for (const part of line.split(/(\*\*[^*]+\*\*)/g)) {
      if (!part) continue;
      if (/^\*\*[^*]+\*\*$/.test(part)) el.append(h("strong", {}, part.slice(2, -2)));
      else el.append(document.createTextNode(part));
    }
  });
}

function addMsg(role, text) {
  const body = h("div", { class: "body" });
  const el = h("div", { class: `msg ${role}` }, h("span", { class: "who" }, role === "user" ? "You" : "Lab Analyst"), body);
  if (text) renderRich(body, text);
  const log = $("#chat-log");
  log.append(el);
  log.scrollTop = log.scrollHeight;
  return { el, body };
}

function setChatBusy(b) {
  S.chatBusy = b;
  $("#chat-send").disabled = b;
  for (const c of document.querySelectorAll("#chips button")) c.disabled = b;
}

async function sendChat(message) {
  const msg = message.trim();
  if (!msg || S.chatBusy) return;
  setChatBusy(true);
  addMsg("user", msg);
  const bubble = addMsg("assistant", "");
  let text = "";
  const log = $("#chat-log");
  const onEvent = (ev) => {
    switch (ev.type) {
      case "session":
        S.sessionId = ev.session_id;
        traceLine("res", `session ${ev.session_id}`);
        break;
      case "tool_call":
        traceLine("tool", `> ${ev.tool}(${trunc(JSON.stringify(ev.args ?? {}), 400)})`);
        break;
      case "tool_result":
        traceLine("res", `< ${ev.tool}: ${trunc(JSON.stringify(ev.result ?? {}), 500)}`);
        break;
      case "pending_action":
        traceLine("tool", `! pending action ${ev.action?.id}: ${ev.action?.summary ?? ev.action?.kind ?? ""}`);
        loadActions();
        break;
      case "text":
        if (ev.text) {
          text += (text && !text.endsWith("\n") ? "\n\n" : "") + ev.text;
          renderRich(bubble.body, text);
          log.scrollTop = log.scrollHeight;
        }
        break;
      case "final":
        traceLine("res", `final${ev.author ? ` (${ev.author})` : ""}`);
        break;
      case "error":
        traceLine("err", `error: ${ev.error}`);
        bubble.el.classList.add("err");
        text += (text ? "\n\n" : "") + `Error: ${ev.error}`;
        renderRich(bubble.body, text);
        break;
      default:
        traceLine("sys", `event ${trunc(JSON.stringify(ev), 200)}`);
    }
  };
  const handleChunk = (chunk) => {
    const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, "")).join("\n");
    if (!data) return;
    try { onEvent(JSON.parse(data)); } catch { traceLine("err", `unparsable event: ${trunc(data, 200)}`); }
  };
  traceLine("sys", `POST /api/chat (session ${S.sessionId || "new"})`);
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg, session_id: S.sessionId }) });
    if (!r.ok || !r.body) throw new Error(`${r.status} ${r.statusText}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) { handleChunk(buf.slice(0, i)); buf = buf.slice(i + 2); }
    }
    buf += dec.decode();
    if (buf.trim()) handleChunk(buf);
  } catch (e) {
    traceLine("err", `error: ${e.message}`);
    bubble.el.classList.add("err");
    text += (text ? "\n\n" : "") + `Error: ${e.message}`;
    renderRich(bubble.body, text);
  } finally {
    if (!text) renderRich(bubble.body, "No text returned. See the trace console.");
    setChatBusy(false);
    loadActions();
  }
}

function actionBadge(status) {
  if (status === "pending") return h("span", { class: "badge warn" }, h("span", { "aria-hidden": "true" }, "◔"), "Pending");
  if (status === "executed") return h("span", { class: "badge ok" }, h("span", { "aria-hidden": "true" }, "✓"), "Executed");
  if (status === "executed_sandbox") return h("span", { class: "badge info" }, h("span", { "aria-hidden": "true" }, "✓"), "Executed (sandbox)");
  if (status === "rejected") return h("span", { class: "badge muted" }, h("span", { "aria-hidden": "true" }, "✖"), "Rejected");
  return h("span", { class: "badge muted" }, String(status));
}

async function loadActions() {
  const body = $("#pending-body");
  let list;
  try { list = await api("/api/actions"); } catch (e) { errorInto(body, "/api/actions", e); return; }
  if (!list.length) {
    fill(body, h("p", { class: "empty" }, "No actions yet. When the analyst proposes a write, such as recording a human review, it waits here for a person."));
    return;
  }
  fill(body, h("ul", { class: "pending-list" }, list.map((a) => {
    const msg = h("p", { class: "msg-line", role: "status" });
    const kids = [
      h("div", { class: "catch-head" }, h("strong", {}, a.summary || a.kind || a.id), actionBadge(a.status)),
      kv([
        ["Action", `${a.id} (${a.kind ?? "unknown kind"})`],
        ["Risk", a.risk ?? "not stated"],
        ["Requires", a.requires ?? "hold_to_confirm"],
        ["Agent source", Array.isArray(a.reasoning_source) ? a.reasoning_source.join(", ") : a.reasoning_source ? String(a.reasoning_source) : "not given"],
        ["Created", fmtTime(a.created)],
        a.decided ? ["Decided", fmtTime(a.decided)] : null,
      ]),
      a.details ? h("details", {}, h("summary", {}, "Details"), kv(Object.entries(a.details).map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)]))) : null,
      a.result ? h("p", { class: "note" }, `Result: ${trunc(JSON.stringify(a.result), 400)}`) : null,
    ];
    if (a.status === "pending") {
      const confirm = h("button", { class: "btn primary", type: "button" }, "Confirm");
      holdToConfirm(confirm, async () => {
        try {
          await postJSON(`/api/actions/${encodeURIComponent(a.id)}/confirm`);
          traceLine("res", `action ${a.id} confirmed by a person`);
          if (a.details && a.details.run_id === S.runId) await refreshGate();
          await loadActions();
        } catch (e) { msg.className = "msg-line err"; msg.textContent = `Confirm failed: ${e.message}`; }
      });
      const reject = h("button", { class: "btn danger-outline", type: "button", onclick: async () => {
        reject.disabled = true;
        try { await postJSON(`/api/actions/${encodeURIComponent(a.id)}/reject`); traceLine("res", `action ${a.id} rejected`); await loadActions(); }
        catch (e) { reject.disabled = false; msg.className = "msg-line err"; msg.textContent = `Reject failed: ${e.message}`; }
      } }, "Reject");
      kids.push(h("div", { class: "action-row" }, confirm, reject, h("span", { class: "reason" }, "Hold Confirm for 2 s.")), msg);
    }
    return h("li", { class: `pending${a.status === "pending" ? " is-pending" : ""}` }, kids);
  })));
}

// ---------------------------------------------------------------------------------------------------------------
// Polling: every 10 s while any run is in progress
function schedulePoll() {
  clearTimeout(S.pollTimer);
  S.pollTimer = setTimeout(poll, POLL_MS);
}
function updatePollStatus(runs) {
  const n = runs.filter((r) => r.status === "running").length;
  const t = new Date().toISOString().slice(11, 19);
  $("#poll-status").textContent = n
    ? `Live: ${n} run(s) in progress. Last refresh ${t} UTC, next in ${POLL_MS / 1000} s.`
    : `No run in progress. Auto refresh paused at ${t} UTC.`;
}
async function poll() {
  let runs;
  try { runs = (await api("/api/runs")).runs || []; }
  catch (e) { $("#poll-status").textContent = `Refresh failed: ${e.message}. Retrying in ${POLL_MS / 1000} s.`; schedulePoll(); return; }
  const prev = S.allRuns || [];
  const statusChanged = runs.length !== prev.length || runs.some((r) => (prev.find((p) => p.run_id === r.run_id) || {}).status !== r.status);
  S.allRuns = runs;
  const running = runs.some((r) => r.status === "running");
  const open = runs.find((r) => r.run_id === S.runId);
  const tasks = [loadLedger()];
  if (statusChanged) tasks.push(loadOverview());
  if (statusChanged || (open && open.status === "running") || (!open && runs.some((r) => r.problem === S.problem))) tasks.push(loadRuns());
  await Promise.allSettled(tasks);
  updatePollStatus(runs);
  if (running) schedulePoll();
}

// ---------------------------------------------------------------------------------------------------------------
// Wiring
function wire() {
  $("#duration-scale").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-scale]");
    if (!b || b.disabled) return;
    S.durationLog = b.dataset.scale === "log";
    setPressed($("#duration-scale"), "scale", b.dataset.scale);
    renderDuration();
  });
  $("#cost-voltage").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b || S.costVoltage === b.dataset.v) return;
    S.costVoltage = b.dataset.v;
    setPressed($("#cost-voltage"), "v", b.dataset.v);
    loadCost();
  });
  const rmRange = $("#rm-range");
  if (rmRange) rmRange.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-r]");
    if (!b) return;
    S.rmRange = b.dataset.r;
    setPressed(rmRange, "r", b.dataset.r);
    renderRm();
  });
  $("#cal-filter").addEventListener("click", (e) => {
    S.calOnlyOff = !S.calOnlyOff;
    e.currentTarget.setAttribute("aria-pressed", String(S.calOnlyOff));
    renderCalibration();
  });
  $("#holdout-mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b) return;
    S.holdoutMode = b.dataset.mode;
    setPressed($("#holdout-mode"), "mode", b.dataset.mode);
    renderHoldout();
  });

  const tabs = [...document.querySelectorAll("#problem-tabs [role=tab]")];
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => setProblem(t.dataset.problem));
    t.addEventListener("keydown", (e) => {
      let j = null;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = tabs.length - 1;
      if (j === null) return;
      e.preventDefault();
      setProblem(tabs[j].dataset.problem, true);
    });
  });
  $("#run-select").addEventListener("change", (e) => {
    S.runId = e.target.value; S.programId = null; S.programPinned = false; S.memo = {};
    loadRun();
  });
  $("#program-select").addEventListener("change", (e) => {
    S.programPinned = true;
    loadDiff(e.target.value);
  });

  fill($("#chips"), ...CHIPS.map((c) => h("button", { class: "btn", type: "button", onclick: () => sendChat(c) }, c)));
  const input = $("#chat-input");
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = input.value;
    if (!v.trim() || S.chatBusy) return;
    input.value = "";
    sendChat(v);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  $("#trace-clear").addEventListener("click", () => fill($("#trace")));
  $("#actions-refresh").addEventListener("click", loadActions);
}

async function init() {
  readTheme();
  wire();
  traceLine("sys", "Trace console ready. Tool calls from the Lab Analyst appear here.");
  await loadOverview();
  loadDuration();
  loadMonthly();
  loadPortfolio();
  loadCost();
  loadCalibration();
  loadActions();
  await Promise.allSettled([loadRuns(), loadLedger()]);
  updatePollStatus(S.allRuns);
  if (S.allRuns.some((r) => r.status === "running")) schedulePoll();
}

init();
