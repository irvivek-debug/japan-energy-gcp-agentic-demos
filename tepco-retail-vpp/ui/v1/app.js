// Retail Energy Desk UI. Static ES module, no build step.
// Every figure on the page is read from /api/*. Model text and tool previews are untrusted:
// they are only ever inserted as textContent, or through renderMarkdown(), which escapes first.
import { holdToConfirm } from "./hold-to-confirm.js";

/* ------------------------------------------------------------------------------------------ constants */
const DEFAULT_CUSTOMER = "C-0001"; // request parameter for the first CFE view
const PPA_QUERY = { prospect_id: "PR-01", target: 90 }; // request parameters for the prospect design toggle
const ORCH = "desk_orchestrator";
const AGENTS = [
  { id: "desk_orchestrator", short: "ORCH", role: "Routes the request", color: "#3987e5" },
  { id: "trading_dispatch_agent", short: "TRADE", role: "Hedging and VPP dispatch", color: "#d95926" },
  { id: "contract_risk_agent", short: "RISK", role: "Contracts and margin risk", color: "#199e70" },
  { id: "onboarding_agent", short: "ONBOARD", role: "Prospect onboarding and PPA design", color: "#c98500" },
  { id: "cfe_provenance_agent", short: "CFE", role: "24/7 CFE and certificates", color: "#d55181" },
  { id: "risk_auditor", short: "AUDIT", role: "Policy compliance checks", color: "#9085e9" },
];
const AGENT_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a]));
const SERIES = { spot: "#3987e5", ask: "#d95926", imb: "#199e70", rm: "#9085e9", long: "#6b7a90", short: "#e66767",
  da: "#3987e5", latest: "#d95926", actual: "#199e70", soc: "#3987e5" };
const RAMP = ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]; // sequential blue, dark = low
const KIND_LABEL = { intraday_orders: "Intraday orders (JEPX)", vpp_dispatch: "VPP dispatch", tariff_adjustment: "Tariff adjustment",
  ppa_offer: "24/7 CFE PPA offer" };
const CLASS_ORDER = ["residential_battery", "cni_bess", "ev_depot", "heat_pump_water_heater", "dr_load"];
const CLASS_LABEL = { residential_battery: "Residential batteries", cni_bess: "C&I batteries", ev_depot: "EV depots",
  heat_pump_water_heater: "Heat pump water heaters", dr_load: "Demand response loads" };
const HEALTH_RANK = { untrusted: 0, degraded: 1, ok: 2 };
const HEALTH_TEXT = { ok: "OK", degraded: "DEGRADED", untrusted: "UNTRUSTED" };
const HEALTH_ICON = { ok: "✓", degraded: "!", untrusted: "✕" };
const GATE_TEXT = { delivered: "Delivered", in_delivery: "In delivery", closed: "Gate closed", open: "Gate open" };
const GATE_OPACITY = { delivered: 0.35, in_delivery: 0.6, closed: 0.6, open: 1 };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/* ------------------------------------------------------------------------------------------ state */
const S = {
  clock: null, health: null, kpis: null, market: null, position: null, fleet: null, selected: null, telemetry: {},
  customers: [], cfeCustomer: DEFAULT_CUSTOMER, cfe: null, ppa: null, ppaMode: false, ppaLoading: false,
  scenarios: [], actions: [], audit: [], sessionId: null, running: false, abort: null, turnNo: 0,
  reviewed: new Set(), openDetails: new Set(), actionErrors: {},
};
const charts = {};

/* ------------------------------------------------------------------------------------------ DOM helpers */
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "vars") for (const [p, val] of Object.entries(v)) n.style.setProperty(p, val);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ------------------------------------------------------------------------------------------ formatting */
const NF = {};
function num(v, d = 1) {
  if (v == null || v === "" || !Number.isFinite(Number(v))) return "n/a";
  NF[d] ??= new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const s = NF[d].format(Number(v));
  return s === `-${NF[d].format(0)}` ? NF[d].format(0) : s;
}
const signed = (v, d = 1) => (Number(v) > 0 ? `+${num(v, d)}` : num(v, d));
function jpy(v) {
  if (v == null || !Number.isFinite(Number(v))) return "n/a";
  const n = Number(v);
  return Math.abs(n) >= 1e6 ? `${num(n / 1e6, 1)}M JPY` : `${num(n, 0)} JPY`;
}
const u = (v, d, unit) => `${num(v, d)} ${unit}`;
const startOf = (range) => String(range || "").split("-")[0];
function srcShort(s) {
  // "dataset.table" -> "table"; file citations such as "desk_policy_guide.md Section 4" stay whole
  const m = /^([a-z0-9_]+)\.([a-z0-9_]+)$/i.exec(String(s));
  return m && !/^(md|txt|pdf|csv|json|ya?ml)$/i.test(m[2]) ? m[2] : String(s);
}
const asList = (x) => (Array.isArray(x) ? x : x == null ? [] : [x]);
const hhmmss = (epoch) => new Date(Number(epoch) * 1000).toLocaleTimeString("en-GB", { hour12: false });
function slotTime(slot) {
  const row = S.market?.slots?.find((r) => r.slot === Number(slot)) || S.position?.slots?.find((r) => r.slot === Number(slot));
  return row ? row.time : "";
}
function nowPos(nowIso) {
  // axis position of the desk clock on a slot axis where slot s spans [s - 0.5, s + 0.5]
  const m = /T(\d{2}):(\d{2})/.exec(nowIso || "");
  return m ? 0.5 + (Number(m[1]) * 60 + Number(m[2])) / 30 : null;
}
const nowHHMM = (iso) => (/T(\d{2}:\d{2})/.exec(iso || "") || [])[1] || "";
function humanKey(k) {
  const W = { jpy: "JPY", kwh: "kWh", mwh: "MWh", gwh: "GWh", kw: "kW", mw: "MW", pct: "%", mtd: "MTD", cfe: "CFE", ppa: "PPA",
    nfc: "NFC", id: "ID", soc: "SOC", dkw: "dKW" };
  const s = String(k).split("_").map((w) => W[w] ?? w).join(" ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function kv(key, v) {
  // label and formatted value by key suffix, units always attached
  if (typeof v === "boolean") return [humanKey(key), v ? "Yes" : "No"];
  if (Array.isArray(v)) return [humanKey(key), v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") || "none"];
  if (v && typeof v === "object") return [humanKey(key), JSON.stringify(v)];
  if (typeof v !== "number") return [humanKey(key), v == null ? "n/a" : String(v)];
  const strip = (re) => humanKey(key.replace(re, ""));
  if (/_jpy_kwh$/.test(key)) return [strip(/_jpy_kwh$/), u(v, 2, "JPY/kWh")];
  if (/_jpy$/.test(key)) return [strip(/_jpy$/), jpy(v)];
  if (/_mwh$/.test(key)) return [strip(/_mwh$/), u(v, 2, "MWh")];
  if (/_gwh$/.test(key)) return [strip(/_gwh$/), u(v, 1, "GWh")];
  if (/_kwh$/.test(key)) return [strip(/_kwh$/), u(v, 0, "kWh")];
  if (/_kw$/.test(key)) return [strip(/_kw$/), u(v, 0, "kW")];
  if (/_mw$/.test(key)) return [strip(/_mw$/), u(v, 1, "MW")];
  if (/_pct$/.test(key)) return [strip(/_pct$/), `${num(v, 1)}%`];
  if (/_days$/.test(key)) return [strip(/_days$/), `${num(v, 0)} days`];
  if (/_slots$/.test(key)) return [strip(/_slots$/), `${num(v, 0)} slots`];
  return [humanKey(key), num(v, Number.isInteger(v) ? 0 : 2)];
}

/* ------------------------------------------------------------------------------------------ API */
async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, { headers: { Accept: "application/json" }, ...opts });
  } catch (e) {
    throw new Error(`Network error: ${e.message}`);
  }
  const txt = await r.text();
  let body = null;
  try { body = txt ? JSON.parse(txt) : null; } catch { body = txt; }
  if (!r.ok) {
    const detail = body && typeof body === "object" && body.detail ? body.detail : typeof body === "string" ? body.slice(0, 160) : "";
    const err = new Error(`HTTP ${r.status}${detail ? `: ${typeof detail === "string" ? detail : JSON.stringify(detail)}` : ""}`);
    err.status = r.status;
    throw err;
  }
  return body;
}

/* ------------------------------------------------------------------------------------------ panel states */
function stateNode(kind, msg, retry) {
  return h("div", { class: `state ${kind}`, role: kind === "error" ? "alert" : "status" },
    kind === "loading" ? h("span", { class: "spinner", "aria-hidden": "true" }) : h("span", { class: "state-icon", "aria-hidden": "true" }, "!"),
    h("span", { class: "state-msg" }, msg),
    retry ? h("button", { class: "btn btn-sm", type: "button", onclick: retry }, "Retry") : null);
}
function setState(el, kind, msg, retry) { if (el) el.replaceChildren(stateNode(kind, msg, retry)); }
function overlay(id, kind, msg, retry) {
  const o = $(`#${id}`);
  if (!o) return;
  if (!kind) { o.hidden = true; o.replaceChildren(); return; }
  o.hidden = false;
  o.classList.toggle("dim", kind === "loading");
  o.replaceChildren(stateNode(kind, msg, retry));
}

let toastTimer = 0;
function toast(msg, kind = "info") {
  const t = $("#toast");
  t.hidden = false;
  t.className = `toast ${kind}`;
  t.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 7000);
}

/* ------------------------------------------------------------------------------------------ charts */
const hasECharts = () => typeof window.echarts !== "undefined";
const CSSV = (() => {
  const cs = getComputedStyle(document.documentElement);
  const g = (n, f) => cs.getPropertyValue(n).trim() || f;
  return { fg: g("--fg", "#e4e2e1"), muted: g("--fg-muted", "#a0a3a8"), border: g("--border", "#374151"), grid: "#2a2f38",
    surface: g("--surface", "#1f2020"), high: g("--surface-high", "#2a2a2a"), ok: g("--ok", "#30d158"), warn: g("--warn", "#ff9f0a"),
    crit: g("--crit", "#ff453a"), accent: g("--accent", "#a7caed"), mono: "JetBrains Mono, ui-monospace, monospace",
    sans: "Inter, system-ui, sans-serif" };
})();

function registerTheme() {
  const axis = { axisLine: { lineStyle: { color: CSSV.border } }, axisTick: { lineStyle: { color: CSSV.border } },
    axisLabel: { color: CSSV.muted, fontFamily: CSSV.mono, fontSize: 11 }, splitLine: { lineStyle: { color: CSSV.grid, width: 1 } },
    nameTextStyle: { color: CSSV.muted, fontFamily: CSSV.sans, fontSize: 11 } };
  echarts.registerTheme("desk", {
    backgroundColor: "transparent", color: [SERIES.spot, SERIES.ask, SERIES.imb, SERIES.rm],
    textStyle: { color: CSSV.fg, fontFamily: CSSV.sans }, legend: { textStyle: { color: CSSV.fg, fontSize: 12 } },
    categoryAxis: axis, valueAxis: axis, timeAxis: axis,
  });
}

const TOOLTIP = () => ({ backgroundColor: CSSV.high, borderColor: CSSV.border, borderWidth: 1, padding: [8, 10],
  textStyle: { color: CSSV.fg, fontFamily: CSSV.mono, fontSize: 12 }, extraCssText: "box-shadow:none;border-radius:0;",
  confine: true });

function chart(id) {
  if (!hasECharts()) return null;
  if (charts[id]) return charts[id];
  const el = document.getElementById(id);
  const c = echarts.init(el, "desk", { renderer: "canvas" });
  new ResizeObserver(() => c.resize()).observe(el);
  charts[id] = c;
  return c;
}
const NO_ECHARTS = "Chart library did not load from cdn.jsdelivr.net. The table view below still works.";

function tipRow(label, value, color) {
  const sw = color ? `<span class="tt-sw" style="background:${color}"></span>` : `<span class="tt-sw none"></span>`;
  return `<div class="tt-row">${sw}<span class="tt-l">${escapeHtml(label)}</span><span class="tt-v">${escapeHtml(value)}</span></div>`;
}
const tipHead = (t) => `<div class="tt-head">${escapeHtml(t)}</div>`;

