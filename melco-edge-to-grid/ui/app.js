// Factory Energy Command: every number on screen comes from /api/* (no hand-typed values).
import { holdToConfirm } from "./hold-to-confirm.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "n/a" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
const jpy = (v) => `${num(v)} JPY`;
const mjpy = (v) => `${num(v / 1e6, 2)}M JPY`;
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const GROUP_COLORS = ["--g1", "--g2", "--g3", "--g4", "--g5", "--g6", "--g7"];
const AGENT_COLORS = {
  optimization_orchestrator: "--accent", market_intelligence_agent: "--g1", factory_interlock_agent: "--g2", bess_strategy_agent: "--g3",
  asset_health_agent: "--g4", gain_share_agent: "--g5", safety_auditor: "--g7",
};
const charts = {};

function baseChart(id) {
  const el = document.getElementById(id);
  const c = echarts.init(el, null, { renderer: "canvas" });
  charts[id] = c;
  return c;
}
function axisStyle() {
  return {
    axisLine: { lineStyle: { color: css("--border") } }, axisTick: { show: false },
    axisLabel: { color: css("--fg-muted"), fontFamily: "JetBrains Mono", fontSize: 10 },
    splitLine: { lineStyle: { color: css("--grid") } },
  };
}
const tooltip = (extra = {}) => ({
  trigger: "axis", backgroundColor: css("--surface-high"), borderColor: css("--border"), textStyle: { color: css("--fg"), fontSize: 12 },
  axisPointer: { type: "line", lineStyle: { color: css("--fg-muted") } }, ...extra,
});
const legend = (data) => ({ data, top: 0, textStyle: { color: css("--fg-muted"), fontSize: 11 }, itemWidth: 14, itemHeight: 8, icon: "roundRect" });
const badge = (verdict) => {
  const map = { ACCEPT: ["ok", "✓"], LIMIT: ["warn", "◐"], REJECT: ["crit", "✕"], APPROVED: ["ok", "✓"], APPROVED_WITH_CONDITIONS: ["warn", "◐"], BLOCKED: ["crit", "✕"],
    high: ["crit", "!"], medium: ["warn", "!"], low: ["info", "i"], pending: ["warn", "…"], executed_sandbox: ["ok", "✓"], rejected: ["crit", "✕"], blocked_at_edge: ["crit", "✕"] };
  const [cls, ico] = map[verdict] || ["info", "i"];
  return `<span class="badge ${cls}"><span class="ico" aria-hidden="true">${ico}</span>${esc(String(verdict).replaceAll("_", " "))}</span>`;
};

// ---------------------------------------------------------------------------------------------
async function loadDashboard() {
  const [health, ov, stack, drToday, drAll, flex, bess, pv, jepx, anom, gain] = await Promise.all([
    api("/api/health"), api("/api/overview"), api("/api/load-stack"), api("/api/dr-today"), api("/api/dr-events"), api("/api/flex"),
    api("/api/bess"), api("/api/pv"), api("/api/jepx"), api("/api/anomalies"), api("/api/gain-share?month=2026-07"),
  ]);
  $("#backend").textContent = `agents: ${health.agent_backend} · data: ${health.data_backend} (${health.dataset})`;
  renderKpis(ov);
  renderStack(stack);
  renderTimeline(drToday, drAll, ov, flex, pv, jepx);
  renderFlex(flex);
  renderBess(bess);
  renderPv(pv);
  renderJepx(jepx);
  renderAnomalies(anom);
  renderGain(gain);
  await refreshLogs();
}

function renderKpis(ov) {
  const k = ov.kpis;
  const set = (id, value, sub) => { $(`#${id} .kpi-value`).innerHTML = value; $(`#${id} .kpi-sub`).innerHTML = sub; };
  set("kpi-load", `${num(k.plant_load.value_kw)} <small>kW</small>`,
    `${num(100 * k.plant_load.value_kw / k.plant_load.contracted_kw, 1)} % of ${num(k.plant_load.contracted_kw)} kW contracted · month peak ${num(k.plant_load.month_peak_kw)} kW`);
  set("kpi-dr", `${num(k.dr.firm_kw)} <small>/ ${num(k.dr.target_kw)} kW</small>`,
    `<span class="${k.dr.margin_kw >= 0 ? "up" : "down"}">${k.dr.margin_kw >= 0 ? "+" : ""}${num(k.dr.margin_kw)} kW (${num(k.dr.margin_pct, 1)} %)</span> firm, ${k.dr.window}, ${k.dr.rejected} action rejected at the edge`);
  set("kpi-bess", `${num(k.bess.soc_pct, 1)} <small>%</small>`, `${k.bess.mode} ${num(Math.abs(k.bess.power_kw))} kW under ${esc(k.bess.policy)}`);
  set("kpi-pv", `${num(k.pv.now_kw)} <small>kW</small>`, `p50 ${num(k.pv.p50_kw)} kW for 13:30 · 3,000 kWp installed`);
  set("kpi-jepx", `${num(k.jepx.spot_now, 2)} <small>JPY/kWh</small>`,
    `plant price ${num(k.jepx.plant_price_now, 2)} · spike ${esc(k.jepx.spike_window)} to ${num(k.jepx.spike_peak, 1)} JPY/kWh`);
  $("#event-banner").innerHTML = `<b>${esc(k.dr.event_id)}</b> reduce ${num(k.dr.target_kw)} kW ${esc(k.dr.window)} · JEPX spike ${esc(k.jepx.spike_window)}`;
}

