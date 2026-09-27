/* Workspace · Cockpit: the v1 operational panels in the v2 language. Every figure from /api. */
(async function () {
  const { esc, num, css } = UI;
  await Shell.mountNav("workspace", "/workspace/index.html");
  const root = document.getElementById("page");
  const verdictBadge = (v) => `<span class="badge ${v === "ACCEPT" ? "b-ok" : v === "LIMIT" ? "b-warn" : "b-crit"}">${v === "ACCEPT" ? "✓" : v === "LIMIT" ? "◐" : "✕"} ${esc(v)}</span>`;
  try {
    const [ov, stack, flex, bs, pv, jp, an, agents, meta, edge, audit] = await Promise.all([
      Shell.api("/api/overview"), Shell.api("/api/load-stack"), Shell.api("/api/flex"), Shell.api("/api/bess"), Shell.api("/api/pv"), Shell.api("/api/jepx"),
      Shell.api("/api/anomalies"), Shell.api("/api/agents"), Shell.api("/api/meta"), Shell.api("/api/edge-decisions"), Shell.api("/api/audit")]);
    const k = ov.kpis, hitl = agents.agents.filter((a) => a.hitl_required).length;
    root.innerHTML = `<section class="hero reveal"><div class="eyebrow">Workspace · Cockpit</div><h1>Today's event, the plant, and what waits for you</h1>
      <p class="lede">${num(agents.agents.length)} agents you can talk to · ${num(hitl)} of them propose actions that need your sign-off · <span id="pending-n">…</span> waiting now.</p></section>
      <section><div class="kpirow">
        <div class="card kpi reveal"><div class="card-cap">Plant load now</div><div class="metric" id="k-load"></div><div class="sub">${num(100 * k.plant_load.value_kw / k.plant_load.contracted_kw, 1)} % of ${num(k.plant_load.contracted_kw)} kW contracted; month peak ${num(k.plant_load.month_peak_kw)} kW</div></div>
        <div class="card kpi reveal"><div class="card-cap">DR, edge-verified</div><div class="metric" id="k-dr"></div><div class="sub">target ${num(k.dr.target_kw)} kW ${esc(k.dr.window)}; margin ${num(k.dr.margin_kw)} kW (${num(k.dr.margin_pct, 1)} %); ${num(k.dr.rejected)} rejected at the edge</div></div>
        <div class="card kpi reveal"><div class="card-cap">Battery state of charge</div><div class="metric" id="k-soc"></div><div class="sub">${esc(k.bess.mode)} ${num(Math.abs(k.bess.power_kw))} kW under ${esc(k.bess.policy)}</div></div>
        <div class="card kpi reveal"><div class="card-cap">PV now</div><div class="metric" id="k-pv"></div><div class="sub">p50 ${num(k.pv.p50_kw)} kW for this half hour</div></div>
        <div class="card kpi reveal"><div class="card-cap">JEPX Tokyo now</div><div class="metric" id="k-jepx"></div><div class="sub">spike ${esc(k.jepx.spike_window)} to ${num(k.jepx.spike_peak, 1)} JPY/kWh</div></div>
      </div></section>
      <section><div class="bento">
        <div class="card c8 reveal"><div class="card-cap">Plant load by asset group<span class="spacer"></span><span class="pill">kW</span></div><div class="chart tall" id="c-stack" role="img" aria-label="Plant load by asset group with import, forecast, plan and nomination"></div>
          <p class="muted" style="font-size:12.5px">Areas: gross load by group. Lines: metered import, forecast with no action, import with the plan, and the day-ahead nomination.</p></div>
        <div class="card c4 reveal"><div class="card-cap">Needs your sign-off<span class="spacer"></span><span class="badge b-warn" id="q-n">…</span></div><div id="queue"></div></div>
        <div class="card c7 reveal"><div class="card-cap">Flexible loads and edge verdicts<span class="spacer"></span><span class="mono dim">${esc(flex.plan_id)}</span></div>
          <p class="muted" style="font-size:13px">Firm <b>${num(flex.summary.firm_reduction_kw)} kW</b> against ${num(flex.target_kw)} kW · ${num(flex.summary.accepted)} accepted, ${num(flex.summary.limited)} limited, ${num(flex.summary.rejected)} rejected · slowest decision ${num(flex.summary.max_action_decision_ms, 2)} ms (simulated)</p>
          <div class="table-scroll"><table class="data"><thead><tr><th>Asset</th><th>Action</th><th>Plan kW</th><th>Edge verdict</th><th>Granted kW</th><th>Rule</th></tr></thead><tbody>${flex.rows.map((r) =>
            `<tr class="${r.edge_verdict === "REJECT" ? "rej" : ""}"><td>${esc(r.asset_label)}<span class="reason">${esc(r.method)}</span></td><td>${esc(r.action)}</td><td class="num">${num(r.planning_estimate_kw)}</td>`
            + `<td>${verdictBadge(r.edge_verdict)}</td><td class="num">${num(r.edge_granted_avg_kw)}</td><td class="mono" style="font-size:11px">${esc(r.rule_ids.join(", "))}<span class="reason">${esc(r.edge_reason)}</span></td></tr>`).join("")}</tbody></table></div></div>
        <div class="card c5 reveal"><div class="card-cap">Battery state-of-charge plan<span class="spacer"></span><span class="pill">%</span></div><div class="chart" id="c-soc" role="img" aria-label="Battery state of charge"></div>
          <table class="data"><thead><tr><th></th><th>Current rules</th><th>Forecast-aware</th></tr></thead><tbody>
          ${[["DR firm", "dr_firm_kw", "kW", 0], ["SOC at DR start", "soc_at_dr_start_pct", "%", 1], ["Charging in PV-risk slots", "charge_in_pv_risk_slots_kwh", "kWh", 0], ["SOC limit violations", "soc_limit_violations", "", 0]]
            .map(([l, key, u, dp]) => `<tr><td>${l}</td><td class="num">${num(bs.policies.rule_based_v1.kpis[key], dp)} ${u}</td><td class="num">${num(bs.policies.forecast_aware_v2.kpis[key], dp)} ${u}</td></tr>`).join("")}</tbody></table></div>
        <div class="card c4 reveal"><div class="card-cap">PV p10 / p50 / p90<span class="spacer"></span><span class="pill">kW</span></div><div class="chart" id="c-pv" role="img" aria-label="PV forecast band"></div>
          <p class="muted" style="font-size:12.5px">Deepest gap ${esc(pv.deepest_gap.time)}: p10 ${num(pv.deepest_gap.p10_kw)} kW vs p50 ${num(pv.deepest_gap.p50_kw)} kW.</p></div>
        <div class="card c4 reveal"><div class="card-cap">JEPX Tokyo and imbalance<span class="spacer"></span><span class="pill">JPY/kWh</span></div><div class="chart" id="c-jepx" role="img" aria-label="Spot and imbalance prices"></div></div>
        <div class="card c4 reveal"><div class="card-cap">Asset health, this week</div>${an.anomalies.map((a) => {
          const cost = a.impact.annual_cost_jpy != null ? `${num(a.impact.annual_cost_jpy)} JPY a year` : a.impact.demand_charge_jpy_this_month != null ? `${num(a.impact.demand_charge_jpy_this_month)} JPY this month` : `${num(a.impact.unallocated_kwh)} kWh unallocated`;
          return `<div class="queue-item"><div class="row"><span class="badge ${a.severity === "high" ? "b-crit" : "b-warn"}">${esc(a.severity)}</span><b>${esc(a.asset_id)}</b></div><p>${esc(a.type.replaceAll("_", " "))}: <b>${esc(cost)}</b></p><div class="dim" style="font-size:12px">${esc(a.likely_cause)}</div></div>`;
        }).join("")}</div>
        <div class="card c6 reveal"><div class="card-cap">Edge decisions</div><div class="table-scroll" style="max-height:320px"><table class="data"><thead><tr><th>When</th><th>Asset</th><th>Action</th><th>Verdict</th><th>Rule</th><th>ms</th></tr></thead><tbody>${[...edge.runtime.map((r) => ({ ...r, live: true })), ...edge.history].slice(0, 60).map((r) =>
          `<tr class="${r.verdict === "REJECT" ? "rej" : ""}"><td class="mono" style="font-size:11px">${esc(r.live ? "live" : r.ts.replace("T", " "))}</td><td>${esc(r.asset_id)}</td><td>${esc(r.action)}</td><td>${verdictBadge(r.verdict)}</td><td class="mono" style="font-size:11px">${esc(r.rule_id)}</td><td class="num">${num(r.latency_ms, 2)}</td></tr>`).join("")}</tbody></table></div></div>
        <div class="card c6 reveal"><div class="card-cap">Audit log</div>${audit.length ? `<table class="data"><thead><tr><th>Action</th><th>Decision</th><th>Status</th><th>Edge re-check</th></tr></thead><tbody>${audit.map((a) =>
          `<tr><td class="mono" style="font-size:11px">${esc(a.action_id)}</td><td>${esc(a.decision)}</td><td>${esc(a.status)}</td><td>${a.edge_recheck ? `${num(a.edge_recheck.firm_kw)} kW firm, ${num(a.edge_recheck.rejected)} rejected` : ""}</td></tr>`).join("")}</tbody></table>`
          : '<p class="muted">No decisions yet. Approving or rejecting an action writes a record here.</p>'}</div>
      </div></section>
      ${Shell.provenance(UI.provRows(meta, [...new Set([...stack.source, ...flex.source, ...bs.source, ...jp.source])]))}`;

    Motion.countUp(document.getElementById("k-load"), k.plant_load.value_kw, { unit: "kW" });
    Motion.countUp(document.getElementById("k-dr"), k.dr.firm_kw, { unit: "kW" });
    Motion.countUp(document.getElementById("k-soc"), k.bess.soc_pct, { dp: 1, unit: "%" });
    Motion.countUp(document.getElementById("k-pv"), k.pv.now_kw, { unit: "kW" });
    Motion.countUp(document.getElementById("k-jepx"), k.jepx.spot_now, { dp: 2, unit: "JPY/kWh" });
    const q = document.getElementById("queue");
    const refresh = async () => { const l = await UI.renderQueue(q, document.getElementById("q-n")); document.getElementById("pending-n").textContent = String(l.filter((a) => a.status === "pending").length); };
    await refresh();

    const P = UI.palette(), G = [...P, css("--bx")];
    const c1 = UI.chart(document.getElementById("c-stack"));
    if (c1) {
      const x = stack.rows.map((r) => r.time);
      c1.setOption({ animation: false, grid: { left: 56, right: 12, top: 56, bottom: 28 }, tooltip: UI.tooltip((v) => (v == null ? "n/a" : `${num(v)} kW`)),
        legend: UI.legend([...stack.groups, "Import, metered", "Import, no action", "Import, with plan", "Nomination"]),
        xAxis: { type: "category", data: x, boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", ...UI.axis() },
        series: [...stack.groups.map((g, i) => ({ name: g, type: "line", stack: "gross", symbol: "none", data: stack.rows.map((r) => r[g]), lineStyle: { width: 1, color: css("--surface") },
          areaStyle: { color: G[i % G.length], opacity: 0.8 }, itemStyle: { color: G[i % G.length] } })),
          { name: "Import, metered", type: "line", symbol: "none", data: stack.rows.map((r) => r.import_actual_kw), lineStyle: { color: css("--fg"), width: 2 }, itemStyle: { color: css("--fg") },
            markLine: { symbol: "none", silent: true, lineStyle: { color: css("--accent") }, label: { formatter: "now", color: css("--accent") }, data: [{ xAxis: stack.now }] } },
          { name: "Import, no action", type: "line", symbol: "none", data: stack.rows.map((r) => r.import_forecast_kw), lineStyle: { color: css("--fg-muted"), width: 1.5, type: "dashed" }, itemStyle: { color: css("--fg-muted") } },
          { name: "Import, with plan", type: "line", symbol: "none", data: stack.rows.map((r) => r.import_plan_kw), lineStyle: { color: css("--accent"), width: 2.5 }, itemStyle: { color: css("--accent") },
            markArea: { silent: true, itemStyle: { color: "rgba(196,176,232,0.10)" }, label: { color: css("--fg-muted"), fontSize: 10, position: "insideTopLeft" }, data: [[{ name: "DR window", xAxis: stack.dr_window[0] }, { xAxis: stack.dr_window[1] }]] } },
          { name: "Nomination", type: "line", symbol: "none", data: stack.rows.map((r) => r.nominated_kw), lineStyle: { color: css("--fg-dim"), width: 1, type: "dotted" }, itemStyle: { color: css("--fg-dim") } }] });
    }
    const c2 = UI.chart(document.getElementById("c-soc"));
    if (c2) {
      const r1 = bs.policies.rule_based_v1.rows, r2 = bs.policies.forecast_aware_v2.rows;
      const hx = bs.history.map((h) => h.time), x = [...hx, ...r2.map((r) => r.time)];
      const pad = (arr) => [...Array(hx.length).fill(null), ...arr];
      c2.setOption({ animation: false, grid: { left: 40, right: 36, top: 36, bottom: 28 }, tooltip: UI.tooltip((v) => (v == null ? "n/a" : `${num(v, 1)} %`)),
        legend: UI.legend(["Metered", "Current rules", "Forecast-aware"]),
        xAxis: { type: "category", data: x, boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", min: 0, max: 100, ...UI.axis() },
        series: [{ name: "Metered", type: "line", symbol: "none", data: [...bs.history.map((h) => h.soc_pct), ...Array(r2.length).fill(null)], lineStyle: { color: css("--fg"), width: 2 }, itemStyle: { color: css("--fg") },
          markLine: { symbol: "none", silent: true, data: [{ yAxis: bs.limits.soc_min_pct }, { yAxis: bs.limits.soc_max_pct }], lineStyle: { color: css("--critical"), type: "dashed" }, label: { color: css("--fg-muted"), formatter: "{c} %" } } },
          { name: "Current rules", type: "line", symbol: "none", data: pad(r1.map((r) => r.soc_end_pct)), lineStyle: { color: P[1], width: 2, type: "dashed" }, itemStyle: { color: P[1] } },
          { name: "Forecast-aware", type: "line", symbol: "none", data: pad(r2.map((r) => r.soc_end_pct)), lineStyle: { color: P[3], width: 2.5 }, itemStyle: { color: P[3] } }] });
    }
    const c3 = UI.chart(document.getElementById("c-pv"));
    if (c3) {
      const s = pv.slots, x = s.map((q2) => q2.time.slice(0, 5));
      c3.setOption({ animation: false, grid: { left: 44, right: 10, top: 34, bottom: 28 },
        tooltip: { ...UI.tooltip(), formatter: (ps) => { const q2 = s[ps[0].dataIndex]; return `<b>${q2.time}</b><br>p10 ${num(q2.p10_kw)} kW<br>p50 ${num(q2.p50_kw)} kW<br>p90 ${num(q2.p90_kw)} kW`; } },
        legend: UI.legend(["p10 to p90", "p50"]), xAxis: { type: "category", data: x, boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", ...UI.axis() },
        series: [{ name: "lo", type: "line", stack: "b", symbol: "none", data: s.map((q2) => q2.p10_kw), lineStyle: { opacity: 0 } },
          { name: "p10 to p90", type: "line", stack: "b", symbol: "none", data: s.map((q2) => q2.p90_kw - q2.p10_kw), lineStyle: { opacity: 0 }, areaStyle: { color: P[0], opacity: 0.22 }, itemStyle: { color: P[0] } },
          { name: "p50", type: "line", symbol: "none", data: s.map((q2) => q2.p50_kw), lineStyle: { color: P[0], width: 2 }, itemStyle: { color: P[0] } }] });
    }
    const c4 = UI.chart(document.getElementById("c-jepx"));
    if (c4) {
      const sw = jp.spike_windows[0];
      c4.setOption({ animation: false, grid: { left: 40, right: 10, top: 34, bottom: 28 }, tooltip: UI.tooltip((v) => `${num(v, 2)} JPY/kWh`), legend: UI.legend(["Spot", "Imbalance (estimate)"]),
        xAxis: { type: "category", data: jp.slots.map((s) => s.time.slice(0, 5)), boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", ...UI.axis() },
        series: [{ name: "Spot", type: "line", symbol: "none", data: jp.slots.map((s) => s.spot), lineStyle: { color: P[1], width: 2 }, itemStyle: { color: P[1] },
          markArea: sw ? { silent: true, itemStyle: { color: "rgba(224,185,120,0.08)" }, data: [[{ xAxis: sw.start }, { xAxis: sw.end }]] } : undefined },
          { name: "Imbalance (estimate)", type: "line", symbol: "none", data: jp.slots.map((s) => s.imbalance), lineStyle: { color: P[4], width: 2, type: "dashed" }, itemStyle: { color: P[4] } }] });
    }
  } catch (e) {
    root.innerHTML = `<div class="note crit"><strong>Data unavailable</strong><br>${esc(e.message)}</div>`;
  }
  Motion.reveal();
})();