/* ------------------------------------------------------------------------------------------ header */
async function loadClock() {
  try {
    S.clock = await api("/api/clock");
    renderClock();
    if (S.market) renderMarket();
    if (S.position) renderPosition();
  } catch (e) {
    $("#desk-clock").textContent = `Clock unavailable (${e.message})`;
    $("#gate-countdown").textContent = "Unavailable";
  }
}
function renderClock() {
  const c = S.clock;
  const d = new Date(`${c.date}T00:00:00Z`);
  $("#scenario-badge").textContent = `Tokyo heatwave, ${DOW[d.getUTCDay()]} ${c.date}`;
  $("#desk-clock").textContent = `${nowHHMM(c.now)} JST, slot ${c.current_slot}`;
  $("#desk-clock").title = `Slot ${c.current_slot} delivers ${c.current_slot_time}`;
  const g = c.next_gate_closure || {};
  const gc = $("#gate-countdown");
  gc.replaceChildren(
    `Slot ${g.slot} gate closes ${nowHHMM(g.gate_closure)}, ${g.minutes_left} min `,
    h("span", { class: `badge ${g.minutes_left <= 10 ? "crit" : g.minutes_left <= 30 ? "warn" : "ok"}` },
      g.minutes_left <= 30 ? "Act now" : "On track"));
  gc.title = `Delivery ${g.slot_time}. Open slots today: ${c.open_slots_today}. Imbalance cap: ${c.imbalance_cap}`;
  if (S.market) setTempBadge();
}
function setTempBadge() {
  const t = Math.max(...S.market.slots.map((r) => Number(r.temp_p50)).filter(Number.isFinite));
  if (S.clock && Number.isFinite(t)) {
    const d = new Date(`${S.clock.date}T00:00:00Z`);
    $("#scenario-badge").textContent = `Tokyo heatwave, ${DOW[d.getUTCDay()]} ${S.clock.date}, peak ${num(t, 1)} °C`;
  }
}

async function loadHealth() {
  try {
    S.health = await api("/api/health");
    const hl = S.health;
    const da = $("#backend-data"), ag = $("#backend-agents");
    da.textContent = `Data: ${hl.data_backend}`;
    da.title = `Dataset ${hl.dataset}`;
    ag.textContent = `Agents: ${hl.agent_backend === "agent_engine" ? "Agent Runtime" : hl.agent_backend}`;
    da.className = ag.className = `badge ${hl.ok ? "info" : "crit"}`;
    $("#platform-line").textContent = hl.agent_backend === "agent_engine"
      ? "Agents on Gemini Enterprise Agent Platform, Agent Runtime (formerly Vertex AI Agent Engine)."
      : "Agents run in-process with the ADK runner here; built to deploy on Gemini Enterprise Agent Platform, Agent Runtime (formerly Vertex AI Agent Engine).";
  } catch (e) {
    $("#backend-data").textContent = "Data: unreachable";
    $("#backend-data").className = "badge crit";
    $("#backend-agents").textContent = `Health check failed (${e.message})`;
    $("#backend-agents").className = "badge crit";
  }
}

/* ------------------------------------------------------------------------------------------ KPIs */
const KPI_IDS = ["kpi-spot", "kpi-reserve", "kpi-position", "kpi-vpp", "kpi-mar"];
async function loadKpis(quiet = false) {
  if (!quiet) KPI_IDS.forEach((id) => setState($(`#${id} .kpi-body`), "loading", "Loading"));
  try {
    S.kpis = await api("/api/kpis");
    renderKpis();
  } catch (e) {
    KPI_IDS.forEach((id) => setState($(`#${id} .kpi-body`), "error", `Could not load KPIs: ${e.message}`, () => loadKpis()));
  }
}
function src(list) {
  const items = asList(list);
  if (!items.length) return null;
  return h("div", { class: "kpi-src", title: items.join(", ") }, `Source: ${items.map(srcShort).join(", ")}`);
}
function kpiValue(value, unit) {
  return h("div", { class: "kpi-value" }, value, h("span", { class: "unit" }, unit));
}
function badge(kind, text, icon) {
  return h("span", { class: `badge ${kind}` }, icon ? h("span", { "aria-hidden": "true" }, icon) : null, text);
}
function renderKpis() {
  const k = S.kpis;
  const put = (id, ...kids) => $(`#${id} .kpi-body`).replaceChildren(...kids);

  const sp = k.tokyo_spot_now;
  put("kpi-spot", kpiValue(num(sp.value, 2), sp.unit),
    h("div", { class: "kpi-sub" }, `Slot ${sp.slot}, ${sp.slot_time}`),
    h("div", { class: "kpi-sub strong" }, `Evening max ${num(sp.evening_max, 2)} ${sp.unit}`), src(sp.source));

  const rm = k.reserve_margin;
  const worst = Math.min(Number(rm.now), Number(rm.min_ahead));
  const when = Number(rm.now) <= Number(rm.min_ahead) ? "now" : "ahead";
  const lvl = worst < 5 ? ["crit", `Critical ${when}, under 5%`, "✕"] : worst < 8 ? ["warn", `Warning ${when}, under 8%`, "!"] : ["ok", "Normal", "✓"];
  put("kpi-reserve", h("div", { class: "kpi-row" }, kpiValue(num(rm.now, 1), rm.unit), badge(lvl[0], lvl[1], lvl[2])),
    h("div", { class: "kpi-sub strong" }, `Minimum ahead ${num(rm.min_ahead, 1)}${rm.unit} at ${rm.min_slot_time} (slot ${rm.min_slot})`),
    src(rm.source));

  const np = k.net_open_position_next4;
  const v = Number(np.value);
  const dir = v < -0.05 ? ["crit", "Short", "▼"] : v > 0.05 ? ["info", "Long", "▲"] : ["ok", "Flat", "✓"];
  const slots = asList(np.slots);
  const cover = Number(np.sandbox_cover_mwh) || 0;
  put("kpi-position", h("div", { class: "kpi-row" }, kpiValue(signed(np.value, 1), np.unit), badge(dir[0], dir[1], dir[2])),
    h("div", { class: "kpi-sub" }, slots.length ? `Next ${slots.length} open slots, ${slots[0]} to ${slots[slots.length - 1]}. Negative means short.` : "No open slots"),
    h("div", { class: `kpi-sub ${cover > 0 ? "good" : ""}` }, cover > 0
      ? `Sandbox cover ${signed(cover, 1)} ${np.unit} approved`
      : `Sandbox cover ${num(cover, 1)} ${np.unit}, nothing approved yet`),
    src(np.source));

  const vp = k.vpp_available;
  const untrusted = asList(vp.untrusted);
  put("kpi-vpp", kpiValue(num(vp.value, 1), vp.unit),
    h("div", { class: "kpi-sub" }, `Slot ${vp.slot}. ${vp.clusters_trusted} of ${vp.clusters_total} clusters trusted. dKW committed ${num(vp.committed_dkw_mw, 1)} MW`),
    untrusted.length
      ? h("div", { class: "kpi-sub" }, badge("crit", `Untrusted: ${untrusted.length}`, "✕"), " ",
        ...untrusted.map((id) => h("button", { class: "linkish mono", type: "button", onclick: () => selectCluster(id, true),
          "aria-label": `Inspect untrusted cluster ${id}` }, id)))
      : h("div", { class: "kpi-sub good" }, "All clusters trusted"),
    src(vp.source));

  const mr = k.margin_at_risk;
  put("kpi-mar", kpiValue(jpy(mr.value).replace(/ JPY$/, ""), "JPY"),
    h("div", { class: "kpi-sub strong" }, `at +${mr.shock_pct}% spot, rest of August`),
    h("div", { class: "kpi-sub" }, `Hedge cover ${num(mr.hedge_cover_pct, 1)}%. Expected margin before shock ${jpy(mr.margin_before)}`),
    h("div", { class: "kpi-sub" }, `Period ${mr.period}`), src(mr.source));
}