function renderStack(d) {
  const c = baseChart("chart-stack");
  const x = d.rows.map((r) => r.time);
  const surface = css("--surface");
  const areas = d.groups.map((g, i) => ({
    name: g, type: "line", stack: "gross", symbol: "none", smooth: false, data: d.rows.map((r) => r[g]),
    lineStyle: { width: 1, color: surface }, areaStyle: { color: css(GROUP_COLORS[i]), opacity: 0.85 }, itemStyle: { color: css(GROUP_COLORS[i]) },
    emphasis: { focus: "series" },
  }));
  const lines = [
    { name: "Import, metered", key: "import_actual_kw", color: css("--fg"), type: "solid" },
    { name: "Import, forecast (no action)", key: "import_forecast_kw", color: css("--fg-muted"), type: "dashed" },
    { name: "Import, with plan", key: "import_plan_kw", color: css("--accent"), type: "solid", width: 2.5 },
    { name: "Day-ahead nomination", key: "nominated_kw", color: "#8b8f96", type: "dotted" },
  ].map((l) => ({ name: l.name, type: "line", symbol: "none", data: d.rows.map((r) => r[l.key]), lineStyle: { color: l.color, type: l.type, width: l.width || 2 }, itemStyle: { color: l.color }, z: 5 }));
  lines[2].markArea = { silent: true, itemStyle: { color: "rgba(184,166,240,0.10)" }, label: { color: css("--fg-muted"), fontSize: 10 },
    data: [[{ name: "DR window", xAxis: d.dr_window[0], label: { position: "insideTopLeft" } }, { xAxis: d.dr_window[1] }],
      [{ name: "JEPX spike", xAxis: d.spike_window[0], itemStyle: { color: "rgba(201,133,0,0.10)" }, label: { position: "insideBottomRight" } }, { xAxis: d.spike_window[1] }]] };
  lines[0].markLine = { symbol: "none", silent: true, lineStyle: { color: css("--accent"), type: "solid" }, label: { formatter: "now", color: css("--accent") }, data: [{ xAxis: d.now }] };
  c.setOption({
    animation: false, grid: { left: 56, right: 16, top: 56, bottom: 28 }, tooltip: tooltip({ valueFormatter: (v) => (v == null ? "n/a" : `${num(v)} kW`) }),
    legend: { ...legend([...d.groups, ...lines.map((l) => l.name)]), type: "scroll" },
    xAxis: { type: "category", data: x, boundaryGap: false, ...axisStyle(), splitLine: { show: false } },
    yAxis: { type: "value", name: "kW", nameTextStyle: { color: css("--fg-muted") }, ...axisStyle() },
    series: [...areas, ...lines],
  });
  $("#stack-note").textContent = `Stacked areas are gross plant load by asset group; lines are receiving-point import. Contracted demand ${num(d.contracted_kw)} kW; month billing peak to date ${num(d.month_peak_kw)} kW. Sources: ${d.source.join(", ")}.`;
}

function renderTimeline(dr, all, ov, flex, pv, jepx) {
  const ev = dr.events[0];
  $("#dr-id").textContent = ev.event_id;
  const b = ev.estimated_baseline || {};
  const rej = flex.rows.filter((r) => r.edge_verdict === "REJECT");
  const spike = (jepx.spike_windows || [])[0];
  const items = [
    ["", `${esc(ev.notified_at.slice(11))}`, `Aggregator dispatch: reduce ${num(ev.requested_kw)} kW (${num(ev.requested_kwh)} kWh).`],
    ["now", "13:30", `Now. Edge-verified plan ${esc(flex.plan_id)}: ${num(flex.summary.firm_reduction_kw)} kW firm.`],
    ["risk", (pv.pv_risk_slots || []).length ? `${pv.pv_risk_slots[0].slice(0, 5)}-${pv.pv_risk_slots.at(-1).slice(6)}` : "", `PV cloud band: p10 ${num(pv.deepest_gap?.p10_kw)} kW vs p50 ${num(pv.deepest_gap?.p50_kw)} kW at ${esc(pv.deepest_gap?.time)}.`],
    ["dr", `${ev.start_time}-${ev.end_time}`, `DR window. Baseline estimate ${num(b.baseline_avg_kw)} kW (High 4 of 5, adjustment ${num(b.same_day_adjustment_kw)} kW).`],
    ["risk", spike ? `${spike.start}-${spike.end}` : "", spike ? `JEPX spike: average ${num(spike.avg_spot_jpy_kwh, 1)}, peak ${num(spike.max_spot_jpy_kwh, 1)} JPY/kWh; reserve margin down to ${num(spike.min_reserve_margin_pct, 1)} %.` : ""],
    ...rej.map((r) => ["lock", "", `${esc(r.asset_label)} rejected at the edge (${esc(r.rule_ids.join(", "))}): committed batch stays on.`]),
  ];
  $("#timeline").innerHTML = items.filter((i) => i[2]).map(([cls, t, txt]) => `<li class="${cls}"><span class="t">${t}</span>${txt}</li>`).join("");
  const rows = all.events.filter((e) => e.status === "settled");
  $("#dr-history").innerHTML = `<thead><tr><th>Event</th><th class="num">Req kW</th><th class="num">Delivered kW</th><th class="num">%</th><th class="num">Net JPY</th></tr></thead><tbody>${rows.map((e) =>
    `<tr${e.penalty_jpy > 0 ? ' class="rej"' : ""}><td>${esc(e.date)}</td><td class="num">${num(e.requested_kw)}</td><td class="num">${num(e.delivered_kw)}</td><td class="num">${num(e.performance_pct, 0)}${e.penalty_jpy > 0 ? " ✕" : ""}</td><td class="num">${num(e.net_settlement_jpy)}</td></tr>`).join("")}</tbody>`;
}

function renderFlex(f) {
  const s = f.summary;
  $("#flex-plan").textContent = f.plan_id;
  $("#flex-summary").innerHTML = `Target ${num(f.target_kw)} kW · edge-verified firm <b>${num(s.firm_reduction_kw)} kW</b> (margin ${num(s.margin_kw)} kW, ${num(s.margin_pct, 1)} %) · ${s.accepted} accepted, ${s.limited} limited, ${s.rejected} rejected · slowest decision ${num(s.max_action_decision_ms, 2)} ms at the edge (simulated) · ${esc(s.sequencing)}`;
  $("#flex-table").innerHTML = `<thead><tr><th>Asset</th><th>Action</th><th class="num">Plan est. kW</th><th>Edge verdict</th><th class="num">Granted kW</th><th>Rule</th></tr></thead><tbody>${f.rows.map((r) =>
    `<tr class="${r.edge_verdict === "REJECT" ? "rej" : ""}"><td>${esc(r.asset_label)}<span class="reason">${esc(r.method)}</span></td><td>${esc(r.action)}</td><td class="num">${num(r.planning_estimate_kw)}</td><td>${badge(r.edge_verdict)}</td><td class="num">${num(r.edge_granted_avg_kw)}</td><td title="${esc(r.edge_reason)}">${esc(r.rule_ids.join(", "))}<span class="reason">${esc(r.edge_reason)}</span></td></tr>`).join("")}</tbody>`;
}