/* ------------------------------------------------------------------------------------------ market chart */
async function loadMarket(quiet = false) {
  if (!quiet) overlay("market-overlay", "loading", "Loading market data");
  try {
    S.market = await api("/api/market");
    setTempBadge();
    renderMarket();
    if ($("#market-tv").open) renderMarketTable();
    if (S.fleet) renderFleetSub();
  } catch (e) {
    overlay("market-overlay", "error", `Could not load market data: ${e.message}`, () => loadMarket());
  }
}
function slotAxis(gridIndex, rows, showLabels, step = 4) {
  const labelSlots = rows.map((r) => r.slot).filter((s) => (s - 1) % step === 0);
  const startBySlot = Object.fromEntries(rows.map((r) => [r.slot, startOf(r.time)]));
  const first = rows[0].slot, last = rows[rows.length - 1].slot;
  return { type: "value", gridIndex, min: first - 0.5, max: last + 0.5, interval: step, splitLine: { show: false },
    axisLabel: { show: showLabels, customValues: labelSlots, formatter: (v) => startBySlot[Math.round(v)] && Math.abs(v - Math.round(v)) < 1e-6 ? startBySlot[Math.round(v)] : "" },
    axisTick: { show: showLabels, customValues: labelSlots }, axisPointer: { label: { show: false } } };
}
function runs(rows, pred) {
  const out = [];
  let cur = null;
  for (const r of rows) {
    if (pred(r)) { if (cur) cur[1] = r.slot; else cur = [r.slot, r.slot]; } else if (cur) { out.push(cur); cur = null; }
  }
  if (cur) out.push(cur);
  return out;
}
function renderMarket() {
  const rows = S.market.slots;
  $("#market-sub").textContent = `${S.market.date}. Spot, intraday best ask and imbalance forecast (p10 to p90 band), reserve margin below. Source: ${asList(S.market.source).map(srcShort).join(", ")}`;
  const c = chart("market-chart");
  if (!c) { overlay("market-overlay", "error", NO_ECHARTS); return; }
  overlay("market-overlay", null);
  const nowIso = S.clock?.now || S.market.now;
  const np = nowPos(nowIso);
  const firstOpen = rows.find((r) => r.gate_status === "open");
  const gateSlot = S.clock?.next_gate_closure?.slot ?? firstOpen?.slot;
  const gateTime = nowHHMM(S.clock?.next_gate_closure?.gate_closure);
  const scarcity = runs(rows, (r) => r.scarcity);
  const band = rows.filter((r) => r.is_forecast && r.imbalance_p10 != null && r.imbalance_p90 != null);
  const pts = (key) => rows.map((r) => [r.slot, r[key]]);
  const vLines = (withLabels) => {
    const d = [];
    if (np != null) d.push({ xAxis: np, lineStyle: { color: CSSV.fg, type: "solid", width: 1 },
      label: { show: withLabels, formatter: `Now ${nowHHMM(nowIso)}`, position: "end", color: CSSV.fg, fontFamily: CSSV.mono, fontSize: 11 } });
    if (gateSlot) d.push({ xAxis: gateSlot - 0.5, lineStyle: { color: CSSV.warn, type: "dashed", width: 1 },
      label: { show: withLabels, formatter: `Gate open from slot ${gateSlot}${gateTime ? `, closes ${gateTime}` : ""}`, position: "start",
        color: CSSV.fg, fontFamily: CSSV.mono, fontSize: 11, backgroundColor: CSSV.surface, padding: [2, 4] } });
    return { symbol: "none", silent: true, data: d };
  };
  const scarcityArea = (withLabels) => ({ silent: true, itemStyle: { color: "rgba(255,69,58,0.08)" },
    label: { show: withLabels, position: "insideTopRight", color: CSSV.muted, fontFamily: CSSV.mono, fontSize: 10, formatter: "Scarcity" },
    data: scarcity.map(([a, b]) => [{ xAxis: a - 0.5 }, { xAxis: b + 0.5 }]) });
  const line = (name, key, color, extra = {}) => ({ name, type: "line", xAxisIndex: 0, yAxisIndex: 0, data: pts(key), showSymbol: false,
    symbolSize: 8, lineStyle: { width: 2, color, cap: "round", join: "round" }, itemStyle: { color }, emphasis: { disabled: true }, ...extra });

  c.setOption({
    aria: { enabled: true },
    animationDuration: 400,
    legend: { top: 0, left: 0, itemWidth: 18, itemHeight: 8, textStyle: { color: CSSV.fg, fontSize: 12 },
      data: [{ name: "Tokyo spot", icon: "roundRect" }, { name: "Intraday best ask", icon: "roundRect" },
        { name: "Imbalance (p50)", icon: "roundRect" }, { name: "Imbalance p10 to p90", icon: "rect" }, { name: "Reserve margin", icon: "roundRect" }] },
    grid: [{ left: 52, right: 60, top: 56, bottom: 142 }, { left: 52, right: 60, bottom: 30, height: 72 }],
    axisPointer: { link: [{ xAxisIndex: "all" }], lineStyle: { color: CSSV.muted } },
    xAxis: [slotAxis(0, rows, false, 4), slotAxis(1, rows, true, 4)],
    yAxis: [
      { type: "value", gridIndex: 0, name: "JPY/kWh", nameLocation: "end", nameGap: 12, min: 0, axisLabel: { formatter: (v) => num(v, 0) } },
      { type: "value", gridIndex: 1, name: "Reserve %", nameLocation: "end", nameGap: 8, position: "right", min: 0, splitNumber: 2,
        axisLabel: { formatter: (v) => `${num(v, 0)}%` } },
    ],
    tooltip: { ...TOOLTIP(), trigger: "axis", axisPointer: { type: "line" }, formatter: (ps) => marketTip(ps) },
    series: [
      line("Tokyo spot", "tokyo_spot", SERIES.spot, { z: 5, markLine: vLines(true), markArea: scarcityArea(true) }),
      line("Intraday best ask", "intraday_ask", SERIES.ask),
      line("Imbalance (p50)", "imbalance", SERIES.imb),
      { name: "Imbalance p10 to p90", type: "custom", xAxisIndex: 0, yAxisIndex: 0, silent: true, z: 1, clip: true,
        itemStyle: { color: SERIES.imb }, encode: { x: 0, y: [1, 2] },
        data: band.map((r) => [r.slot, Number(r.imbalance_p10), Number(r.imbalance_p90)]),
        renderItem: (params, api) => {
          if (params.dataIndex !== 0 || band.length < 2) return null;
          const top = band.map((r) => api.coord([r.slot, Number(r.imbalance_p90)]));
          const bottom = band.map((r) => api.coord([r.slot, Number(r.imbalance_p10)])).reverse();
          return { type: "polygon", silent: true, shape: { points: top.concat(bottom) }, style: { fill: SERIES.imb, opacity: 0.18 } };
        } },
      { name: "Reserve margin", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: pts("reserve_margin"), showSymbol: false, symbolSize: 8,
        lineStyle: { width: 2, color: SERIES.rm }, itemStyle: { color: SERIES.rm }, emphasis: { disabled: true },
        markLine: { symbol: "none", silent: true, data: [
          { yAxis: 8, lineStyle: { color: CSSV.warn, type: "dashed", width: 1 },
            label: { formatter: "8% warning", position: "insideStartTop", color: CSSV.muted, fontSize: 10, fontFamily: CSSV.mono } },
          { yAxis: 5, lineStyle: { color: CSSV.crit, type: "dashed", width: 1 },
            label: { formatter: "5% critical", position: "insideStartBottom", color: CSSV.muted, fontSize: 10, fontFamily: CSSV.mono } },
          ...vLines(false).data] },
        markArea: scarcityArea(false) },
    ],
  }, true);
}
function marketTip(ps) {
  if (!ps?.length) return "";
  const slot = Math.round(ps[0].axisValue ?? ps[0].value?.[0]);
  const r = S.market.slots.find((x) => x.slot === slot);
  if (!r) return "";
  return tipHead(`Slot ${r.slot}, ${r.time}`) +
    `<div class="tt-sub">${escapeHtml(GATE_TEXT[r.gate_status] || r.gate_status)}${r.is_forecast ? ", forecast" : ", actual"}${r.scarcity ? ", scarcity" : ""}</div>` +
    tipRow("Tokyo spot", u(r.tokyo_spot, 2, "JPY/kWh"), SERIES.spot) +
    tipRow("System spot", u(r.system_spot, 2, "JPY/kWh")) +
    tipRow("Intraday best ask", u(r.intraday_ask, 2, "JPY/kWh"), SERIES.ask) +
    tipRow("Imbalance p50", u(r.imbalance, 2, "JPY/kWh"), SERIES.imb) +
    (r.is_forecast ? tipRow("Imbalance p10 to p90", `${num(r.imbalance_p10, 2)} to ${num(r.imbalance_p90, 2)} JPY/kWh`) : "") +
    tipRow("Reserve margin", `${num(r.reserve_margin, 1)}%`, SERIES.rm) +
    tipRow("Temperature p50", `${num(r.temp_p50, 1)} °C`);
}
function tableFrom(headers, rows, opts = {}) {
  return h("table", { class: `data ${opts.cls || ""}` },
    h("thead", null, h("tr", null, headers.map((x, i) => h("th", { class: opts.num?.includes(i) ? "num" : null, scope: "col" }, x)))),
    h("tbody", null, rows.map((r) => h("tr", { class: r.cls || null }, (r.cells || r).map((x, i) =>
      h("td", { class: opts.num?.includes(i) ? "num" : null }, x instanceof Node ? x : String(x ?? "")))))));
}
function renderMarketTable() {
  if (!S.market) return;
  $("#market-table").replaceChildren(tableFrom(
    ["Slot", "Time", "Gate", "Tokyo spot JPY/kWh", "Intraday ask JPY/kWh", "Imbalance p50 JPY/kWh", "p10 to p90 JPY/kWh", "Reserve margin %", "Scarcity"],
    S.market.slots.map((r) => [r.slot, r.time, GATE_TEXT[r.gate_status] || r.gate_status, num(r.tokyo_spot, 2), num(r.intraday_ask, 2),
      num(r.imbalance, 2), r.is_forecast ? `${num(r.imbalance_p10, 2)} to ${num(r.imbalance_p90, 2)}` : "actual", num(r.reserve_margin, 1),
      r.scarcity ? "Yes" : "No"]), { num: [0, 3, 4, 5, 7] }));
}

/* ------------------------------------------------------------------------------------------ position chart */
async function loadPosition(quiet = false) {
  if (!quiet) overlay("position-overlay", "loading", "Loading position");
  try {
    S.position = await api("/api/position");
    renderPosition();
    if ($("#position-tv").open) renderPositionTable();
  } catch (e) {
    overlay("position-overlay", "error", `Could not load position: ${e.message}`, () => loadPosition());
  }
}
const SHORT_DECAL = { symbol: "rect", symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: Math.PI / 4, color: "rgba(10,10,10,0.55)" };
function renderPosition() {
  const rows = S.position.slots;
  const open = rows.filter((r) => r.gate_status === "open");
  const netOpen = open.reduce((a, r) => a + Number(r.open_position || 0), 0);
  const worst = open.reduce((m, r) => (m == null || r.open_position < m.open_position ? r : m), null);
  const cover = rows.reduce((a, r) => a + Number(r.sandbox_cover || 0), 0);
  $("#position-sub").textContent = open.length
    ? `Open slots ${open[0].slot} to ${open[open.length - 1].slot}: net ${signed(netOpen, 1)} MWh. Largest short ${num(worst.open_position, 1)} MWh at ${startOf(worst.time)} (slot ${worst.slot}).${cover > 0 ? ` Sandbox cover ${signed(cover, 1)} MWh included.` : ""}`
    : "No open slots";
  const c = chart("position-chart");
  if (!c) { overlay("position-overlay", "error", NO_ECHARTS); return; }
  overlay("position-overlay", null);
  const nowIso = S.clock?.now || S.position.now;
  const np = nowPos(nowIso);
  const openRuns = runs(rows, (r) => r.gate_status === "open");
  const deliveredRuns = runs(rows, (r) => r.gate_status === "delivered");
  const barItem = (r, isShort) => {
    const v = Number(r.open_position);
    const show = isShort ? v < 0 : v >= 0;
    return { value: [r.slot, show ? v : null], itemStyle: { opacity: GATE_OPACITY[r.gate_status] ?? 1 },
      label: isShort && worst && r.slot === worst.slot && v < 0
        ? { show: true, position: "bottom", formatter: `Short ${num(-v, 1)}`, color: CSSV.fg, fontFamily: CSSV.mono, fontSize: 10, distance: 4 }
        : undefined };
  };
  const dline = (name, key, color, type = "solid") => ({ name, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, symbolSize: 8,
    connectNulls: false, data: rows.map((r) => [r.slot, r[key]]), lineStyle: { width: 2, color, type }, itemStyle: { color }, emphasis: { disabled: true } });
  c.setOption({
    aria: { enabled: true, decal: { show: true } },
    animationDuration: 400,
    legend: { top: 0, left: 0, itemWidth: 16, itemHeight: 8, itemGap: 10, textStyle: { color: CSSV.fg, fontSize: 11 },
      data: ["DA plan", "Latest forecast", "Actual", "Short", "Long"] },
    grid: [{ left: 48, right: 12, top: 56, height: 104 }, { left: 48, right: 12, top: 196, bottom: 30 }],
    axisPointer: { link: [{ xAxisIndex: "all" }], lineStyle: { color: CSSV.muted } },
    xAxis: [slotAxis(0, rows, false, 8), slotAxis(1, rows, true, 8)],
    yAxis: [
      { type: "value", gridIndex: 0, name: "Demand MWh", nameGap: 10, scale: true, splitNumber: 3, axisLabel: { formatter: (v) => num(v, 0) } },
      { type: "value", gridIndex: 1, name: "Open position MWh", nameGap: 10, splitNumber: 4, axisLabel: { formatter: (v) => num(v, 0) } },
    ],
    tooltip: { ...TOOLTIP(), trigger: "axis", axisPointer: { type: "line" }, formatter: (ps) => positionTip(ps) },
    series: [
      dline("DA plan", "demand_da", SERIES.da, "dashed"),
      dline("Latest forecast", "demand_latest", SERIES.latest),
      dline("Actual", "demand_actual", SERIES.actual),
      { name: "Short", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barWidth: "70%", barGap: "-100%",
        itemStyle: { color: SERIES.short, borderRadius: [0, 0, 2, 2], decal: SHORT_DECAL }, emphasis: { disabled: true },
        data: rows.map((r) => barItem(r, true)),
        markArea: { silent: true, itemStyle: { color: "rgba(167,202,237,0.06)" },
          label: { position: "insideTop", color: CSSV.muted, fontFamily: CSSV.mono, fontSize: 10 },
          data: [...openRuns.map(([a, b]) => [{ xAxis: a - 0.5, name: "Gate open" }, { xAxis: b + 0.5 }]),
            ...deliveredRuns.map(([a, b]) => [{ xAxis: a - 0.5, name: "Delivered", itemStyle: { color: "rgba(0,0,0,0)" } }, { xAxis: b + 0.5 }])] },
        markLine: np == null ? undefined : { symbol: "none", silent: true, data: [{ xAxis: np, lineStyle: { color: CSSV.fg, width: 1, type: "solid" },
          label: { formatter: `Now ${nowHHMM(nowIso)}`, position: "end", color: CSSV.fg, fontFamily: CSSV.mono, fontSize: 10 } }] } },
      { name: "Long", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barWidth: "70%", barGap: "-100%",
        itemStyle: { color: SERIES.long, borderRadius: [2, 2, 0, 0], decal: { symbol: "none" } }, emphasis: { disabled: true },
        data: rows.map((r) => barItem(r, false)) },
    ],
  }, true);
}
function positionTip(ps) {
  if (!ps?.length) return "";
  const slot = Math.round(ps[0].axisValue ?? ps[0].value?.[0]);
  const r = S.position.slots.find((x) => x.slot === slot);
  if (!r) return "";
  const v = Number(r.open_position);
  return tipHead(`Slot ${r.slot}, ${r.time}`) + `<div class="tt-sub">${escapeHtml(GATE_TEXT[r.gate_status] || r.gate_status)}</div>` +
    tipRow("DA plan", u(r.demand_da, 1, "MWh"), SERIES.da) + tipRow("Latest forecast", u(r.demand_latest, 1, "MWh"), SERIES.latest) +
    tipRow("Actual", r.demand_actual == null ? "not yet metered" : u(r.demand_actual, 1, "MWh"), SERIES.actual) +
    tipRow("Bilateral", u(r.bilateral, 1, "MWh")) + tipRow("Day-ahead spot", u(r.spot, 1, "MWh")) + tipRow("Intraday", u(r.intraday, 1, "MWh")) +
    tipRow("Sandbox cover", u(r.sandbox_cover, 2, "MWh")) +
    tipRow("Open position", `${signed(v, 2)} MWh ${v < -0.05 ? "(short)" : v > 0.05 ? "(long)" : "(flat)"}`, v < 0 ? SERIES.short : SERIES.long);
}
function renderPositionTable() {
  if (!S.position) return;
  $("#position-table").replaceChildren(tableFrom(
    ["Slot", "Time", "Gate", "DA plan MWh", "Latest MWh", "Actual MWh", "Sandbox cover MWh", "Open position MWh"],
    S.position.slots.map((r) => ({ cls: r.open_position < -0.05 ? "row-short" : null, cells: [r.slot, r.time, GATE_TEXT[r.gate_status] || r.gate_status,
      num(r.demand_da, 1), num(r.demand_latest, 1), r.demand_actual == null ? "n/a" : num(r.demand_actual, 1), num(r.sandbox_cover, 2),
      `${signed(r.open_position, 2)}${r.open_position < -0.05 ? " short" : ""}`] })), { num: [0, 3, 4, 5, 6, 7] }));
}