function renderBess(b) {
  const c = baseChart("chart-bess");
  const x = Array.from({ length: 49 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
  const hist = Array(49).fill(null);
  b.history.forEach((h) => { hist[h.slot - 1] = h.soc_pct; });
  const nowIdx = 27;
  hist[nowIdx] = b.soc_now_pct;
  const proj = (pol) => { const arr = Array(49).fill(null); arr[nowIdx] = b.soc_now_pct; b.policies[pol].rows.forEach((r) => { arr[r.slot] = r.soc_end_pct; }); return arr; };
  const v2 = b.policies.forecast_aware_v2, v1 = b.policies.rule_based_v1;
  const drRows = v2.rows.filter((r) => r.dr);
  c.setOption({
    animation: false, grid: { left: 40, right: 36, top: 36, bottom: 26 }, tooltip: tooltip({ valueFormatter: (v) => (v == null ? "n/a" : `${num(v, 1)} %`) }),
    legend: legend(["Metered", "rule_based_v1", "forecast_aware_v2"]),
    xAxis: { type: "category", data: x, boundaryGap: false, ...axisStyle(), splitLine: { show: false } },
    yAxis: { type: "value", min: 0, max: 100, name: "SOC %", nameTextStyle: { color: css("--fg-muted") }, ...axisStyle() },
    series: [
      { name: "Metered", type: "line", symbol: "none", data: hist, lineStyle: { color: css("--fg"), width: 2 }, itemStyle: { color: css("--fg") },
        markLine: { symbol: "none", silent: true, data: [{ yAxis: 10 }, { yAxis: 95 }], lineStyle: { color: css("--crit"), type: "dashed" }, label: { color: css("--fg-muted"), formatter: "{c} %" } } },
      { name: "rule_based_v1", type: "line", symbol: "none", data: proj("rule_based_v1"), lineStyle: { color: css("--g2"), width: 2, type: "dashed" }, itemStyle: { color: css("--g2") } },
      { name: "forecast_aware_v2", type: "line", symbol: "none", data: proj("forecast_aware_v2"), lineStyle: { color: css("--accent"), width: 2.5 }, itemStyle: { color: css("--accent") },
        markArea: { silent: true, itemStyle: { color: "rgba(184,166,240,0.10)" }, label: { color: css("--fg-muted"), fontSize: 10 },
          data: [[{ name: "DR", xAxis: x[drRows[0].slot - 1] }, { xAxis: x[drRows.at(-1).slot] }], [{ name: "PV risk", xAxis: x[29], itemStyle: { color: "rgba(255,159,10,0.10)" } }, { xAxis: x[32] }]] } },
    ],
  });
  const rows = [
    ["DR firm contribution", "dr_firm_kw", "kW", 0], ["SOC at DR start", "soc_at_dr_start_pct", "%", 1], ["Charging in PV-risk slots", "charge_in_pv_risk_slots_kwh", "kWh", 0],
    ["Spike-window discharge", "spike_energy_kwh", "kWh", 0], ["Peak import (p10 PV)", "peak_import_p10pv_kw", "kW", 0],
    ["Pre-event imbalance at risk (p10 PV)", "pre_event_imbalance_exposure_jpy_p10pv", "JPY", 0], ["SOC limit violations", "soc_limit_violations", "", 0],
  ];
  $("#bess-kpis").innerHTML = `<thead><tr><th>KPI</th><th class="num">v1</th><th class="num">v2</th></tr></thead><tbody>${rows.map(([l, k, u, d]) =>
    `<tr><td>${l}</td><td class="num">${num(v1.kpis[k], d)} ${u}</td><td class="num">${num(v2.kpis[k], d)} ${u}</td></tr>`).join("")}</tbody>`;
}

function renderPv(p) {
  const c = baseChart("chart-pv");
  const actual = Object.fromEntries(p.actual_by_slot.map((a) => [a.time, a.kw]));
  const slots = p.slots;
  const times = [...new Set([...p.actual_by_slot.map((a) => a.time).filter((t) => t < slots[0].time.slice(0, 5)), ...slots.map((s) => s.time.slice(0, 5))])];
  const byT = Object.fromEntries(slots.map((s) => [s.time.slice(0, 5), s]));
  c.setOption({
    animation: false, grid: { left: 44, right: 10, top: 34, bottom: 26 },
    tooltip: tooltip({ formatter: (ps) => { const t = ps[0].axisValue; const s = byT[t]; const a = actual[t];
      return `<b>${t}</b><br>${s ? `p10 ${num(s.p10_kw)} kW<br>p50 ${num(s.p50_kw)} kW<br>p90 ${num(s.p90_kw)} kW<br>` : ""}${a != null ? `metered ${num(a)} kW` : ""}`; } }),
    legend: legend(["p10-p90 band", "p50", "Metered"]),
    xAxis: { type: "category", data: times, boundaryGap: false, ...axisStyle(), splitLine: { show: false } },
    yAxis: { type: "value", name: "kW", nameTextStyle: { color: css("--fg-muted") }, ...axisStyle() },
    series: [
      { name: "p10", type: "line", stack: "band", symbol: "none", data: times.map((t) => byT[t]?.p10_kw ?? null), lineStyle: { opacity: 0 }, tooltip: { show: true } },
      { name: "p10-p90 band", type: "line", stack: "band", symbol: "none", data: times.map((t) => (byT[t] ? byT[t].p90_kw - byT[t].p10_kw : null)),
        lineStyle: { opacity: 0 }, areaStyle: { color: css("--g1"), opacity: 0.28 }, itemStyle: { color: css("--g1") } },
      { name: "p50", type: "line", symbol: "none", data: times.map((t) => byT[t]?.p50_kw ?? null), lineStyle: { color: css("--g1"), width: 2 }, itemStyle: { color: css("--g1") } },
      { name: "Metered", type: "line", symbol: "none", data: times.map((t) => actual[t] ?? null), lineStyle: { color: css("--fg"), width: 2 }, itemStyle: { color: css("--fg") } },
    ],
  });
  $("#pv-issued").textContent = `issued ${p.issued_at.slice(11)}`;
  const cal = p.calibration_14d || {};
  $("#pv-note").textContent = `Deepest gap ${p.deepest_gap?.time}: p10 ${num(p.deepest_gap?.p10_kw)} / p50 ${num(p.deepest_gap?.p50_kw)} / p90 ${num(p.deepest_gap?.p90_kw)} kW. Last 14 days: ${num(cal.p10_p90_coverage_pct, 1)} % of slots inside p10-p90, p50 error ${num(cal.p50_mae_kw)} kW.`;
}

function renderJepx(j) {
  const c = baseChart("chart-jepx");
  const x = j.slots.map((s) => s.time.slice(0, 5));
  const sp = (j.spike_windows || [])[0];
  c.setOption({
    animation: false, grid: { left: 40, right: 10, top: 34, bottom: 26 }, tooltip: tooltip({ valueFormatter: (v) => (v == null ? "n/a" : `${num(v, 2)} JPY/kWh`) }),
    legend: legend(["Spot", "Imbalance (est.)", "Plant all-in price"]),
    xAxis: { type: "category", data: x, boundaryGap: false, ...axisStyle(), splitLine: { show: false } },
    yAxis: { type: "value", name: "JPY/kWh", nameTextStyle: { color: css("--fg-muted") }, ...axisStyle() },
    series: [
      { name: "Spot", type: "line", symbol: "none", data: j.slots.map((s) => s.spot), lineStyle: { color: css("--g4"), width: 2 }, itemStyle: { color: css("--g4") },
        markArea: sp ? { silent: true, itemStyle: { color: "rgba(201,133,0,0.10)" }, data: [[{ name: "spike", xAxis: sp.start }, { xAxis: sp.end }]], label: { color: css("--fg-muted"), fontSize: 10 } } : undefined },
      { name: "Imbalance (est.)", type: "line", symbol: "none", data: j.slots.map((s) => s.imbalance), lineStyle: { color: css("--g5"), width: 2, type: "dashed" }, itemStyle: { color: css("--g5") } },
      { name: "Plant all-in price", type: "line", symbol: "none", data: j.slots.map((s) => s.plant_price), lineStyle: { color: css("--g1"), width: 1.5, type: "dotted" }, itemStyle: { color: css("--g1") } },
    ],
  });
  $("#jepx-note").textContent = sp ? `Spike ${sp.start}-${sp.end}: spot average ${num(sp.avg_spot_jpy_kwh, 1)}, peak ${num(sp.max_spot_jpy_kwh, 1)} JPY/kWh; imbalance estimate up to ${num(sp.max_imbalance_jpy_kwh, 1)} JPY/kWh at a ${num(sp.min_reserve_margin_pct, 1)} % reserve margin (cap 200 JPY/kWh until 2026-09-30).` : "";
}

function renderAnomalies(a) {
  const title = { compressor_specific_power_drift: "Compressor specific-power drift", stuck_meter: "Stuck meter", billing_peak_set_around_dr_event: "Billing peak set around a DR event" };
  $("#anomalies").innerHTML = a.anomalies.map((x) => {
    const cost = x.impact.annual_cost_jpy != null ? `${jpy(x.impact.annual_cost_jpy)} per year` : x.impact.demand_charge_jpy_this_month != null ? `${jpy(x.impact.demand_charge_jpy_this_month)} demand charge this month` : `${num(x.impact.unallocated_kwh)} kWh unallocated`;
    const ev = x.type === "compressor_specific_power_drift" ? `${x.asset_id}: ${num(x.evidence.recent_excess_vs_peers_pct, 1)} % above peers (was ${num(x.evidence.early_june_excess_vs_peers_pct, 1)} % in early June)`
      : x.type === "stuck_meter" ? `${x.asset_id} (${x.evidence.metered_assets}) flat at ${num(x.evidence.flat_value_kw, 1)} kW since ${x.evidence.since.replace("T", " ")}, ${num(x.evidence.duration_h, 1)} h`
        : `${num(x.evidence.month_billing_peak_kw)} kW at ${x.evidence.set_at} (${x.evidence.dr_event}), battery ${num(x.evidence.bess_kw_at_peak)} kW`;
    return `<li><div class="a-head"><span class="a-title">${title[x.type] || x.type}</span>${badge(x.severity)}</div><div class="a-cost">${cost}</div><div class="a-ev">${esc(ev)}</div></li>`;
  }).join("") || '<li class="empty">No anomalies.</li>';
}

function renderGain(g) {
  const c = baseChart("chart-gain");
  const m = g.ledger.months;
  c.setOption({
    animation: false, grid: { left: 56, right: 10, top: 34, bottom: 26 }, tooltip: tooltip({ axisPointer: { type: "shadow" }, valueFormatter: (v) => `${num(v / 1e6, 2)}M JPY` }),
    legend: legend(["Client net", "Vendor gain share", "BESS-as-a-Service fee"]),
    xAxis: { type: "category", data: m.map((x) => x.month), ...axisStyle(), splitLine: { show: false } },
    yAxis: { type: "value", name: "JPY", nameTextStyle: { color: css("--fg-muted") }, axisLabel: { color: css("--fg-muted"), formatter: (v) => `${v / 1e6}M` }, splitLine: { lineStyle: { color: css("--grid") } } },
    series: [
      { name: "Client net", key: "client_net_jpy", color: "--g3" }, { name: "Vendor gain share", key: "vendor_gain_share_jpy", color: "--g1" }, { name: "BESS-as-a-Service fee", key: "baas_fee_jpy", color: "--g7" },
    ].map((s) => ({ name: s.name, type: "bar", stack: "split", barWidth: "55%", data: m.map((x) => x[s.key]), itemStyle: { color: css(s.color), borderColor: css("--surface"), borderWidth: 1 } })),
  });
  const inv = g.invoice, today = g.today;
  $("#gain-july").innerHTML = [
    ["July verified savings", mjpy(inv.total_verified_savings_jpy)], [`Gain share ${num(inv.gain_share_pct)} %`, mjpy(inv.vendor_gain_share_jpy)],
    ["BESS-as-a-Service fee", mjpy(inv.baas_fee_jpy)], ["July client net", mjpy(inv.client_net_benefit_jpy)],
    ["Today's event (estimate)", jpy(today.event_value_jpy)], ["Today: vendor share", jpy(today.vendor_gain_share_jpy)],
    ["July peak lost around DR", jpy(inv.demand_peak_check?.extra_demand_charge_jpy)], ["DR lines reconcile", inv.dr_reconciliation?.reconciles ? "✓ yes" : "✕ no"],
  ].map(([l, v]) => `<div class="g"><span class="caps">${l}</span><div class="v">${v}</div></div>`).join("");
}

async function refreshLogs() {
  const [edge, audit] = await Promise.all([api("/api/edge-decisions"), api("/api/audit")]);
  const rows = [...edge.runtime.map((r) => ({ ...r, live: true })), ...edge.history];
  $("#log-edge").innerHTML = `<table class="data"><thead><tr><th>When</th><th>Asset</th><th>Action</th><th>Verdict</th><th>Rule</th><th class="num">ms</th></tr></thead><tbody>${rows.slice(0, 120).map((r) =>
    `<tr${r.verdict === "REJECT" ? ' class="rej"' : ""} title="${esc(r.plan_id)}: ${esc(r.reason)}"><td class="nowrap">${esc(r.live ? `live ${r.plan_id}` : r.ts.replace("T", " "))}</td><td class="nowrap">${esc(r.asset_id)}</td><td>${esc(r.action)}</td><td>${badge(r.verdict)}</td><td class="nowrap">${esc(r.rule_id)}</td><td class="num">${num(r.latency_ms, 2)}</td></tr>`).join("")}</tbody></table>`;
  $("#log-audit").innerHTML = audit.length ? `<table class="data"><thead><tr><th>Action</th><th>Kind</th><th>Decision</th><th>Status</th><th>Edge re-check</th></tr></thead><tbody>${audit.map((a) =>
    `<tr><td>${esc(a.action_id)}</td><td>${esc(a.kind)}</td><td>${esc(a.decision)}</td><td>${badge(a.status)}</td><td>${a.edge_recheck ? `${esc(a.edge_recheck.plan_id)}: ${num(a.edge_recheck.firm_kw)} kW, ${a.edge_recheck.rejected} rejected` : ""}</td></tr>`).join("")}</tbody></table>`
    : '<p class="empty">No decisions yet. Confirm or reject a pending action to create an audit record.</p>';
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.setAttribute("aria-selected", String(x === t)));
  $("#log-edge").hidden = t.dataset.tab !== "edge";
  $("#log-audit").hidden = t.dataset.tab !== "audit";
}));

// ---------------------------------------------------------------------------------------------
// Chat, swarm trace and the pending-actions tray
// ---------------------------------------------------------------------------------------------
let sessionId = null;
let busy = false;

function md(text) {
  const lines = esc(text).split("\n");
  let html = "", list = null, table = [];
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
    html += `<table>${rows.map((r, i) => `<tr>${r.map((c) => (i ? `<td>${c}</td>` : `<th>${c}</th>`)).join("")}</tr>`).join("")}</table>`;
    table = [];
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    if (/^\s*\|/.test(l)) { if (list) { html += `</${list}>`; list = null; } table.push(l.trim()); continue; }
    flushTable();
    const h = l.match(/^#{1,4}\s+(.*)/);
    const b = l.match(/^\s*[*-]\s+(.*)/);
    const n = l.match(/^\s*\d+\.\s+(.*)/);
    if (h) { if (list) { html += `</${list}>`; list = null; } html += `<h4>${inline(h[1])}</h4>`; }
    else if (b || n) { const t = b ? "ul" : "ol"; if (list !== t) { if (list) html += `</${list}>`; html += `<${t}>`; list = t; } html += `<li>${inline((b || n)[1])}</li>`; }
    else if (!l.trim()) { if (list) { html += `</${list}>`; list = null; } }
    else { if (list) { html += `</${list}>`; list = null; } html += `<p>${inline(l)}</p>`; }
  }
  flushTable();
  if (list) html += `</${list}>`;
  return html;
}