/* ------------------------------------------------------------------------------------------ VPP fleet */
async function loadFleet() {
  setState($("#fleet-groups"), "loading", "Loading VPP fleet");
  try {
    S.fleet = await api("/api/vpp/fleet");
    renderFleet();
    const cl = S.fleet.clusters;
    const first = [...cl].sort((a, b) => HEALTH_RANK[a.health] - HEALTH_RANK[b.health])[0];
    if (first) selectCluster(S.selected && cl.some((c) => c.cluster_id === S.selected) ? S.selected : first.cluster_id, false);
  } catch (e) {
    setState($("#fleet-groups"), "error", `Could not load VPP fleet: ${e.message}`, loadFleet);
    $("#fleet-sub").textContent = "Fleet unavailable";
  }
}
function renderFleetSub() {
  const f = S.fleet;
  const t = slotTime(f.slot);
  $("#fleet-sub").textContent = `${f.clusters.length} clusters, state for slot ${f.slot}${t ? ` (${t})` : ""}, snapshot ${nowHHMM(f.snapshot)} JST`;
}
function renderFleet() {
  const f = S.fleet;
  renderFleetSub();
  const bad = f.clusters.filter((c) => c.health !== "ok").sort((a, b) => HEALTH_RANK[a.health] - HEALTH_RANK[b.health]);
  $("#fleet-alert").replaceChildren(bad.length
    ? h("div", { class: "alert" }, h("span", { class: "caps" }, "Needs attention"),
      h("ul", { class: "alert-list" }, bad.map((c) => h("li", null,
        h("button", { class: `alert-item ${c.health}`, type: "button", onclick: () => selectCluster(c.cluster_id, true) },
          h("span", { class: `badge ${c.health === "untrusted" ? "crit" : "warn"}` }, h("span", { "aria-hidden": "true" }, HEALTH_ICON[c.health]), HEALTH_TEXT[c.health]),
          h("span", { class: "mono strong" }, c.cluster_id),
          h("span", { class: "alert-reason" }, asList(c.reasons).map((x) => String(x).split(":")[0]).join(", ") || "check telemetry"),
          c.committed_dkw_kw > 0 ? h("span", { class: "dkw-tag" }, `dKW ${num(c.committed_dkw_kw, 0)} kW at risk`) : null)))))
    : h("div", { class: "alert ok" }, badge("ok", "All clusters healthy", "✓")));

  const groups = CLASS_ORDER.filter((k) => f.clusters.some((c) => c.asset_class === k))
    .concat([...new Set(f.clusters.map((c) => c.asset_class))].filter((k) => !CLASS_ORDER.includes(k)));
  $("#fleet-groups").replaceChildren(...groups.map((cls) => {
    const list = f.clusters.filter((c) => c.asset_class === cls)
      .sort((a, b) => HEALTH_RANK[a.health] - HEALTH_RANK[b.health] || a.cluster_id.localeCompare(b.cluster_id));
    const counts = { ok: 0, degraded: 0, untrusted: 0 };
    list.forEach((c) => { counts[c.health] = (counts[c.health] || 0) + 1; });
    const disp = list.reduce((a, c) => a + Number(c.dispatchable_kw || 0), 0);
    const socs = list.map((c) => c.soc_pct).filter((x) => x != null);
    const dkw = list.filter((c) => c.committed_dkw_kw > 0).length;
    const parts = [`${list.length} clusters`, `${counts.ok} OK`];
    if (counts.degraded) parts.push(`${counts.degraded} degraded`);
    if (counts.untrusted) parts.push(`${counts.untrusted} untrusted`);
    parts.push(`${num(disp / 1000, 1)} MW dispatchable`);
    if (socs.length) parts.push(`average SOC ${num(socs.reduce((a, b) => a + b, 0) / socs.length, 0)}%`);
    if (dkw) parts.push(`${dkw} with dKW`);
    return h("section", { class: "fgroup", "aria-label": CLASS_LABEL[cls] || humanKey(cls) },
      h("div", { class: "fgroup-head" }, h("h3", null, CLASS_LABEL[cls] || humanKey(cls)), h("span", { class: "sub" }, parts.join(" · "))),
      h("div", { class: "tiles" }, list.map(tileFor)));
  }));
  markSelectedTile();
}
function tileFor(c) {
  const soc = c.soc_pct == null ? "SOC n/a" : `SOC ${num(c.soc_pct, 0)}%`;
  const dkw = c.committed_dkw_kw > 0;
  return h("button", { class: `tile ${c.health}`, type: "button", "data-id": c.cluster_id, "aria-pressed": "false",
    "aria-label": `${c.cluster_id}, ${HEALTH_TEXT[c.health]}, ${soc}, dispatchable ${num(c.dispatchable_kw, 0)} kW${dkw ? `, dKW committed ${num(c.committed_dkw_kw, 0)} kW` : ""}`,
    onclick: () => selectCluster(c.cluster_id, false) },
  h("span", { class: "t-top" }, h("span", { class: "t-id" }, c.cluster_id.replace(/^VPP-/, "")), dkw ? h("span", { class: "t-dkw", title: `dKW committed ${num(c.committed_dkw_kw, 0)} kW` }, "dKW") : null),
  h("span", { class: "t-health" }, HEALTH_TEXT[c.health]),
  h("span", { class: "t-num" }, soc),
  h("span", { class: "t-num" }, `${num(c.dispatchable_kw, 0)} kW`));
}
function markSelectedTile() {
  document.querySelectorAll("#fleet-groups .tile").forEach((t) => t.setAttribute("aria-pressed", String(t.dataset.id === S.selected)));
}
async function selectCluster(id, scroll) {
  if (!S.fleet) return;
  const c = S.fleet.clusters.find((x) => x.cluster_id === id);
  if (!c) return;
  S.selected = id;
  markSelectedTile();
  renderClusterDetail(c);
  if (scroll) $("#fleet").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  if (S.telemetry[id]) { renderTelemetry(c, S.telemetry[id]); return; }
  overlay("tele-overlay", "loading", `Loading telemetry for ${id}`);
  try {
    const t = await api(`/api/vpp/telemetry/${encodeURIComponent(id)}`);
    S.telemetry[id] = t;
    if (S.selected === id) renderTelemetry(c, t);
  } catch (e) {
    if (S.selected === id) overlay("tele-overlay", "error", `Telemetry unavailable: ${e.message}`, () => selectCluster(id, false));
  }
}
function renderClusterDetail(c) {
  const kind = c.health === "untrusted" ? "crit" : c.health === "degraded" ? "warn" : "ok";
  $("#cd-head").replaceChildren(
    h("div", { class: "cd-title" }, h("span", { class: "mono strong" }, c.cluster_id), h("span", { class: "sub" }, c.name)),
    badge(kind, HEALTH_TEXT[c.health], HEALTH_ICON[c.health]));
  $("#cd-reasons").replaceChildren(...(asList(c.reasons).length
    ? asList(c.reasons).map((r) => h("li", { class: kind }, h("span", { "aria-hidden": "true" }, `${HEALTH_ICON[c.health]} `), String(r)))
    : [h("li", { class: "ok" }, h("span", { "aria-hidden": "true" }, "✓ "), "Telemetry fresh and moving")]));
  const rows = [
    ["State of charge", c.soc_pct == null ? "n/a (no storage)" : `${num(c.soc_pct, 1)}%`],
    ["Dispatchable", `${u(c.dispatchable_kw, 0, "kW")}, ${u(c.dispatchable_kwh, 0, "kWh")}`],
    ["Available", `${u(c.available_kw, 0, "kW")}, ${u(c.available_kwh, 0, "kWh")}`],
    ["Capacity", `${u(c.capacity_kw, 0, "kW")}, ${u(c.energy_kwh, 0, "kWh")}`],
    ["dKW committed", c.committed_dkw_kw > 0 ? `${u(c.committed_dkw_kw, 0, "kW")} (${asList(c.commitments).join(", ")})` : "None"],
    ["Devices online", `${num(c.online_devices, 0)} of ${num(c.device_count, 0)}`],
    ["Last seen", String(c.last_seen || "n/a").replace("T", " ")],
    ["Response time", u(c.response_time_s, 0, "s")],
    ["Dispatch cost", u(c.dispatch_cost_jpy_kwh, 2, "JPY/kWh")],
  ];
  $("#cd-stats").replaceChildren(...rows.flatMap(([k, v]) => [h("dt", null, k), h("dd", { class: "mono" }, v)]));
}
function renderTelemetry(c, t) {
  const ser = asList(t.series);
  const ch = chart("tele-chart");
  if (!ch) { overlay("tele-overlay", "error", NO_ECHARTS); return; }
  if (!ser.length) { ch.clear(); overlay("tele-overlay", "error", `No telemetry rows for ${c.cluster_id}`); return; }
  overlay("tele-overlay", null);
  const x = ser.map((r) => nowHHMM(r.timestamp));
  const y = ser.map((r) => r.soc_pct);
  // longest trailing run with an unchanged SOC reading (frozen telemetry)
  let k = y.length - 1;
  while (k > 0 && y[k] != null && y[k - 1] === y[k]) k--;
  const flat = y[y.length - 1] != null && y.length - 1 - k >= 3 ? [k, y.length - 1] : null;
  const hasSoc = y.some((v) => v != null);
  ch.setOption({
    aria: { enabled: true },
    animation: false,
    grid: { left: 40, right: 12, top: 18, bottom: 22 },
    xAxis: { type: "category", data: x, boundaryGap: false, axisLabel: { interval: Math.max(0, Math.floor(x.length / 5) - 1), fontSize: 10 } },
    yAxis: hasSoc
      ? { type: "value", min: 0, max: 100, splitNumber: 2, name: "SOC %", nameGap: 6, nameTextStyle: { fontSize: 10, align: "left" }, axisLabel: { fontSize: 10, formatter: (v) => `${v}%` } }
      : { type: "value", scale: true, splitNumber: 2, name: "Available kW", nameGap: 6, nameTextStyle: { fontSize: 10, align: "left" }, axisLabel: { fontSize: 10, formatter: (v) => num(v, 0) } },
    tooltip: { ...TOOLTIP(), trigger: "axis", formatter: (ps) => {
      const r = ser[ps[0].dataIndex];
      return tipHead(`${c.cluster_id} at ${String(r.timestamp).replace("T", " ")}`) +
        tipRow("SOC", r.soc_pct == null ? "n/a" : `${num(r.soc_pct, 1)}%`, SERIES.soc) + tipRow("Available", u(r.available_kw, 0, "kW")) +
        tipRow("Last heartbeat", String(r.last_seen || "n/a").replace("T", " "));
    } },
    series: [{ type: "line", data: hasSoc ? y : ser.map((r) => r.available_kw), showSymbol: false, symbolSize: 8,
      lineStyle: { width: 2, color: c.health === "untrusted" ? SERIES.short : SERIES.soc }, itemStyle: { color: c.health === "untrusted" ? SERIES.short : SERIES.soc },
      areaStyle: { opacity: 0.1 }, emphasis: { disabled: true },
      markArea: flat && hasSoc ? { silent: true, itemStyle: { color: "rgba(255,69,58,0.12)" },
        label: { formatter: `Flat since ${x[flat[0]]}`, position: "insideTop", color: CSSV.fg, fontFamily: CSSV.mono, fontSize: 10 },
        data: [[{ xAxis: x[flat[0]] }, { xAxis: x[flat[1]] }]] } : undefined }],
  }, true);
}