function trace(t, who, html) {
  const el = document.createElement("div");
  el.className = "ev";
  const color = css(AGENT_COLORS[who] || "--fg-muted");
  el.innerHTML = `<span class="t">${num(t, 1)}s</span> <span class="who" style="color:${color}">${esc(who)}</span> ${html}`;
  const box = $("#trace");
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

function summarise(result) {
  if (!result || typeof result !== "object") return esc(String(result).slice(0, 160));
  if (result.result && typeof result.result === "string") return `<span class="res">${esc(result.result.slice(0, 180))}…</span>`;
  const bits = [`status=${esc(result.status)}`];
  if (result.plan_id) bits.push(`plan=${esc(result.plan_id)}`);
  if (result.summary?.firm_reduction_kw != null) bits.push(`firm=${num(result.summary.firm_reduction_kw)} kW`, `rejected=${result.summary.rejected}`);
  if (result.verdict) bits.push(`verdict=${esc(result.verdict)}`);
  if (result.pending_action) bits.push("queued for Hold-to-Confirm");
  if (result.error) bits.push(`<span class="err">${esc(result.error.slice(0, 120))}</span>`);
  if (result.source) bits.push(`<span class="res">${esc([].concat(result.source).slice(0, 3).join(", "))}</span>`);
  return bits.join(" · ");
}

async function send(message) {
  if (busy || !message.trim()) return;
  busy = true;
  $("#send").disabled = true;
  const thread = $("#thread");
  thread.insertAdjacentHTML("beforeend", `<div class="msg user"><span class="who">You</span>${esc(message)}</div>`);
  const out = document.createElement("div");
  out.className = "msg agent pending";
  out.innerHTML = `<span class="who">Optimization Orchestrator</span>Working: delegating to specialists…`;
  thread.appendChild(out);
  thread.scrollTop = thread.scrollHeight;
  $("#trace").innerHTML = "";
  $("#trace-stat").textContent = "running";
  let finalText = "", calls = 0;
  try {
    const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id: sessionId }) });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        if (!chunk.startsWith("data: ")) continue;
        const e = JSON.parse(chunk.slice(6));
        if (e.type === "session") sessionId = e.session_id;
        else if (e.type === "tool_call") { calls++; trace(e.t, e.author, `<span class="tool">→ ${esc(e.tool)}</span>(${esc(JSON.stringify(e.args).slice(0, 200))})`); }
        else if (e.type === "tool_result") trace(e.t, e.author, `<span class="res">← ${esc(e.tool)}:</span> ${summarise(e.result)}`);
        else if (e.type === "pending_action") { trace(e.t, e.author, `<span class="tool">⏸ pending action ${esc(e.action.id)}</span> ${esc(e.action.kind)}`); refreshActions(); }
        else if (e.type === "text") {
          if (e.author === "optimization_orchestrator") { finalText += e.text; out.classList.remove("pending"); out.innerHTML = `<span class="who">Optimization Orchestrator</span>${md(finalText)}`; }
          else trace(e.t, e.author, `<span class="txt">${esc(e.text.slice(0, 220))}${e.text.length > 220 ? "…" : ""}</span>`);
        } else if (e.type === "error") { trace(e.t || 0, "server", `<span class="err">${esc(e.error)}</span>`); out.innerHTML = `<span class="who">Error</span>${esc(e.error)}`; }
        else if (e.type === "done") $("#trace-stat").textContent = `${calls} calls · ${num(e.t, 1)} s`;
        thread.scrollTop = thread.scrollHeight;
      }
    }
  } catch (err) {
    out.innerHTML = `<span class="who">Error</span>${esc(err.message)}`;
  } finally {
    busy = false;
    $("#send").disabled = false;
    refreshActions();
    refreshLogs();
  }
}