/* ------------------------------------------------------------------------------------------ CFE */
async function loadCfe() {
  overlay("cfe-overlay", "loading", "Loading CFE matching");
  const [cust, heat] = await Promise.allSettled([api("/api/cfe/customers"), api(cfeUrl(S.cfeCustomer))]);
  const sel = $("#cfe-customer");
  if (cust.status === "fulfilled") {
    S.customers = asList(cust.value?.customers);
    sel.replaceChildren(...S.customers.map((c) => h("option", { value: c.customer_id }, `${c.name} (${c.customer_id})`)));
    if (!S.customers.some((c) => c.customer_id === S.cfeCustomer) && S.customers[0]) S.cfeCustomer = S.customers[0].customer_id;
    sel.value = S.cfeCustomer;
  } else {
    sel.replaceChildren(h("option", null, "Customers unavailable"));
    toast(`CFE customers could not load: ${cust.reason.message}`, "crit");
  }
  if (heat.status === "fulfilled") {
    S.cfe = heat.value;
    if (!S.ppaMode) renderCfe();
  } else {
    $("#cfe-summary").replaceChildren();
    overlay("cfe-overlay", "error", `Could not load CFE heatmap: ${heat.reason.message}`, loadCfe);
  }
}
function cfeUrl(id) {
  // month follows the desk clock; before the clock loads the server default month applies
  const month = (S.clock?.date || S.health?.now || "").slice(0, 7);
  return `/api/cfe/heatmap?customer_id=${encodeURIComponent(id)}${month ? `&month=${encodeURIComponent(month)}` : ""}`;
}
async function loadCfeHeatmap(id) {
  S.cfeCustomer = id;
  overlay("cfe-overlay", "loading", "Loading CFE matching");
  try {
    const r = await api(cfeUrl(id));
    if (S.cfeCustomer !== id) return;
    S.cfe = r;
    if (!S.ppaMode) renderCfe();
  } catch (e) {
    if (!S.ppaMode) { $("#cfe-summary").replaceChildren(); overlay("cfe-overlay", "error", `Could not load CFE heatmap: ${e.message}`, () => loadCfeHeatmap(id)); }
  }
}
function meter(label, value, note, emphasis) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return h("div", { class: `meter ${emphasis || ""}` },
    h("div", { class: "meter-top" }, h("span", { class: "meter-label" }, label), h("span", { class: "meter-value mono" }, `${num(value, 1)}%`)),
    h("div", { class: "meter-track", role: "presentation" }, h("div", { class: "meter-fill", vars: { "--w": `${pct}%` } })),
    note ? h("div", { class: "meter-note" }, note) : null);
}
function renderCfe() {
  const r = S.cfe, sc = r.score || {};
  const cust = S.customers.find((c) => c.customer_id === r.customer_id);
  $("#cfe-sub").textContent = `${sc.name || cust?.name || r.customer_id}, ${humanKey(cust?.segment || "")}, ${humanKey(sc.cfe_product || cust?.cfe_product || "")} product, ${cust ? u(cust.contracted_kw, 0, "kW") + " contracted" : ""}`.replace(/, ,/g, ",");
  const weak = asList(sc.weakest_hours_of_day).map((w) => `${String(w.hour).padStart(2, "0")}:00 (${num(w.matched_pct, 1)}%)`).join(", ");
  $("#cfe-summary").replaceChildren(
    h("div", { class: "meters" },
      meter("Annual-style volumetric match", sc.annual_style_volumetric_match_pct, "What a volumetric certificate claim says"),
      meter("Contracted clean, matched hour by hour", sc.contracted_hourly_matched_pct, "Excess in one hour never offsets another"),
      meter("24/7 CFE score", sc.cfe_score_24x7_pct, `Includes grid CFE share ${num(sc.grid_cfe_contribution_pct, 1)}%`, "hero")),
    h("p", { class: "cfe-facts" },
      `${sc.period || r.month}, ${num(sc.hours, 0)} hours. Load ${u(sc.load_mwh, 1, "MWh")}, contracted clean ${u(sc.contracted_clean_mwh, 1, "MWh")}. `,
      `Excess clean not counted ${u(sc.excess_clean_mwh_not_counted, 1, "MWh")}. ${num(sc.hours_below_50pct_matched, 0)} hours below 50% matched.`,
      weak ? ` Weakest hours: ${weak}.` : "",
      asList(sc.certificate_ledger_findings).length ? ` Ledger findings: ${asList(sc.certificate_ledger_findings).length}.` : ""));
  $("#cfe-key").textContent = `Cell = one hour, color = share of load matched by contracted clean supply that hour. Method: ${sc.method || "n/a"}`;
  const c = chart("cfe-chart");
  if (!c) { overlay("cfe-overlay", "error", NO_ECHARTS); return; }
  overlay("cfe-overlay", null);
  const cells = asList(r.cells);
  const dates = [...new Set(cells.map((x) => x.date))].sort();
  const hours = [...new Set(cells.map((x) => Number(x.hour)))].sort((a, b) => a - b);
  const data = cells.map((x) => [hours.indexOf(Number(x.hour)), dates.indexOf(x.date), x.matched_pct ?? "-"]);
  c.setOption(heatOption({
    x: hours.map((hh) => `${String(hh).padStart(2, "0")}:00`), y: dates.map((d) => d.slice(5)), data, xName: "Hour of day (JST)",
    tip: (p) => tipHead(`${dates[p.value[1]]}, ${String(hours[p.value[0]]).padStart(2, "0")}:00`) +
      tipRow("Matched", p.value[2] === "-" ? "n/a" : `${num(p.value[2], 1)}%`),
  }), true);
}
function heatOption({ x, y, data, xName, tip }) {
  return {
    aria: { enabled: true },
    animation: false,
    grid: { left: 52, right: 12, top: 8, bottom: 78 },
    xAxis: { type: "category", data: x, name: xName, nameLocation: "middle", nameGap: 28, splitArea: { show: false },
      axisLabel: { interval: 2, fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "category", data: y, inverse: true, axisLabel: { fontSize: 10 }, axisTick: { show: false }, splitArea: { show: false } },
    visualMap: { type: "continuous", min: 0, max: 100, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 12,
      itemHeight: 220, text: ["100% matched", "0%"], textGap: 8, textStyle: { color: CSSV.muted, fontFamily: CSSV.mono, fontSize: 11 },
      inRange: { color: RAMP } },
    tooltip: { ...TOOLTIP(), trigger: "item", formatter: tip },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: CSSV.surface, borderWidth: 1 },
      emphasis: { itemStyle: { borderColor: CSSV.fg, borderWidth: 1 } } }],
  };
}
async function togglePpa() {
  S.ppaMode = !S.ppaMode;
  const btn = $("#ppa-toggle");
  btn.setAttribute("aria-pressed", String(S.ppaMode));
  $("#cfe-customer").disabled = S.ppaMode;
  if (!S.ppaMode) {
    if (S.cfe) renderCfe(); else loadCfeHeatmap(S.cfeCustomer);
    return;
  }
  if (S.ppa) { renderPpa(); return; }
  if (S.ppaLoading) return;
  S.ppaLoading = true;
  $("#cfe-summary").replaceChildren(h("p", { class: "cfe-facts" }, "Solving the least-cost hourly portfolio for the prospect. The first run takes about ten seconds."));
  overlay("cfe-overlay", "loading", `Designing ${PPA_QUERY.prospect_id} at ${PPA_QUERY.target}% hourly CFE`);
  try {
    S.ppa = await api(`/api/cfe/ppa-heatmap?prospect_id=${encodeURIComponent(PPA_QUERY.prospect_id)}&target=${encodeURIComponent(PPA_QUERY.target)}`);
    if (S.ppaMode) renderPpa();
  } catch (e) {
    if (S.ppaMode) overlay("cfe-overlay", "error", `Prospect design failed: ${e.message}`, () => { S.ppaMode = false; togglePpa(); });
  } finally {
    S.ppaLoading = false;
  }
}
function renderPpa() {
  const p = S.ppa;
  const grid = asList(p.heatmap);
  const cells = [];
  grid.forEach((row, m) => asList(row).forEach((v, hr) => cells.push({ m, hr, v })));
  const valid = cells.filter((c) => c.v != null);
  const low = valid.reduce((a, c) => (a == null || c.v < a.v ? c : a), null);
  const mean = valid.length ? valid.reduce((a, c) => a + Number(c.v), 0) / valid.length : null;
  const below = valid.filter((c) => c.v < Number(p.target_pct)).length;
  $("#cfe-sub").textContent = `Prospect ${p.prospect_id}, target ${num(p.target_pct, 0)}% hourly CFE. Month by hour matched share of a typical day.`;
  $("#cfe-summary").replaceChildren(
    h("div", { class: "ppa-facts" },
      p.feasible ? badge("ok", `Feasible at ${num(p.target_pct, 0)}%`, "✓") : badge("crit", `Not feasible at ${num(p.target_pct, 0)}%`, "✕"),
      p.design && p.design.achieved_hourly_cfe_pct != null
        ? h("span", { class: "mono" }, `Hourly CFE ${num(p.design.achieved_hourly_cfe_pct, 1)}% vs annual matched ${num(p.design.annual_matched_pct, 1)}%`)
        : h("span", { class: "mono" }, `Mean cell ${num(mean, 1)}%`),
      p.design && p.design.price_range_jpy_kwh
        ? h("span", { class: "mono" }, `${num(p.design.price_range_jpy_kwh[0], 2)} to ${num(p.design.price_range_jpy_kwh[1], 2)} JPY/kWh, ${num(p.design.annual_load_gwh, 1)} GWh/yr, ${p.design.term_years} years`)
        : null,
      low ? h("span", { class: "mono" }, `Lowest ${num(low.v, 1)}% (${MONTHS[low.m] || low.m + 1}, ${String(low.hr).padStart(2, "0")}:00)`) : null,
      h("span", { class: "mono" }, `${below} of ${valid.length} cells below target`)),
    h("p", { class: "cfe-facts" }, `Source: ${asList(p.source).map(srcShort).join(", ")}. The target is the share of annual load matched hour by hour, so some month-hours sit below it while others reach 100%.`));
  $("#cfe-key").textContent = "Cell = average matched share for that month and hour under the proposed clean portfolio.";
  const c = chart("cfe-chart");
  if (!c) { overlay("cfe-overlay", "error", NO_ECHARTS); return; }
  overlay("cfe-overlay", null);
  const hours = grid[0] ? grid[0].map((_, i) => `${String(i).padStart(2, "0")}:00`) : [];
  c.setOption(heatOption({
    x: hours, y: grid.map((_, m) => MONTHS[m] || String(m + 1)), data: cells.map((x) => [x.hr, x.m, x.v ?? "-"]), xName: "Hour of day (JST)",
    tip: (pp) => tipHead(`${MONTHS[pp.value[1]]}, ${hours[pp.value[0]]}`) + tipRow("Matched", pp.value[2] === "-" ? "n/a" : `${num(pp.value[2], 1)}%`),
  }), true);
}

/* ------------------------------------------------------------------------------------------ safe markdown */
function mdInline(s) {
  // s is already HTML-escaped; only tags produced here are inserted
  const codes = [];
  let t = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  t = t.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, "$1<strong>$2</strong>");
  t = t.replace(/(^|[^*\w])\*(?=[^\s*])([^*]*?[^\s*])\*(?!\*)/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_\w])_(?=[^\s_])([^_]*?[^\s_])_(?![_\w])/g, "$1<em>$2</em>");
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, "$1 ($2)"); // links rendered as plain text, never as anchors
  return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[Number(i)]}</code>`);
}
const RE_LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const RE_HEAD = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RE_HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const RE_FENCE = /^\s*```/;
const RE_QUOTE = /^\s*&gt;\s?(.*)$/;
const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l || "");
const splitRow = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isBlockStart = (l, next) => RE_LIST.test(l) || RE_HEAD.test(l) || RE_HR.test(l) || RE_FENCE.test(l) || RE_QUOTE.test(l) ||
  (l.includes("|") && isSep(next));

function listHtml(items) {
  let out = "";
  const stack = [];
  for (const it of items) {
    while (stack.length && it.indent < stack[stack.length - 1].indent) out += `</li></${stack.pop().tag}>`;
    const top = stack[stack.length - 1];
    if (!top || it.indent > top.indent) {
      const tag = it.ordered ? "ol" : "ul";
      out += `<${tag}><li>${mdInline(it.text)}`;
      stack.push({ indent: it.indent, tag });
    } else {
      out += `</li><li>${mdInline(it.text)}`;
    }
  }
  while (stack.length) out += `</li></${stack.pop().tag}>`;
  return out;
}

export function renderMarkdown(src) {
  const lines = escapeHtml(String(src ?? "").replace(/\u0000/g, "").replace(/\r\n?/g, "\n")).split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (/^\s*$/.test(line)) { i++; continue; }
    if (RE_FENCE.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !RE_FENCE.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${buf.join("\n")}</code></pre>`);
      continue;
    }
    if ((m = RE_HEAD.exec(line))) {
      const lvl = Math.min(6, m[1].length + 2);
      out.push(`<h${lvl}>${mdInline(m[2])}</h${lvl}>`);
      i++;
      continue;
    }
    if (RE_HR.test(line)) { out.push("<hr>"); i++; continue; }
    if (line.includes("|") && isSep(lines[i + 1])) {
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && !/^\s*$/.test(lines[i])) rows.push(splitRow(lines[i++]));
      out.push(`<div class="md-table"><table class="data"><thead><tr>${head.map((c) => `<th>${mdInline(c)}</th>`).join("")}</tr></thead><tbody>${
        rows.map((r) => `<tr>${head.map((_, j) => `<td>${mdInline(r[j] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (RE_LIST.test(line)) {
      const items = [];
      while (i < lines.length && (m = RE_LIST.exec(lines[i]))) {
        const it = { indent: m[1].length, ordered: /\d/.test(m[2]), text: m[3] };
        i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !RE_LIST.test(lines[i])) it.text += ` ${lines[i++].trim()}`;
        items.push(it);
      }
      out.push(listHtml(items));
      continue;
    }
    if (RE_QUOTE.test(line)) {
      const buf = [];
      while (i < lines.length && (m = RE_QUOTE.exec(lines[i]))) { buf.push(m[1]); i++; }
      out.push(`<blockquote>${buf.map(mdInline).join("<br>")}</blockquote>`);
      continue;
    }
    const buf = [line.trim()];
    i++;
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !isBlockStart(lines[i], lines[i + 1])) buf.push(lines[i++].trim());
    out.push(`<p>${buf.map(mdInline).join("<br>")}</p>`);
  }
  return out.join("");
}

/* ------------------------------------------------------------------------------------------ scenarios + chat */
async function loadScenarios() {
  const box = $("#scenario-chips");
  setState(box, "loading", "Loading suggested prompts");
  try {
    S.scenarios = asList(await api("/api/scenarios"));
    box.replaceChildren(...S.scenarios.map((s) => h("button", { class: "chip", type: "button", title: `${s.persona}: ${s.prompt}`,
      "aria-label": `${s.id} ${s.title}, ${s.persona}. Sends: ${s.prompt}`, onclick: () => { $("#chat-input").value = s.prompt; sendChat(s.prompt, s); } },
    h("span", { class: "chip-id mono" }, s.id), h("span", null, s.title))));
    updateComposer();
  } catch (e) {
    setState(box, "error", `Suggested prompts unavailable: ${e.message}`, loadScenarios);
  }
}

function updateComposer() {
  $("#send-btn").disabled = S.running;
  $("#stop-btn").hidden = !S.running;
  $("#new-session").disabled = S.running;
  document.querySelectorAll("#scenario-chips .chip").forEach((b) => { b.disabled = S.running; });
  $("#session-line").textContent = S.sessionId ? `Session ${S.sessionId}` : "New session (created on first message)";
}
function convoScroll() {
  const cv = $("#convo");
  cv.scrollTop = cv.scrollHeight;
}
function addUserMsg(text, scenario) {
  $("#convo .convo-empty")?.remove();
  $("#convo").append(h("div", { class: "msg user" },
    h("div", { class: "msg-who" }, scenario ? `You, ${scenario.id} ${scenario.title}` : "You"), h("p", { class: "msg-text" }, text)));
  convoScroll();
}
function addBotMsg() {
  const body = h("div", { class: "md" }, h("p", { class: "muted" }, "Working on it."));
  const progress = h("div", { class: "msg-progress", "aria-hidden": "true" }, h("span", { class: "spinner" }), h("span", { class: "pg-text" }, "Starting"));
  const meta = h("div", { class: "msg-meta mono" });
  const el = h("div", { class: "msg bot" }, h("div", { class: "msg-who" }, h("span", { class: "dot", vars: { "--agent-color": AGENT_BY_ID[ORCH].color } }), ORCH), progress, body, meta);
  $("#convo").append(el);
  convoScroll();
  return { el, body, progress, meta };
}
function setProgress(turn, text) {
  turn.progressText = text;
  const secs = ((performance.now() - turn.start) / 1000).toFixed(0);
  const line = `Working ${secs} s: ${text}`;
  $("#chat-status").textContent = line;
  $("#agent-status").textContent = line;
  $("#agent-status").title = line;
  $("#agent-status").classList.add("busy");
  turn.bot.progress.querySelector(".pg-text").textContent = line;
}

async function sendChat(message, scenario) {
  const text = String(message || "").trim();
  if (S.running || !text) return;
  S.running = true;
  $("#chat-input").value = "";
  updateComposer();
  addUserMsg(text, scenario);
  const bot = addBotMsg();
  const turn = { start: performance.now(), toolCalls: 0, pending: 0, lastText: "", final: false, error: null, bot, progressText: "Sending", stopped: false };
  S.turnNo += 1;
  consoleTurn(text, scenario);
  rosterReset();
  setProgress(turn, "Sending request to desk_orchestrator");
  const tick = setInterval(() => setProgress(turn, turn.progressText), 1000);
  S.abort = new AbortController();
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message: text, session_id: S.sessionId }), signal: S.abort.signal });
    if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    const flush = (final) => {
      buf = buf.replace(/\r\n/g, "\n");
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0 || (final && buf.trim())) {
        const block = idx >= 0 ? buf.slice(0, idx) : buf;
        buf = idx >= 0 ? buf.slice(idx + 2) : "";
        const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, "")).join("\n");
        if (!data) continue;
        let ev;
        try { ev = JSON.parse(data); } catch { continue; }
        handleEvent(ev, turn);
      }
    };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      flush(false);
    }
    buf += dec.decode();
    flush(true);
  } catch (e) {
    if (e.name === "AbortError") turn.stopped = true;
    else turn.error = e.message;
  } finally {
    clearInterval(tick);
    S.running = false;
    S.abort = null;
    finishTurn(turn);
    updateComposer();
    refreshAfterTurn();
  }
}

function handleEvent(ev, turn) {
  const author = ev.author || "agent";
  switch (ev.type) {
    case "session":
      S.sessionId = ev.session_id;
      updateComposer();
      break;
    case "tool_call": {
      turn.toolCalls += 1;
      const delegate = AGENT_BY_ID[ev.tool];
      rosterSet(author, "working");
      if (delegate) rosterSet(ev.tool, "working");
      rosterCount(author);
      setProgress(turn, delegate ? `${author} is asking ${ev.tool}` : `${author} is calling ${ev.tool}`);
      consoleToolCall(ev, turn);
      break;
    }
    case "tool_result": {
      if (AGENT_BY_ID[ev.tool]) rosterSet(ev.tool, "done");
      setProgress(turn, `${author} received the ${ev.tool} result`);
      consoleToolResult(ev, turn);
      break;
    }
    case "pending_action":
      turn.pending += 1;
      setProgress(turn, `${author} queued ${KIND_LABEL[ev.action?.kind] || "an action"} for approval`);
      consolePending(ev, turn);
      scheduleActionsRefresh();
      break;
    case "audit":
      rosterSet(author, "done");
      setProgress(turn, `${author} verdict ${String(ev.verdict || "").toUpperCase()} for ${ev.action_id}`);
      consoleAudit(ev, turn);
      scheduleActionsRefresh();
      break;
    case "text":
      if (author === ORCH) {
        turn.lastText = String(ev.text || "");
        turn.bot.body.innerHTML = renderMarkdown(turn.lastText); // escaped by renderMarkdown
        setProgress(turn, `${ORCH} is writing the reply`);
        consoleText(ev, turn, true);
        convoScroll();
      } else {
        rosterSet(author, "done");
        setProgress(turn, `${author} is reporting back`);
        consoleText(ev, turn, false);
      }
      break;
    case "final":
      turn.final = true;
      consoleLine(ORCH, "fin", [h("span", { class: "k ok" }, "FINAL"), ` Turn complete in ${num((performance.now() - turn.start) / 1000, 1)} s`], turn);
      break;
    case "error":
      turn.error = String(ev.error || "unknown error");
      consoleLine(ev.author || "server", "err", [h("span", { class: "k err" }, "ERROR"), " ", turn.error], turn);
      break;
    default:
      break;
  }
}

function finishTurn(turn) {
  const secs = num((performance.now() - turn.start) / 1000, 1);
  turn.bot.progress.remove();
  const b = turn.bot.body;
  if (turn.lastText) b.innerHTML = renderMarkdown(turn.lastText); // escaped by renderMarkdown
  else if (turn.error) b.replaceChildren(h("p", { class: "err-text", role: "alert" }, `The desk could not answer: ${turn.error}`));
  else if (turn.stopped) b.replaceChildren(h("p", { class: "muted" }, "Stopped listening. The agents may still finish in the background; refresh pending actions to see any proposals."));
  else b.replaceChildren(h("p", { class: "muted" }, "No reply text arrived from desk_orchestrator."));
  if (turn.error && turn.lastText) b.append(h("p", { class: "err-text", role: "alert" }, `Stream error: ${turn.error}`));
  const parts = [`${secs} s`, `${turn.toolCalls} tool call${turn.toolCalls === 1 ? "" : "s"}`];
  if (turn.pending) parts.push(`${turn.pending} action${turn.pending === 1 ? "" : "s"} queued for approval`);
  turn.bot.meta.replaceChildren(parts.join(" · "), turn.pending ? h("a", { href: "#actions", class: "meta-link" }, "Review actions") : null);
  $("#chat-status").textContent = turn.error ? `Error after ${secs} s` : turn.stopped ? `Stopped after ${secs} s` : `Done in ${secs} s`;
  $("#agent-status").textContent = "Idle";
  $("#agent-status").classList.remove("busy");
  rosterIdle();
  convoScroll();
}
function refreshAfterTurn() {
  loadActions(true);
  loadAudit(true);
}