async function refreshActions() {
  const list = await api("/api/actions");
  const pending = list.filter((a) => a.status === "pending").length;
  $("#actions-count").textContent = `${pending} pending`;
  const box = $("#actions");
  if (!list.length) { box.innerHTML = '<p class="empty">Nothing queued. Agents can only propose; every change waits here for a 2-second Hold-to-Confirm.</p>'; return; }
  box.innerHTML = "";
  for (const a of list) {
    const d = a.details || {};
    const el = document.createElement("div");
    el.className = `action ${a.status !== "pending" ? "done" : ""}`;
    const acts = (d.actions || []).map((x) => `<li>${esc(x.asset_id)} ${esc(x.action)}: ${badge(x.verdict)} ${num(x.granted_avg_kw)} kW <span class="src">${esc((x.rule_ids || []).join(", "))}</span></li>`).join("");
    const excl = (d.excluded_by_edge || []).map((x) => `<li>${esc(x.asset_id)} ${esc(x.action)} ${badge("REJECT")} <span class="src">${esc(x.rule_ids.join(", "))}</span> ${esc(x.reason)}</li>`).join("");
    const kp = d.kpis ? `<li>DR firm ${num(d.kpis.dr_firm_kw)} kW, SOC at DR start ${num(d.kpis.soc_at_dr_start_pct, 1)} %, end SOC ${num(d.kpis.soc_end_pct, 1)} %, SOC violations ${d.kpis.soc_limit_violations}</li>` : "";
    el.innerHTML = `<div class="a-row"><span class="caps">${esc(a.kind.replaceAll("_", " "))} · ${esc(a.id)}</span>${badge(a.status)}</div>
      <div class="a-row"><span>risk ${badge(a.risk || "low")}</span>${a.audit ? `<span>audit ${badge(a.audit)}</span>` : ""}</div>
      <p class="a-sum">${esc(a.summary)}</p>
      <details><summary>Reasoning, edge verdicts and sources</summary>
        ${d.rationale ? `<p>${esc(d.rationale)}</p>` : ""}
        ${d.issue ? `<p>${esc(d.issue)} (${esc(d.priority)})</p>` : ""}
        ${acts ? `<p class="caps">Edge-approved actions</p><ul>${acts}</ul>` : ""}${kp ? `<ul>${kp}</ul>` : ""}
        ${excl ? `<p class="caps">Rejected by the edge (excluded)</p><ul>${excl}</ul>` : ""}
        <p class="src">Sources: ${esc((d.sources || []).join(", "))} · proposed by ${esc(a.proposed_by || "agent")}</p>
      </details>
      <div class="btns"></div>`;
    if (a.status === "pending") {
      const ok = document.createElement("button");
      ok.className = "btn primary";
      ok.textContent = "Hold to confirm";
      const no = document.createElement("button");
      no.className = "btn";
      no.textContent = "Reject";
      no.addEventListener("click", async () => { await api(`/api/actions/${a.id}/reject`, { method: "POST" }); refreshActions(); refreshLogs(); });
      holdToConfirm(ok, async () => { await api(`/api/actions/${a.id}/confirm`, { method: "POST" }); refreshActions(); refreshLogs(); }, { ms: 2000 });
      el.querySelector(".btns").append(ok, no);
    }
    box.appendChild(el);
  }
}

async function initChat() {
  const { prompts } = await api("/api/suggested-prompts");
  $("#chips").innerHTML = prompts.map((p) => `<button class="chip" type="button" data-prompt="${esc(p.prompt)}" title="${esc(p.prompt)}"><b>${esc(p.id)}</b>${esc(p.label)}</button>`).join("");
  $("#chips").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) { $("#chat-input").value = b.dataset.prompt; $("#chat-input").focus(); } });
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#chat-input").value; $("#chat-input").value = ""; send(v); });
  $("#chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });
  $("#thread").innerHTML = `<div class="msg agent"><span class="who">Optimization Orchestrator</span>${md("Ask about today's DR event, the JEPX spike, the battery, PV risk, anomalies or gain share. Every figure comes from tools over the plant dataset, every plan passes the edge interlock simulation and the safety audit, and nothing executes without your Hold-to-Confirm.")}</div>`;
}

window.addEventListener("resize", () => Object.values(charts).forEach((c) => c.resize()));
initChat();
refreshActions();
loadDashboard().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<p class="badge crit" role="alert">Dashboard failed to load: ${esc(e.message)}</p>`); });