/* ------------------------------------------------------------------------------------------ swarm console */
const agentColor = (id) => AGENT_BY_ID[id]?.color || "#7d8590";
function rosterRender() {
  $("#roster").replaceChildren(...AGENTS.map((a) => h("li", { class: "ag", "data-id": a.id, "data-state": "idle", vars: { "--agent-color": a.color }, title: a.role },
    h("span", { class: "dot", "aria-hidden": "true" }), h("span", { class: "ag-name mono" }, a.id), h("span", { class: "ag-state" }, "idle"))));
}
function rosterEl(id) { return document.querySelector(`#roster .ag[data-id="${CSS.escape(id)}"]`); }
function rosterSet(id, state) {
  const el = rosterEl(id);
  if (!el) return;
  el.dataset.state = state;
  const n = Number(el.dataset.calls || 0);
  el.querySelector(".ag-state").textContent = state === "working" ? `working${n ? `, ${n} calls` : ""}` : state === "done" ? `done${n ? `, ${n} calls` : ""}` : "idle";
}
function rosterCount(id) {
  const el = rosterEl(id);
  if (!el) return;
  el.dataset.calls = String(Number(el.dataset.calls || 0) + 1);
  rosterSet(id, el.dataset.state === "idle" ? "working" : el.dataset.state);
}
function rosterReset() { document.querySelectorAll("#roster .ag").forEach((el) => { el.dataset.calls = "0"; rosterSet(el.dataset.id, "idle"); }); }
function rosterIdle() { document.querySelectorAll("#roster .ag").forEach((el) => { if (el.dataset.state === "working") rosterSet(el.dataset.id, "done"); }); }

function logEl() { return $("#console-log"); }
function nearBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 48; }
function consoleEmpty() {
  logEl().replaceChildren(h("p", { class: "console-empty" }, "No activity yet. Send a prompt to watch the orchestrator route work to the specialist agents."));
}
function consoleTurn(text, scenario) {
  const log = logEl();
  log.querySelector(".console-empty")?.remove();
  log.append(h("div", { class: "turn-sep" }, `Turn ${S.turnNo}${scenario ? `, ${scenario.id} ${scenario.title}` : ""}: `, h("span", { class: "turn-q" }, text.length > 140 ? `${text.slice(0, 140)} ...` : text)));
  log.scrollTop = log.scrollHeight;
}
function consoleLine(author, kind, content, turn) {
  const log = logEl();
  const stick = nearBottom(log);
  log.querySelector(".console-empty")?.remove();
  let g = log.lastElementChild;
  if (!g || !g.classList.contains("cgroup") || g.dataset.author !== author) {
    const a = AGENT_BY_ID[author];
    g = h("div", { class: "cgroup", "data-author": author, vars: { "--agent-color": agentColor(author) } },
      h("div", { class: "cg-head" }, h("span", { class: "atag" }, h("span", { class: "dot", "aria-hidden": "true" }), author),
        a ? h("span", { class: "cg-role" }, a.role) : null));
    log.append(g);
  }
  const t = turn ? `+${num((performance.now() - turn.start) / 1000, 1)}s` : "";
  g.append(h("div", { class: `cl ${kind}` }, h("span", { class: "cl-t" }, t), h("div", { class: "cl-c" }, content)));
  if (stick) log.scrollTop = log.scrollHeight;
}
function argsText(args) {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args).map(([k, v]) => {
    let s = typeof v === "string" ? JSON.stringify(v) : JSON.stringify(v);
    if (s && s.length > 160) s = `${s.slice(0, 160)} ...`;
    return `${k}=${s}`;
  }).join(", ");
}
function sourceChips(list) {
  const items = asList(list).filter(Boolean);
  if (!items.length) return null;
  return h("span", { class: "src-chips" }, items.map((s) => h("span", { class: "src-chip", title: String(s) }, srcShort(s))));
}
function statusTag(st) {
  const s = st == null ? "no status" : String(st);
  const kind = /^(ok|pass|done|success)$/i.test(s) ? "ok" : /pending/i.test(s) ? "info" : /(error|fail|reject|denied|invalid)/i.test(s) ? "err" : s === "no status" ? "mut" : "warn";
  return h("span", { class: `k ${kind}` }, s.toUpperCase().replace(/_/g, " "));
}
function expandable(text, n = 240) {
  const s = String(text ?? "");
  if (s.length <= n) return h("span", { class: "pv" }, s);
  return h("details", { class: "pv-more" }, h("summary", null, h("span", { class: "pv" }, `${s.slice(0, n)} ...`), h("span", { class: "more" }, " show all")),
    h("div", { class: "pv full" }, s));
}
function consoleToolCall(ev, turn) {
  const delegate = AGENT_BY_ID[ev.tool];
  consoleLine(ev.author || "agent", "tool", [
    h("span", { class: "k tool" }, delegate ? "DELEGATE" : "CALL"), " ",
    h("span", { class: "tool" }, delegate ? `to ${ev.tool}` : ev.tool),
    h("span", { class: "args" }, delegate ? ` ${argsText(ev.args)}` : `(${argsText(ev.args)})`)], turn);
}
function consoleToolResult(ev, turn) {
  consoleLine(ev.author || "agent", "res", [
    h("span", { class: "k res" }, "RESULT"), " ", h("span", { class: "tool" }, ev.tool), " ", statusTag(ev.status), " ",
    sourceChips(ev.source), h("div", { class: "preview" }, expandable(ev.preview, 220))], turn);
}
function consolePending(ev, turn) {
  const a = ev.action || {};
  consoleLine(ev.author || "agent", "pend", [
    h("span", { class: "k info" }, "PENDING ACTION"), " ", h("span", { class: "mono" }, a.id || ""), " ",
    h("span", null, KIND_LABEL[a.kind] || a.kind || ""), h("div", { class: "preview" }, expandable(a.summary, 200))], turn);
}
function consoleAudit(ev, turn) {
  const checks = asList(ev.checks);
  const fails = checks.filter((c) => c.result !== "pass");
  const v = String(ev.verdict || "").toLowerCase();
  consoleLine(ev.author || "risk_auditor", "aud", [
    h("span", { class: `k ${v === "pass" ? "ok" : "err"}` }, `AUDIT ${v.toUpperCase() || "UNKNOWN"}`), " ",
    h("span", { class: "mono" }, ev.action_id || ""), ` ${checks.length - fails.length} of ${checks.length} checks pass`,
    fails.length ? h("ul", { class: "fails" }, fails.map((f) => h("li", null, `✕ ${f.rule}: ${f.detail} ${f.citation || ""}`))) : null], turn);
}
function consoleText(ev, turn, isReply) {
  consoleLine(ev.author || "agent", "txt", [h("span", { class: "k mut" }, isReply ? "REPLY" : "SAYS"), " ",
    isReply ? h("span", { class: "pv" }, `${String(ev.text || "").length} characters, shown in the chat`) : expandable(ev.text, 260)], turn);
}

/* ------------------------------------------------------------------------------------------ actions tray */
let actionsTimer = 0;
function scheduleActionsRefresh() {
  clearTimeout(actionsTimer);
  actionsTimer = setTimeout(() => loadActions(true), 400);
}
async function loadActions(quiet = false) {
  const list = $("#actions-list");
  if (!quiet && !list.children.length) setState(list, "loading", "Loading actions");
  try {
    S.actions = asList(await api("/api/actions"));
    renderActions();
  } catch (e) {
    setState(list, "error", `Could not load actions: ${e.message}`, () => loadActions());
    $("#pending-link").textContent = "Approvals unavailable";
  }
}
const actionSig = (a) => [a.status, a.audit?.verdict ?? "none", asList(a.audit?.checks).length, a.execution ?? "", S.actionErrors[a.id] ?? ""].join("|");
function renderActions() {
  const list = $("#actions-list");
  const pending = S.actions.filter((a) => a.status === "pending");
  const decided = S.actions.filter((a) => a.status !== "pending");
  const link = $("#pending-link");
  link.textContent = pending.length ? `${pending.length} awaiting approval` : "No pending approvals";
  link.className = `pending-link ${pending.length ? "has" : ""}`;
  $("#actions-title").textContent = pending.length ? `Pending actions (${pending.length})` : "Pending actions";
  if (!S.actions.length) {
    list.replaceChildren(h("div", { class: "empty" },
      h("p", null, "No proposals yet. Agents can only propose; nothing executes until a person approves here."),
      S.scenarios.find((s) => s.id === "S1") ? h("p", { class: "sub" }, `Try "S1 ${S.scenarios.find((s) => s.id === "S1").title}" in the chat.`) : null));
    return;
  }
  const existing = new Map([...list.children].filter((n) => n.dataset?.id).map((n) => [n.dataset.id, n]));
  list.replaceChildren(...[...pending, ...decided].map((a) => {
    const node = existing.get(a.id);
    return node && node.dataset.sig === actionSig(a) ? node : actionCard(a);
  }));
}
function riskBadge(r) {
  const s = String(r || "unknown").toLowerCase();
  return badge(s === "high" ? "crit" : s === "medium" ? "warn" : s === "low" ? "ok" : "info", `Risk ${s}`);
}
function auditBadge(a) {
  const v = a.audit?.verdict;
  if (v === "pass") return badge("ok", "Audit pass", "✓");
  if (v === "fail") return badge("crit", "Audit fail", "✕");
  return badge("info", "Not audited", "?");
}
function statusBadge(a) {
  if (a.status === "executed_sandbox") return badge("ok", "Executed in sandbox", "✓");
  if (a.status === "rejected") return badge("info", "Rejected", "✕");
  return badge("warn", "Awaiting approval", "!");
}
function actionCard(a) {
  const id = a.id;
  const isPending = a.status === "pending";
  const reviewed = S.reviewed.has(id);
  const details = h("details", { class: "reasoning" },
    h("summary", null, h("span", null, "Reasoning and sources"), h("span", { class: "sum-hint" }, isPending && !reviewed ? "Required before approval" : "")),
    h("div", { class: "reasoning-body" },
      h("h4", null, "Agent reasoning"),
      asList(a.reasoning).length ? h("ul", { class: "bullets" }, asList(a.reasoning).map((r) => h("li", null, String(r)))) : h("p", { class: "muted" }, "No reasoning supplied."),
      h("h4", null, "Sources"),
      sourceChips(a.sources) || h("p", { class: "muted" }, "No sources listed."),
      h("h4", null, "Key details"),
      actionDetails(a),
      h("h4", null, "Risk auditor checks"),
      auditTable(a)));
  if (S.openDetails.has(id)) details.open = true;
  const confirmBtn = isPending ? h("button", { class: "btn primary confirm", type: "button", disabled: !reviewed }, "Hold to confirm") : null;
  const rejectBtn = isPending ? h("button", { class: "btn", type: "button" }, "Reject") : null;
  const hint = isPending ? h("p", { class: "hint", "aria-live": "polite" }) : null;
  const setHint = () => {
    if (!hint) return;
    const v = a.audit?.verdict;
    const warnTxt = v === "fail" ? " The risk auditor flagged failures; approve only if you accept them."
      : !v ? " The risk auditor has not checked this action yet." : "";
    hint.textContent = S.reviewed.has(id)
      ? `Press and hold for 2 seconds to approve. Runs in the sandbox only; nothing is sent to the market.${warnTxt}`
      : `Open "Reasoning and sources" to enable approval.${warnTxt}`;
    hint.classList.toggle("warn-text", v === "fail");
  };
  setHint();
  details.addEventListener("toggle", () => {
    if (details.open) {
      S.openDetails.add(id);
      if (isPending && !S.reviewed.has(id)) {
        S.reviewed.add(id);
        confirmBtn.disabled = false;
        details.querySelector(".sum-hint").textContent = "";
        setHint();
      }
    } else S.openDetails.delete(id);
  });
  if (confirmBtn) {
    holdToConfirm(confirmBtn, () => decide(a, "confirm", confirmBtn, rejectBtn), { ms: 2000 });
    rejectBtn.addEventListener("click", () => decide(a, "reject", confirmBtn, rejectBtn));
  }
  const err = S.actionErrors[id];
  const card = h("article", { class: `action ${a.status}`, "data-id": id, "data-sig": actionSig(a), "aria-label": `${KIND_LABEL[a.kind] || a.kind} ${id}` },
    h("header", { class: "action-head" },
      h("div", null, h("div", { class: "caps" }, KIND_LABEL[a.kind] || humanKey(a.kind || "action")), h("div", { class: "action-id mono" }, id)),
      h("div", { class: "action-badges" }, statusBadge(a), riskBadge(a.risk), auditBadge(a))),
    h("p", { class: "action-summary" }, String(a.summary || "")),
    h("p", { class: "action-meta" }, `Proposed by ${a.created_by || "agent"}${a.created ? ` at ${hhmmss(a.created)}` : ""}. Requires ${String(a.requires || "approval").replace(/_/g, " ")}.`),
    details,
    err ? h("p", { class: "err-text", role: "alert" }, err) : null,
    isPending
      ? h("footer", { class: "action-foot" }, hint, h("div", { class: "action-btns" }, confirmBtn, rejectBtn))
      : h("footer", { class: "action-foot decided" },
        h("p", { class: "exec" }, a.status === "executed_sandbox" ? `Execution: ${a.execution || "recorded"}` : "Rejected. Nothing was executed."),
        a.decided ? h("p", { class: "action-meta" }, `Decided at ${hhmmss(a.decided)}`) : null));
  return card;
}
async function decide(a, decision, confirmBtn, rejectBtn) {
  if (confirmBtn) confirmBtn.disabled = true;
  if (rejectBtn) rejectBtn.disabled = true;
  delete S.actionErrors[a.id];
  try {
    const r = await api(`/api/actions/${encodeURIComponent(a.id)}/${decision}`, { method: "POST" });
    toast(decision === "confirm" ? `Approved ${a.id}. ${r?.execution || "Executed in the sandbox."}` : `Rejected ${a.id}. Nothing was executed.`,
      decision === "confirm" ? "ok" : "info");
  } catch (e) {
    S.actionErrors[a.id] = e.status === 409 ? "Already decided by someone else. Showing the latest status." : `Could not ${decision}: ${e.message}`;
    toast(S.actionErrors[a.id], "crit");
  }
  const jobs = [loadActions(true), loadAudit(true)];
  if (decision === "confirm") jobs.push(loadKpis(true), loadPosition(true));
  await Promise.allSettled(jobs);
}

function actionDetails(a) {
  const d = a.details || {};
  try {
    if (a.kind === "intraday_orders") {
      const orders = asList(d.orders);
      return h("div", { class: "tbl-wrap" }, tableFrom(
        ["Slot", "Delivery", "Gate closes", "Buy MWh", "Limit JPY/kWh", "Imbalance p50 JPY/kWh", "Expected cost"],
        [...orders.map((o) => [o.slot, o.time, nowHHMM(o.gate_closure) || o.gate_closure, num(o.quantity_mwh, 2), num(o.limit_price_jpy_kwh, 2),
          num(o.imbalance_p50_jpy_kwh, 2), jpy(o.expected_cost_jpy)]),
        { cls: "total", cells: ["Total", "", "", num(d.total_quantity_mwh, 2), "", "", jpy(d.expected_cost_jpy)] }], { num: [0, 3, 4, 5, 6] }));
    }
    if (a.kind === "vpp_dispatch") {
      const bySlot = Object.entries(d.mwh_by_slot || {}).map(([s, q]) => [Number(s), Number(q)]).sort((x, y) => x[0] - y[0]);
      const sched = asList(d.schedule);
      const byClass = {};
      sched.forEach((x) => {
        const c = (byClass[x.asset_class] ??= { mwh: 0, cost: 0, clusters: new Set() });
        c.mwh += Number(x.mwh || 0);
        c.cost += Number(x.mwh || 0) * Number(x.cost_jpy_kwh || 0);
        c.clusters.add(x.cluster_id);
      });
      return h("div", { class: "detail-grid" },
        h("div", { class: "tbl-wrap" }, h("div", { class: "caps tbl-cap" }, "Dispatch by slot"), tableFrom(["Slot", "Delivery", "MWh"],
          [...bySlot.map(([s, q]) => [s, slotTime(s), num(q, 2)]), { cls: "total", cells: ["Total", "", num(d.total_mwh, 2)] }], { num: [0, 2] })),
        h("div", { class: "tbl-wrap" }, h("div", { class: "caps tbl-cap" }, "By asset class"), tableFrom(["Class", "Clusters", "MWh", "Avg JPY/kWh"],
          Object.entries(byClass).map(([k, c]) => [CLASS_LABEL[k] || humanKey(k), c.clusters.size, num(c.mwh, 2), num(c.mwh ? c.cost / c.mwh : null, 2)]), { num: [1, 2, 3] })),
        h("p", { class: "kv-line" }, `Expected cost ${jpy(d.expected_cost_jpy)} for ${u(d.total_mwh, 2, "MWh")}.`),
        asList(d.excluded_clusters).length ? h("p", { class: "kv-line" }, badge("crit", "Excluded", "✕"), " ", asList(d.excluded_clusters).join(", "), " (untrusted telemetry)") : null);
    }
    if (a.kind === "tariff_adjustment") {
      const unit = d.adjustment_type === "widen_band" ? "%" : " JPY/kWh";
      const base = [["Customer", `${d.customer_name || ""} (${d.customer_id || ""})`], ["Adjustment", humanKey(d.adjustment_type || "")],
        ["New value", `${num(d.new_value, 2)}${unit}`], ["Effective date", d.effective_date || "n/a"], ["Notice", `${num(d.notice_days, 0)} days`],
        ["Customer consent required", d.customer_consent_required ? "Yes" : "No"]];
      return kvList([...base, ...Object.entries(d.impact || {}).map(([k, v]) => kv(k, v))]);
    }
    if (a.kind === "ppa_offer") {
      const pb = d.price_build_up || {};
      const range = asList(pb.price_range_jpy_kwh);
      const warn = asList(d.document_warnings);
      return h("div", { class: "detail-stack" },
        kvList([["Prospect", `${d.prospect_name || ""} (${d.prospect_id || ""})`], ["Term", `${num(d.term_years, 0)} years`],
          ["Hourly CFE target vs achieved", `${num(d.cfe_target_pct, 1)}% target, ${num(d.achieved_hourly_cfe_pct, 1)}% achieved`],
          ["Annual-style match", `${num(d.annual_matched_pct, 1)}%`], ["Annual load", u(d.annual_load_gwh, 1, "GWh")],
          ["Storage", `${u(Math.abs(Number(d.storage?.power_mw) || 0), 1, "MW")}, ${u(Math.abs(Number(d.storage?.energy_mwh) || 0), 1, "MWh")}`],
          ["Deal Committee required", d.deal_committee_required ? "Yes" : "No"],
          ["Price range", range.length === 2 ? `${num(range[0], 2)} to ${num(range[1], 2)} JPY/kWh` : "n/a"]]),
        h("div", { class: "detail-grid" },
          h("div", { class: "tbl-wrap" }, h("div", { class: "caps tbl-cap" }, "Price build-up"), tableFrom(["Component", "JPY/kWh"],
            Object.entries(pb).filter(([k, v]) => typeof v === "number").map(([k, v]) => ({ cls: k === "total_jpy_kwh" ? "total" : null,
              cells: [humanKey(k.replace(/_jpy_kwh$/, "")), num(v, 2)] })), { num: [1] })),
          h("div", { class: "tbl-wrap" }, h("div", { class: "caps tbl-cap" }, "Capacity mix"), tableFrom(["Resource", "Type", "MW", "GWh/yr"],
            asList(d.capacity_mix).map((c) => [c.resource_id, humanKey(c.type || ""), num(c.mw, 1), num(c.annual_gwh, 1)]), { num: [2, 3] }))),
        warn.length ? h("div", { class: "injection" }, h("div", { class: "caps" }, "Untrusted text found in the prospect document and ignored"),
          warn.map((w) => h("blockquote", { class: "quoted" }, String(w).slice(0, 240)))) : null);
    }
  } catch (e) {
    return h("p", { class: "err-text" }, `Could not render details: ${e.message}`);
  }
  const flat = Object.entries(d).filter(([, v]) => v == null || typeof v !== "object").map(([k, v]) => kv(k, v));
  return flat.length ? kvList(flat) : h("p", { class: "muted" }, "No details supplied.");
}
function kvList(pairs) {
  return h("dl", { class: "kv" }, pairs.flatMap(([k, v]) => [h("dt", null, k), h("dd", { class: "mono" }, String(v))]));
}
function auditTable(a) {
  const checks = asList(a.audit?.checks);
  if (!a.audit) return h("p", { class: "muted" }, "Not audited yet. Ask the desk to run the risk auditor on this action before approving.");
  if (!checks.length) return h("p", { class: "muted" }, `Verdict ${String(a.audit.verdict || "unknown").toUpperCase()}, no check details returned.`);
  return h("div", { class: "tbl-wrap" }, tableFrom(["Rule", "Result", "Detail", "Citation"], checks.map((c) => ({
    cls: c.result === "pass" ? null : "row-fail",
    cells: [c.rule, h("span", { class: `res ${c.result === "pass" ? "ok" : "fail"}` }, c.result === "pass" ? "✓ PASS" : "✕ FAIL"), c.detail, c.citation],
  })), { cls: "checks" }));
}

/* ------------------------------------------------------------------------------------------ audit log */
async function loadAudit(quiet = false) {
  const box = $("#audit-body");
  if (!quiet && !box.children.length) setState(box, "loading", "Loading audit log");
  try {
    S.audit = asList(await api("/api/audit"));
    renderAudit();
  } catch (e) {
    setState(box, "error", `Could not load audit log: ${e.message}`, () => loadAudit());
  }
}
function renderAudit() {
  const box = $("#audit-body");
  if (!S.audit.length) {
    box.replaceChildren(h("p", { class: "empty" }, "No decisions recorded yet. Approvals and rejections appear here with the auditor verdict."));
    return;
  }
  box.replaceChildren(h("div", { class: "tbl-wrap" }, tableFrom(["Time (local)", "Decision", "Action", "Kind", "Summary", "Auditor", "Method", "Execution"],
    S.audit.map((r) => [
      hhmmss(r.at),
      r.decision === "confirm" ? badge("ok", "Confirmed", "✓") : badge("info", "Rejected", "✕"),
      h("span", { class: "mono" }, r.action_id),
      KIND_LABEL[r.kind] || humanKey(r.kind || ""),
      r.summary || "",
      r.audit_verdict === "pass" ? badge("ok", "Pass", "✓") : r.audit_verdict === "fail" ? badge("crit", "Fail", "✕") : badge("info", "Not audited", "?"),
      r.method === "hold_to_confirm_2s" ? "Hold to confirm, 2 s" : humanKey(r.method || ""),
      r.execution || "none",
    ]), { cls: "audit-table" })));
}

/* ------------------------------------------------------------------------------------------ wiring */
function wire() {
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chat-input").value); });
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!S.running) sendChat($("#chat-input").value); }
  });
  $("#stop-btn").addEventListener("click", () => S.abort?.abort());
  $("#new-session").addEventListener("click", () => {
    if (S.running) return;
    S.sessionId = null;
    $("#convo").replaceChildren(h("p", { class: "muted convo-empty" }, "New session started. Pick a suggested prompt or type a question."));
    updateComposer();
  });
  $("#console-clear").addEventListener("click", () => { consoleEmpty(); if (!S.running) rosterReset(); });
  $("#actions-refresh").addEventListener("click", () => loadActions());
  $("#audit-refresh").addEventListener("click", () => loadAudit());
  $("#cfe-customer").addEventListener("change", (e) => loadCfeHeatmap(e.target.value));
  $("#ppa-toggle").addEventListener("click", togglePpa);
  $("#ppa-toggle").textContent = `Prospect design: ${PPA_QUERY.prospect_id} at ${PPA_QUERY.target}%`;
  $("#market-tv").addEventListener("toggle", (e) => { if (e.target.open) renderMarketTable(); });
  $("#position-tv").addEventListener("toggle", (e) => { if (e.target.open) renderPositionTable(); });
  $("#convo").replaceChildren(h("p", { class: "muted convo-empty" }, "Pick a suggested prompt or type a question. Replies take 30 to 120 seconds while the agents work."));
  rosterRender();
  consoleEmpty();
  updateComposer();
}

async function init() {
  if (hasECharts()) registerTheme();
  wire();
  await Promise.allSettled([loadClock(), loadHealth(), loadKpis(), loadMarket(), loadPosition(), loadFleet(), loadCfe(), loadScenarios(), loadActions(), loadAudit()]);
  setInterval(loadClock, 60000);
}

init();
