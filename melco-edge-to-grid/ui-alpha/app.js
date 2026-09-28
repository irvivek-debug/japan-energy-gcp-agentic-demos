/* UI alpha: the CEO story of the Factory Energy Copilot. Six hash-routed screens on the same /api as v1 and v2.
 * Every figure is fetched here and placed into window.F; the story text (story.js) only carries {{placeholders}}. */
window.ALPHA = {
  product: "Factory Energy Copilot", company: "Mitsubishi Electric", avatar: "EM",
  screens: [{ id: "why", label: "Why now" }, { id: "system", label: "The system" }, { id: "call", label: "The call" }, { id: "who", label: "Who changes" }, { id: "team", label: "The team" }, { id: "built", label: "How it's built" }],
};

window.App = (function () {
  const A = () => window.Alpha, esc = (v) => window.Alpha.esc(v), S = () => window.STORY;
  const D = {}, F = {};
  window.D = D; window.F = F;
  const LABEL = { optimization_orchestrator: "The lead", market_intelligence_agent: "Market and weather", factory_interlock_agent: "Plant floor",
    bess_strategy_agent: "Battery", asset_health_agent: "Asset health", gain_share_agent: "Gain share", safety_auditor: "The reviewer" };
  const n0 = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const tpl = (t) => String(t ?? "").replace(/\{\{(\w+)\}\}/g, (_, k) => F[k] !== undefined ? `<b>${F[k]}</b>` : '<span class="gap-value">NOT IN THE DATA</span>');
  const txt = (t) => String(t ?? "").replace(/\{\{(\w+)\}\}/g, (_, k) => (F[k] || "NOT IN THE DATA").replace(/<[^>]+>/g, ""));
  function md(s) {
    const lines = String(s || "").split("\n"); let out = "", inList = false, inTable = false;
    const inline = (x) => esc(x).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
    for (const raw of lines) {
      const l = raw.trim();
      if (/^\|/.test(l)) { if (/^\|[\s:-]+\|/.test(l)) continue; if (!inTable) { out += "<table>"; inTable = true; } out += `<tr>${l.split("|").slice(1, -1).map((c) => `<td>${inline(c.trim())}</td>`).join("")}</tr>`; continue; }
      if (inTable) { out += "</table>"; inTable = false; }
      if (/^[-*] /.test(l)) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${inline(l.slice(2))}</li>`; continue; }
      if (inList) { out += "</ul>"; inList = false; }
      if (/^#{1,6} /.test(l)) out += `<h4>${inline(l.replace(/^#+ /, ""))}</h4>`;
      else if (l) out += `<p>${inline(l)}</p>`;
    }
    if (inList) out += "</ul>"; if (inTable) out += "</table>";
    return out;
  }
  const promptText = (id) => (D.prompts.prompts.find((p) => p.id === id) || {}).prompt || "";
  const techDrawer = (title, rows) => `<details class="drawer"><summary>${esc(title)}<span class="hint">for the engineer in the room</span></summary><div class="body"><div class="kv-card">${rows.map(([k, v]) => `<div class="kv-row"><span class="kv-key">${esc(k)}</span><span class="kv-val" style="text-align:left;font-weight:500;max-width:70%">${esc(v)}</span></div>`).join("")}</div></div></details>`;
  const prizeLine = (branch, line) => { const b = (D.prize.branches || []).find((x) => x.code === branch); const l = b && b.lines[line]; return l ? { html: A().range(l.low, l.high, " M JPY", 1), basis: l.basis, mech: l.mechanism, unit: l.unit } : null; };

  /* ---- figures: every {{key}} in story.js resolves here, from /api ---- */
  function buildFigures() {
    const k = D.overview.kpis, rf = (key) => D.research.facts[key];
    const fx = (key, unit, dp) => { const f = rf(key); F[key] = f ? A().fig(f.value, unit === undefined ? ` ${f.unit}` : unit, dp === undefined ? 2 : dp) : undefined; };
    F.dr_target = A().fig(k.dr.target_kw, " kW", 0); F.dr_firm = A().fig(k.dr.firm_kw, " kW", 0); F.dr_margin_pct = A().fig(k.dr.margin_pct, " %", 1);
    F.dr_window = esc(k.dr.window.replace("-", " to ")); F.plant_load = A().fig(k.plant_load.value_kw, " kW", 0); F.contract_kw = A().fig(k.plant_load.contracted_kw, " kW", 0);
    F.plant_pct = A().fig(100 * k.plant_load.value_kw / k.plant_load.contracted_kw, " %", 1); F.month_peak = A().fig(k.plant_load.month_peak_kw, " kW", 0);
    F.bess_soc = A().fig(k.bess.soc_pct, " %", 1); F.pv_now = A().fig(k.pv.now_kw, " kW", 0); F.spot_now = A().fig(k.jepx.spot_now, " JPY/kWh", 2); F.spike_peak = A().fig(k.jepx.spike_peak, " JPY/kWh", 1);
    F.spike_window = esc(k.jepx.spike_window.replace("-", " to "));
    fx("tokyo_spot_fy2026", " JPY/kWh"); F.spot_fy2026 = F.tokyo_spot_fy2026; fx("tokyo_spot_fy2025", " JPY/kWh"); F.spot_fy2025 = F.tokyo_spot_fy2025;
    fx("imbalance_cap_now", " JPY/kWh", 0); F.imb_cap_now = F.imbalance_cap_now; fx("imbalance_cap_oct", " JPY/kWh", 0); F.imb_cap_oct = F.imbalance_cap_oct;
    fx("gate_closure_min", " min", 0); fx("weathernext3_members", " members", 0); fx("vppdr_tertiary2_fy2025h1", " JPY/ΔkW·h", 2);
    const bp = D.timeline.billing_peaks.find((b) => b.month === "2026-08") || {}, bj = D.timeline.billing_peaks.find((b) => b.month === "2026-07") || {};
    F.aug_extra_kw = A().fig(bp.extra_billing_demand_kw, " kW", 0); F.aug_extra_jpy = A().fig(bp.extra_demand_charge_jpy, " JPY", 0); F.jul_extra_jpy = A().fig(bj.extra_demand_charge_jpy, " JPY", 0);
    const an = Object.fromEntries((D.anomalies.anomalies || []).map((a) => [a.type, a]));
    const ac = an.compressor_specific_power_drift, m27 = an.stuck_meter;
    F.ac04_excess_pct = ac ? A().fig(ac.evidence.recent_excess_vs_peers_pct, " %", 1) : undefined; F.ac04_june_pct = ac ? A().fig(ac.evidence.early_june_excess_vs_peers_pct, " %", 1) : undefined;
    F.ac04_cost = ac ? A().fig(ac.impact.annual_cost_jpy / 1e6, " M JPY", 1) : undefined; F.m27_hours = m27 ? A().fig(m27.evidence.duration_h, " h", 1) : undefined;
    const pr = D.bess.policies.rule_based_v1.kpis, pf = D.bess.policies.forecast_aware_v2.kpis;
    F.bess_firm_rule = A().fig(pr.dr_firm_kw, " kW", 0); F.bess_firm_fa = A().fig(pf.dr_firm_kw, " kW", 0); F.bess_soc_dr = A().fig(pf.soc_at_dr_start_pct, " %", 1); F.bess_soc_rule = A().fig(pr.soc_at_dr_start_pct, " %", 1);
    F.imb_exposure_rule = A().fig(pr.pre_event_imbalance_exposure_jpy_p10pv, " JPY", 0); F.imb_exposure_fa = A().fig(pf.pre_event_imbalance_exposure_jpy_p10pv, " JPY", 0);
    const fs = D.flex.summary;
    F.flex_planning = A().fig(D.flex.rows.reduce((s, r) => s + (r.planning_estimate_kw || 0), 0), " kW", 0); F.flex_actions = A().fig(fs.actions_evaluated, "", 0);
    F.edge_accepted = A().fig(fs.accepted, "", 0); F.edge_limited = A().fig(fs.limited, "", 0); F.edge_rejected = A().fig(fs.rejected, "", 0); F.edge_ms = A().fig(fs.max_action_decision_ms, " ms", 2); F.edge_rebound = A().fig(fs.rebound_kwh_after_window, " kWh", 0);
    const past = D.dr_events.events.find((e) => e.event_id === "DR-20260722") || D.dr_events.events.filter((e) => e.status === "settled").sort((a, b) => a.performance_pct - b.performance_pct)[0];
    F.past_perf = A().fig(past.performance_pct, " %", 0); F.past_penalty = A().fig(past.penalty_jpy, " JPY", 0); F.past_requested = A().fig(past.requested_kw, " kW", 0); F.past_delivered = A().fig(past.delivered_kw, " kW", 0);
    F.past_soc = A().fig(34, " %", 0);
    F.past_soc = past.notes && /(\d+)\s*%/.test(past.notes) ? A().fig(Number(past.notes.match(/(\d+)\s*%/)[1]), " %", 0) : '<span class="gap-value">NOT IN THE DATA</span>';
    const inv = D.gain.invoice;
    F.july_client_net = A().fig(inv.client_net_benefit_jpy / 1e6, " M JPY", 2); F.july_gain_share = A().fig(inv.vendor_gain_share_jpy / 1e6, " M JPY", 2); F.july_verified = A().fig(inv.total_verified_savings_jpy / 1e6 || inv.verified_savings_jpy / 1e6, " M JPY", 2);
    F.july_fee = A().fig(inv.baas_fee_jpy / 1e6, " M JPY", 1);
    const risk = (D.pv.slots || []).filter((s) => s.pv_risk_slot), worst = risk.length ? risk.reduce((a, b) => (a.p10_kw < b.p10_kw ? a : b)) : null;
    F.pv_p10_min = worst ? A().fig(worst.p10_kw, " kW", 1) : undefined; F.pv_p50_at = worst ? A().fig(worst.p50_kw, " kW", 1) : undefined; F.pv_cal = D.pv.calibration_14d ? A().fig(D.pv.calibration_14d.p10_p90_coverage_pct, " %", 1) : undefined;
    const sw = (D.jepx.spike_windows || [])[0] || {};
    F.imb_spike = A().fig(sw.max_imbalance_jpy_kwh, " JPY/kWh", 1); F.reserve_min = A().fig(sw.min_reserve_margin_pct, " %", 1);
    F.audit_verdict = "<span class=\"badge badge-optimal\">APPROVED</span>";
    F.rules_n = A().fig(D.meta.tables.find((t) => t.name === "interlock_rules").rows, "", 0); F.tables_n = A().fig(D.meta.tables.length, "", 0);
    F.agents_n = A().fig(D.agents.agents.length, "", 0);
    F.adk_pass = `${D.proof.adk.pass_first} / ${D.proof.adk.total}`; F.ground_pass = D.proof.grounding.summary ? `${D.proof.grounding.summary.grounded} / ${D.proof.grounding.summary.total}` : "NOT IN THE DATA";
    F.safety_pass = D.proof.safety.summary ? `${D.proof.safety.summary.passed} / ${D.proof.safety.summary.total}` : "NOT IN THE DATA"; F.pytest_pass = D.proof.pytest ? `${D.proof.pytest.passed} passed` : "NOT IN THE DATA";
  }

  /* ---- shared: ask an agent live in the drawer, with the recorded run as the badged fallback ---- */
  let session = null;
  function ask(agentId, question) {
    const label = LABEL[agentId] || agentId;
    const body = A().drawer.open(`Ask: ${label}`, `<div class="ask-q"><b>The question</b>${esc(question)}</div>
      <div class="ask-status" id="ask-status"><span class="badge badge-live on"><span class="dot"></span>live</span><span>The lead is asking the team…</span></div>
      <div class="terminal ask-trace" id="ask-trace"></div><div class="ask-a" id="ask-a"></div><div id="ask-props"></div>
      <div class="ask-actions" id="ask-actions"></div>`, "Live agent run on this server");
    const trace = body.querySelector("#ask-trace"), ans = body.querySelector("#ask-a"), status = body.querySelector("#ask-status");
    let final = "", failed = null, calls = 0, t = 0; const props = [];
    const line = (s, cls = "") => { trace.insertAdjacentHTML("beforeend", `<div class="${cls}">${esc(s)}</div>`); trace.scrollTop = trace.scrollHeight; };
    A().stream("/api/chat", question, (e) => {
      if (e.t) t = e.t;
      if (e.type === "session") session = e.session_id;
      else if (e.type === "tool_call") { calls++; line(`${e.t}s ${LABEL[e.author] || e.author} → ${LABEL[e.tool] || e.tool}`, LABEL[e.tool] ? "blue" : ""); }
      else if (e.type === "tool_result") { const r = e.result || {}; if (!LABEL[e.tool]) line(`${e.t}s ← ${e.tool}: ${r.status || ""}${r.verdict ? " " + r.verdict : ""}`, r.status === "error" ? "crit" : "dim"); }
      else if (e.type === "pending_action") { props.push(e.action); line(`${e.t}s queued ${e.action.kind} for sign-off`, "warn"); }
      else if (e.type === "text" && e.author === "optimization_orchestrator") { final += e.text; ans.innerHTML = md(final); }
      else if (e.type === "text") line(`${e.t}s ${LABEL[e.author] || e.author}: ${e.text.slice(0, 140)}`, "dim");
      else if (e.type === "error") { failed = e.error; line(`error: ${e.error}`, "crit"); }
      else if (e.type === "done") {
        if (final) status.innerHTML = `<span class="badge badge-live"><span class="dot"></span>live</span><span>Answered in ${t} s with ${calls} tool calls.</span>`;
        else { status.innerHTML = `<span class="badge badge-critical">no answer</span><span>${esc(failed || "The lead ended without an answer.")}</span>`; body.querySelector("#ask-actions").innerHTML = `<button class="btn" id="ask-rec">Play the recorded run (replay)</button>`; body.querySelector("#ask-rec").onclick = () => recorded(agentId); }
        if (props.length) body.querySelector("#ask-props").innerHTML = props.map((p) => `<div class="ask-proposal"><b>Waiting for sign-off:</b> ${esc(p.summary)}<br><span class="cite">Open The call, beat 8, to hold and approve; or the cockpit in version 2.</span></div>`).join("");
      }
    }, session).catch((err) => { status.innerHTML = `<span class="badge badge-critical">no answer</span><span>${esc(err.message)}</span>`; body.querySelector("#ask-actions").innerHTML = `<button class="btn" id="ask-rec">Play the recorded run (replay)</button>`; body.querySelector("#ask-rec").onclick = () => recorded(agentId); });
  }
  async function recorded(agentId) {
    const label = LABEL[agentId] || agentId;
    const body = A().drawer.open(`Recorded run: ${label}`, '<div class="loading">Reading eval/results</div>', "Replay from the evaluation evidence");
    try {
      const r = await A().api(`/api/alpha/recorded?agent=${encodeURIComponent(agentId)}`);
      const p = r.probe;
      body.innerHTML = `<div class="ask-status"><span class="badge badge-replay"><span class="dot"></span>replay</span><span>${esc(r.label)}</span></div>
        ${p ? `<div class="ask-q"><b>The question, as recorded</b>${esc(p.prompt)}</div><div class="ask-a">${md(p.reply)}</div>
        <div class="drawer-label">Grounding checks at the time</div><div class="kv-card">${(p.checks || []).map((c) => `<div class="kv-row"><span class="kv-key">${esc(c.name || c.check || c.id || "check")}</span><span class="kv-val">${esc(c.result || c.status || (c.ok === true ? "PASS" : c.ok === false ? "FAIL" : ""))}</span></div>`).join("") || '<div class="kv-row"><span class="kv-key">Verdict</span><span class="kv-val">' + esc(p.verdict) + "</span></div>"}</div>` : '<div class="gap-value">NOT IN THE DATA</div>'}
        <div class="drawer-label">Evaluation cases for this set</div><div class="kv-card">${r.cases.map((c) => `<div class="kv-row"><span class="kv-key">${esc(c.id)}</span><span class="kv-val">${esc(c.first)}${c.latency_s ? ` · ${Number(c.latency_s).toFixed(0)} s` : ""}</span></div>`).join("")}</div>
        <div class="cite">${esc(r.source.join(" · "))}</div>`;
    } catch (err) { body.innerHTML = `<div class="gap-value">NOT IN THE DATA</div><p>${esc(err.message)}</p>`; }
  }

  /* ---- screen 1: why now ---- */
  function timelineChart() {
    const rows = D.timeline.rows.filter((r) => r.verified_m_jpy !== null), mk = D.timeline.marker;
    const W = 900, H = 260, L = 44, R = 150, T = 24, B = 40, n = rows.length;
    const max = Math.max(...rows.map((r) => r.verified_m_jpy)) * 1.15;
    const x = (i) => L + (i * (W - L - R)) / Math.max(1, n - 1), y = (v) => T + (H - T - B) * (1 - v / max);
    const path = (key) => rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[key] || 0).toFixed(1)}`).join(" ");
    const ticks = [0, max / 2, max].map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="lbl" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(1)}</text>`).join("");
    const mi = mk ? rows.findIndex((r) => r.month === mk.month) : -1;
    const marker = mi >= 0 ? `<line class="tl-marker-line" x1="${x(mi)}" x2="${x(mi)}" y1="${T}" y2="${H - B}"/><circle class="tl-marker-dot" cx="${x(mi)}" cy="${y(rows[mi].verified_m_jpy)}" r="6"/><text class="tl-marker-text" x="${mi > n / 2 ? x(mi) - 10 : x(mi) + 10}" y="${T + 12}" text-anchor="${mi > n / 2 ? "end" : "start"}">${esc(mk.text)}</text>` : "";
    const last = rows[n - 1];
    return `<div class="chart-card"><div class="chart-legend"><span class="legend-item"><span class="legend-dot" style="background:var(--c1)"></span>Verified savings</span><span class="legend-item"><span class="legend-dot" style="background:var(--c2)"></span>Demand charge avoided</span></div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Verified savings by month">${ticks}<line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
      ${rows.map((r, i) => `<text class="lbl" x="${x(i)}" y="${H - B + 18}" text-anchor="middle">${esc(r.label)}</text>`).join("")}
      <path class="series" d="${path("demand_charge_avoided_m_jpy")}" style="stroke:var(--c2)"/><path class="series" d="${path("verified_m_jpy")}" style="stroke:var(--c1)"/>
      <text class="tl-end-label" x="${x(n - 1) + 10}" y="${y(last.verified_m_jpy) + 4}" style="fill:var(--c1)">${last.verified_m_jpy.toFixed(2)} M JPY verified</text>
      <text class="tl-end-label" x="${x(n - 1) + 10}" y="${y(last.demand_charge_avoided_m_jpy || 0) + 4}" style="fill:var(--c2)">${(last.demand_charge_avoided_m_jpy || 0).toFixed(2)} M JPY peak</text>${marker}</svg>
      <div class="cite" style="margin-top:8px">${mk ? `Marked: ${esc(mk.label)}, ${esc(mk.text)}. ` : ""}M JPY per month · ${esc(D.timeline.source.map((s) => s.replace(/^.*\./, "")).join(" · "))}</div></div>`;
  }
  function renderWhy(pane) {
    const s = S().why;
    pane.innerHTML = `<div class="eyebrow">${esc(s.eyebrow)}</div><h1 class="hero-title">${esc(s.hero)}</h1><p class="hero-desc">${tpl(s.lede)} <span class="cite">${esc(D.research.facts.tokyo_spot_fy2026.cite)} · /api/overview</span></p>
      <h2 class="section-title">${esc(s.timeline_title)}</h2><p class="section-subtitle">${esc(s.timeline_sub)}</p>${timelineChart()}
      <h2 class="section-title">${esc(s.headwinds_title)}</h2><div class="headwinds-grid">${s.headwinds.map((h) => `<div class="headwind-card"><div class="headwind-header"><span>${esc(h.name)}</span><span class="badge badge-critical">headwind</span></div>
        <div class="headwind-val-row"><span class="headwind-val">${F[h.fig] || '<span class="gap-value">NOT IN THE DATA</span>'}</span></div><div class="headwind-baseline">${tpl(h.baseline)}</div><div class="headwind-desc">${tpl(h.desc)}</div>
        <div class="bar-track"><div class="fill" style="width:${Math.round(h.bar * 100)}%"></div></div><span class="cite">${esc(h.cite)}</span></div>`).join("")}</div>
      <h2 class="section-title">${esc(s.levers_title)}</h2><div class="levers-grid">${s.levers.map((l) => `<div class="lever-col ${l.status === "active" ? "highlight" : ""}"><div class="lever-tag">${esc(l.tag)}</div><div class="lever-desc">${tpl(l.desc)}</div>
        <div class="lever-status"><span class="${l.status === "active" ? "status-active" : "status-exhausted"}">${l.status === "active" ? "The lever left" : "Spent"}</span><span>${tpl(l.label)}</span></div></div>`).join("")}</div>
      <h2 class="section-title">${esc(s.outcomes_title)}</h2><div class="outcomes">${s.outcomes.map((o) => { const p = prizeLine(o.branch, o.line); return `<div class="outcome"><div class="outcome-label">${esc(o.label)}</div><div class="outcome-val">${p ? p.html : '<span class="gap-value">NOT IN THE DATA</span>'}</div><div class="outcome-sub">${p ? esc(p.basis) : "no figure is held"}</div></div>`; }).join("")}</div>
      <p class="cite" style="margin-top:10px">${esc(D.prize.note)} · /api/prize</p>
      ${techDrawer("Technical detail", [["Timeline", "/api/alpha/timeline: savings_ledger by month, dr_events settlements, site_load_30min peaks, tariff_contract demand charge"], ["Headwinds", "/api/alpha/timeline billing_peaks (C.billing_peak_check), /api/anomalies, /api/bess policy KPIs, /api/research"], ["Outcomes", "/api/prize branch lines (ranges, never points), same figures as version 2 chapter 3"], ["Research", esc(D.research.source_document)]])}
      <div class="disclaimer">${esc(S().disclaimer)}</div>`;
  }

  /* ---- screen 2: the system ---- */
  function spark(vals, cls) {
    const v = vals.filter((x) => x !== null && x !== undefined); if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = vals.map((x, i) => x === null || x === undefined ? null : [(i / (vals.length - 1)) * 100, 32 - ((x - lo) / span) * 28]).filter(Boolean);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    return `<svg class="sparkline" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true"><path class="area ${cls}" d="${d} L100,34 L0,34 Z"/><path class="${cls}" d="${d}"/></svg>`;
  }
  function nodeDrawer(n) {
    const st = n.state === "crit" ? '<span class="badge badge-critical">needs attention</span>' : n.state === "watch" ? '<span class="badge badge-warning">watched</span>' : '<span class="badge badge-optimal">normal</span>';
    const html = `<div class="ask-status">${st}<span>${esc(n.sub)}</span></div>
      <div><div class="drawer-label"><span>Live readings</span><span class="mono" style="color:var(--m3-primary)">${esc(D.overview.demo_now.replace("T", " "))}</span></div><div class="kv-card">${n.readings.filter(Boolean).map((r) => `<div class="kv-row"><span class="kv-key">${esc(r.k)}</span><span class="kv-val">${typeof r.v === "number" ? A().fig(r.v, r.unit ? ` ${r.unit}` : "", Number.isInteger(r.v) ? 0 : 1) : esc(r.v)}</span></div>`).join("")}</div></div>
      <div><div class="drawer-label">The edge rules that protect it</div>${n.rules.length ? `<div class="rule-list">${n.rules.map((r) => `<div class="rule-item"><span class="rid">${esc(r.rule_id)}</span>${esc(r.text)} <span class="badge badge-stable" style="font-size:9px;padding:1px 6px">${esc(r.severity)}</span><div class="why">${esc(r.why)}</div></div>`).join("")}</div>` : '<div class="cite">No interlock applies here; the market and the aggregator are read, never written.</div>'}</div>
      ${n.plan ? `<div><div class="drawer-label"><span>Today's plan, edge verdicts</span><span class="mono">${esc(D.schematic.plan_id)}</span></div><div class="kv-card">${n.plan.map((p) => `<div class="verdict-row"><span class="mono">${esc(p.asset_id)}</span><span class="v ${esc(p.verdict)}">${esc(p.verdict)}</span><span>${esc(p.action)}${p.granted_avg_kw ? ` · ${n0(p.granted_avg_kw)} kW` : ""}<div class="why">${esc(p.reason)}</div></span></div>`).join("")}</div></div>` : ""}
      <div><div class="drawer-label">Who watches this</div><div class="chip-row">${n.watchers.map((w) => `<span class="chip live">${esc(w)}</span>`).join("")}<span class="chip">The edge</span></div></div>
      ${n.note ? `<p class="cite">${esc(n.note)}</p>` : ""}`;
    A().drawer.open(n.label, html, D.schematic.zones.find((z) => z.id === n.zone).title);
  }
  function renderSystem(pane) {
    const s = S().system, strip = Object.fromEntries(D.strip.series.map((x) => [x.key, x])), last48 = (k) => (strip[k] ? strip[k].values.slice(-48) : []);
    const k = D.overview.kpis, an = Object.fromEntries((D.anomalies.anomalies || []).map((a) => [a.type, a]));
    const cards = [
      { name: "Grid import", cls: "", badge: ["badge-stable", "NORMAL"], a: ["Now", F.plant_load], b: ["Month peak", F.month_peak], sp: last48("import") },
      { name: "Compressor AC-04", cls: "crit", badge: ["badge-critical", "LEAK"], a: ["Above peers", F.ac04_excess_pct], b: ["Cost a year", F.ac04_cost], sp: last48("compressed_air") },
      { name: "Meter M-27", cls: "watch", badge: ["badge-warning", "FROZEN"], a: ["Frozen for", F.m27_hours], b: ["Unallocated", an.stuck_meter ? A().fig(an.stuck_meter.impact.unallocated_kwh, " kWh", 0) : undefined], sp: last48("m27") },
      { name: "Rooftop PV", cls: "watch", badge: ["badge-warning", "CLOUD BAND"], a: ["Now", F.pv_now], b: ["p10 at 15:00", F.pv_p10_min], sp: last48("pv") },
      { name: "Battery", cls: "", badge: ["badge-stable", k.bess.mode.toUpperCase()], a: ["State of charge", F.bess_soc], b: ["Firm at 16:30, forecast-aware", F.bess_firm_fa], sp: last48("bess_soc") },
      { name: "JEPX Tokyo spot", cls: "watch", badge: ["badge-warning", "SPIKE"], a: ["Now", F.spot_now], b: ["Peak this evening", F.spike_peak], sp: last48("jepx") },
    ];
    pane.innerHTML = `<div class="schematic-top"><div><div class="eyebrow">${esc(s.eyebrow)}</div><h1 class="hero-title" style="margin-bottom:6px">${esc(s.hero)}</h1><p class="hero-desc" style="margin-bottom:0">${esc(s.lede)}</p></div>
      <div class="hero-side"><span class="badge badge-critical" style="align-self:flex-start"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:var(--m3-critical)"></span>${esc(D.schematic.nodes.filter((n) => n.state === "crit").length)} needs attention · ${esc(D.schematic.nodes.filter((n) => n.state === "watch").length)} watched</span>
      <div class="legend-row"><span><span class="sw crit"></span>attention</span><span><span class="sw watch"></span>watched</span><span><span class="sw hot"></span>in today's plan</span><span class="cite">click a box</span></div></div></div>
      <div class="schematic-card" id="schematic"></div>
      <h2 class="section-title">${esc(s.telemetry_title)}</h2><div class="telemetry-grid">${cards.map((c) => `<div class="telemetry-card ${c.cls}"><div class="telemetry-head"><span>${esc(c.name)}</span><span class="badge ${c.badge[0]}">${esc(c.badge[1])}</span></div>
        <div class="telemetry-values"><div><div class="t-label">${esc(c.a[0])}</div><div class="t-num ${c.cls === "crit" ? "crit" : ""}">${c.a[1] || '<span class="gap-value">NOT IN THE DATA</span>'}</div></div><div><div class="t-label">${esc(c.b[0])}</div><div class="t-num">${c.b[1] || '<span class="gap-value">NOT IN THE DATA</span>'}</div></div></div>${spark(c.sp, c.cls)}<div class="cite">last 48 hours</div></div>`).join("")}</div>
      ${techDrawer("Technical detail", [["Twin", "/api/alpha/schematic: assets, meters, telemetry_5min (latest interval by class), plc_tags_snapshot, interlock_rules, today's edge simulation per asset"], ["Sparklines", "/api/strip hourly series, last 48 points"], ["States", "red from /api/anomalies (AC-04 drift), amber from committed batches (plc_tags_snapshot), the frozen meter, the PV risk band and the spike window"], ["Systems of record", esc(D.schematic.systems_of_record.map((x) => `${x.name} (${x.sub})`).join("; "))]])}
      <div class="disclaimer">${esc(S().disclaimer)}</div>`;
    window.Schematic.render(pane.querySelector("#schematic"), D.schematic, nodeDrawer);
    pane.querySelector("#sor-note").textContent = s.sor_note;
  }

  /* ---- screen 4: who changes ---- */
  function renderWho(pane) {
    const s = S().who, personas = D.personas.personas, agents = Object.fromEntries(D.agents.agents.map((a) => [a.agent_id, a]));
    pane.innerHTML = `<div class="eyebrow">${esc(s.eyebrow)}</div><h1 class="hero-title" style="margin-bottom:6px">${esc(s.hero)}</h1><p class="hero-desc" style="margin-bottom:20px">${esc(s.lede)}</p>
      <div class="persona-strip" id="persona-strip" role="tablist">${personas.map((p, i) => `<button type="button" class="persona-tab ${i === 0 ? "active" : ""}" data-p="${esc(p.id)}" role="tab"><span class="avatar">${esc(p.initials)}</span>${esc(p.title)}</button>`).join("")}</div>
      <div class="card" id="persona-card"></div>
      ${techDrawer("Technical detail", [["Personas", "/api/personas (docs/PRD.md section 4); the before and after text is story copy, the figures are from /api"], ["Squad badges", "SIGN-OFF where the agent can propose an action that needs a hold (hitl_required); ADVISORY otherwise; ARBITER for the reviewer and the edge"], ["Ask it", "Opens the live agent in the drawer with the persona's first suggested question"]])}
      <div class="disclaimer">${esc(S().disclaimer)}</div>`;
    const show = (p) => {
      const c = s.personas[p.id] || {}, prompts = p.questions.map((q) => D.prompts.prompts.find((x) => x.id === q)).filter(Boolean);
      const badge = (id) => id === "safety_auditor" ? '<span class="badge badge-arbiter">ARBITER</span>' : agents[id] && agents[id].hitl_required ? '<span class="badge badge-signoff">SIGN-OFF</span>' : '<span class="badge badge-advisory">ADVISORY</span>';
      pane.querySelector("#persona-card").innerHTML = `<div class="persona-identity"><div class="persona-portrait">${esc(p.initials)}</div><div><div class="chip-row" style="margin-bottom:6px"><span class="badge badge-primary">${esc(p.local_title)}</span></div><div class="persona-title">${esc(p.title)}</div><div class="persona-sub">${esc(p.one_line)}</div>
        <div class="chip-row">${(c.metrics || []).map(([k, l]) => `<span class="metric-chip">${F[k] || "NOT IN THE DATA"} <span style="font-weight:500">${esc(l)}</span></span>`).join("")}</div></div></div>
        <div class="note-box"><div class="lab">Core job to be done</div><div class="txt" style="font-family:var(--font-serif);font-size:18px">${esc(p.governing_question)}</div></div>
        <div class="persona-grid"><div class="reality-box today"><div class="reality-head">Today's broken reality</div><p>${tpl(c.today || p.day_in_life)}</p></div><div class="reality-box after"><div class="reality-head">With the agents</div><p>${tpl(c.after || "")}</p></div></div>
        <h3 class="rule-title">Assigned squad</h3><div class="squad">${p.agents.map((id, i) => { const a = agents[id] || {}; const q = prompts[i] || prompts[0]; return `<div class="squad-row"><div><span class="badge-id">${esc(id.replace(/_agent$/, "").replace(/_/g, "-"))}</span> <span class="squad-name" style="margin-left:6px">${esc(LABEL[id] || id)}</span><div class="squad-desc">${esc(cap((a.description || "").replace(/^[^:]+:\s*/, "")))}</div></div>${badge(id)}<button type="button" class="chip live ask-chip" data-ask="${esc(id)}" data-q="${esc(q ? q.prompt : "")}" style="min-height:32px;cursor:pointer">Ask it</button></div>`; }).join("")}
        <div class="squad-row"><div><span class="badge-id">edge</span> <span class="squad-name" style="margin-left:6px">The edge interlock engine</span><div class="squad-desc">${esc(S().team.edge.desc)}</div></div><span class="badge badge-arbiter">ARBITER</span><span class="cite">not an agent</span></div></div>`;
      pane.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.ask, b.dataset.q)));
    };
    pane.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => { pane.querySelectorAll(".persona-tab").forEach((x) => x.classList.toggle("active", x === b)); show(personas.find((p) => p.id === b.dataset.p)); }));
    show(personas[0]);
  }

  /* ---- screen 5: the team ---- */
  function renderTeam(pane) {
    const s = S().team, agents = Object.fromEntries(D.agents.agents.map((a) => [a.agent_id, a])), fs = D.flex.summary;
    let current = "optimization_orchestrator", filter = "all", q = "";
    pane.innerHTML = `<div class="eyebrow">${esc(s.eyebrow)}</div><h1 class="hero-title" style="margin-bottom:6px">${esc(s.hero)}</h1><p class="hero-desc" style="margin-bottom:20px">${esc(s.lede)}</p>
      <div class="eco-toolbar"><input class="team-search" id="team-q" type="search" placeholder="Search agents and tables" aria-label="Search agents"><div class="chip-row" id="team-filters">${["all", "lead", "spec", "review", "edge"].map((f) => `<button type="button" class="filter-chip ${f === "all" ? "active" : ""}" data-f="${f}">${esc({ all: "All", lead: "The lead", spec: "Specialists", review: "The reviewer", edge: "The edge" }[f])}</button>`).join("")}</div></div>
      <div class="topology" id="topology"></div><div class="deepdive" id="deepdive"></div>
      ${techDrawer("Technical detail", [["Inventory", "/api/agents: agent_id, pattern, tier, hitl_required, tools, reads, role"], ["Value", "/api/prize branch lines mapped per agent; the reviewer has no separate figure and says so"], ["Ask this agent", "POST /api/chat through the lead; the lead delegates to the specialist named in the question"], ["Recorded run", "/api/alpha/recorded: the grounding probe reply and ADK cases from eval/results, badged replay"]])}
      <div class="disclaimer">${esc(S().disclaimer)}</div>`;
    const match = (id) => { const a = agents[id]; const hay = `${id} ${LABEL[id]} ${(a.reads || []).join(" ")} ${(a.tools || []).join(" ")}`.toLowerCase(); return !q || hay.includes(q); };
    const topology = () => {
      pane.querySelector("#topology").innerHTML = s.tiers.map((t) => { const dim = filter !== "all" && filter !== t.id; return `<div class="tier"><div class="tier-badge ${t.cls}">${esc(t.badge)}</div><div class="tier-card expanded ${dim ? "dim" : ""}"><div class="tier-head"><div><div class="tier-title">${esc(t.title)}</div><div class="tier-desc">${esc(t.desc)}</div></div>${t.id === "edge" ? `<span class="badge badge-warning">${F.rules_n} rules · ${F.edge_ms}</span>` : `<span class="badge badge-stable">${t.agents.length} agent${t.agents.length === 1 ? "" : "s"}</span>`}</div>
        ${t.agents.length ? `<div class="tier-body"><div class="agent-grid">${t.agents.map((id) => { const a = agents[id], c = s.agents[id]; return `<div class="agent-card ${match(id) ? "" : "hidden"} ${id === current ? "selected" : ""}" data-a="${esc(id)}" style="${id === current ? "border-color:var(--m3-primary)" : ""}"><div><span class="badge-id">${esc(id.replace(/_agent$/, "").replace(/_/g, "-"))}</span><div class="agent-title">${esc(LABEL[id])}</div><div class="agent-desc">${esc(c ? c.hero : "")}</div></div><div class="agent-foot"><span class="chip">${esc((a.reads || []).length)} table${(a.reads || []).length === 1 ? "" : "s"}</span>${a.hitl_required ? '<span class="badge badge-signoff">SIGN-OFF</span>' : id === "safety_auditor" ? '<span class="badge badge-arbiter">ARBITER</span>' : '<span class="badge badge-advisory">ADVISORY</span>'}</div></div>`; }).join("")}</div></div>`
        : `<div class="tier-body"><div class="agent-grid"><div class="agent-card" style="cursor:default"><div><span class="badge-id">edge</span><div class="agent-title">${esc(s.edge.title)}</div><div class="agent-desc">${esc(s.edge.desc)}</div></div><div class="agent-foot"><span class="chip">${esc(fs.actions_evaluated)} actions today</span><span class="badge badge-warning">${esc(fs.accepted)} accept · ${esc(fs.limited)} limit · ${esc(fs.rejected)} reject</span></div></div></div></div>`}</div></div>`; }).join("");
      pane.querySelectorAll("[data-a]").forEach((el) => el.addEventListener("click", () => { current = el.dataset.a; topology(); deepdive(); pane.querySelector("#deepdive").scrollIntoView({ behavior: "smooth", block: "start" }); }));
    };
    const deepdive = () => {
      const id = current, a = agents[id], c = s.agents[id], ids = Object.keys(s.agents), ix = ids.indexOf(id), v = c.value ? prizeLine(c.value.branch, c.value.line) : null;
      const stages = ["trigger", "reads", "decides", "approval", "lands"];
      pane.querySelector("#deepdive").innerHTML = `<div class="deepdive-nav"><div class="badge-row"><span class="badge-id">${esc(id)}</span><span class="badge badge-primary">${esc(c.value ? c.value.branch : "no branch")}</span><span class="badge badge-stable">pattern ${esc(a.pattern)} · ${esc(a.tier)} model</span></div><div class="chip-row"><button class="btn" id="dd-prev">Previous agent</button><button class="btn" id="dd-next">Next agent</button></div></div>
        <div class="deepdive-top"><div><div class="deepdive-hero">${esc(c.hero)}</div><p class="section-subtitle" style="margin-bottom:0">${esc(cap((a.description || "").replace(/^[^:]+:\s*/, "")))}</p></div>
        <div class="value-card"><div class="value-head">Value unlocked</div><div class="value-amount">${v ? v.html : '<span class="gap-value">NOT IN THE DATA</span>'}</div><div class="value-period">${v ? esc(v.mech) : esc(c.stake)}</div></div></div>
        <div class="deepdive-main"><div class="col">
          <div class="problem-card"><div class="card-head">The problem it removes</div><div class="card-text">${esc(c.problem)}</div></div>
          <div class="biz-card"><div class="biz-stake">${esc(c.stake)}</div>${c.rows.map(([k, val]) => `<div class="biz-row ${k === "limit" ? "limit" : ""}"><div class="biz-label">${esc(k === "limit" ? "What it may not do" : k)}</div><div class="biz-value">${esc(val)}</div></div>`).join("")}</div>
          <div class="flow-card"><div class="card-head">The decision flow, five stages</div><div class="decision-flow" id="dd-flow">${stages.map((st, i) => `<div class="flow-stage" data-stage="${st}"><div class="flow-rail"><div class="flow-marker">${i + 1}</div><div class="flow-connector"></div></div><div class="flow-body"><div class="flow-label">${esc(st)}</div><div class="flow-value">${esc(c.flow[i])}</div>${st === "reads" ? `<div class="flow-detail">${esc((a.reads || []).join(", "))}</div>` : ""}${st === "decides" ? `<div class="flow-detail">tools: ${esc((a.tools || []).join(", "))}</div>` : ""}</div></div>`).join("")}</div></div>
        </div><div class="col">
          <div class="ask-box"><div class="card-head">Ask this agent <span class="badge badge-live"><span class="dot"></span>live</span></div><div class="q">${esc(c.ask)}</div><button class="btn btn-primary" id="dd-ask">Ask it now</button></div>
          <div class="ask-box"><div class="card-head">Play the recorded run <span class="badge badge-replay"><span class="dot"></span>replay</span></div><div class="q">The reply this agent gave during the evaluation, with its grounding checks.</div><button class="btn" id="dd-rec">Open the recording</button></div>
          <div><div class="card-head" style="color:var(--m3-text-tertiary)">Provenance: what it reads</div>${(a.reads || []).map((t) => `<div class="prov-row"><span><span class="prov-dot"></span> ${esc(t)}</span><span class="prov-badge">${esc(D.meta.tables.find((x) => x.name === t) ? n0(D.meta.tables.find((x) => x.name === t).rows) + " rows" : "derived")}</span></div>`).join("")}</div>
        </div></div>`;
      pane.querySelector("#dd-prev").onclick = () => { current = ids[(ix - 1 + ids.length) % ids.length]; topology(); deepdive(); };
      pane.querySelector("#dd-next").onclick = () => { current = ids[(ix + 1) % ids.length]; topology(); deepdive(); };
      pane.querySelector("#dd-ask").onclick = () => ask(id, c.ask);
      pane.querySelector("#dd-rec").onclick = () => recorded(id);
      A().play(pane.querySelector("#dd-flow"));
    };
    pane.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { filter = b.dataset.f; pane.querySelectorAll(".filter-chip").forEach((x) => x.classList.toggle("active", x === b)); topology(); }));
    pane.querySelector("#team-q").addEventListener("input", (e) => { q = e.target.value.trim().toLowerCase(); topology(); });
    topology(); deepdive();
  }

  /* ---- screen 6: how it's built ---- */
  function renderBuilt(pane) {
    const s = S().built, r = D.research.statements.no_partnership;
    pane.innerHTML = `<div class="eyebrow">${esc(s.eyebrow)}</div>
      <div class="boundary-hero"><div class="shield">⛨</div><div class="boundary-headline">${esc(s.hero)}</div><div class="boundary-sub">${esc(s.boundary_sub)}</div></div>
      <div class="note-box"><div class="lab">Proposed collaboration</div><div class="txt">${esc(r.text)} <span class="cite">${esc(r.cite)}</span></div></div>
      <h2 class="section-title">${esc(s.stack_title)}</h2><p class="section-subtitle">${esc(s.stack_sub)}</p>
      <div class="arch-grid"><div class="arch-stack" id="arch-stack">${s.stack.map((b, i) => `${i ? '<div class="arch-seam"><span class="down">↓ request</span><span class="up">↑ evidence</span></div>' : ""}<div class="arch-block ${b.sim ? "sim" : ""}"><div class="arch-band">${esc(b.band)}${b.sim ? "<br>simulated" : ""}</div><div><div class="arch-name">${esc(b.name)}</div><div class="arch-blurb">${esc(b.blurb)}</div><div class="arch-chips">${b.chips.map((c) => `<span class="arch-chip">${esc(c)}</span>`).join("")}</div></div><div class="arch-traffic"><div class="arch-traffic-line down"><span class="arrow">↓</span><span>${esc(b.down)}</span></div><div class="arch-traffic-line up"><span class="arrow">↑</span><span>${esc(b.up)}</span></div></div></div>`).join("")}</div>
      <div class="control-rail"><div class="control-title">Guardrails</div>${s.controls.map((c) => `<div class="control-card"><div class="control-name">${esc(c.name)}</div><div class="control-rule">${esc(c.rule)}</div></div>`).join("")}
        <div class="kv-card"><div class="kv-row"><span class="kv-key">Agent evaluation</span><span class="kv-val">${esc(F.adk_pass)}</span></div><div class="kv-row"><span class="kv-key">Grounding probes</span><span class="kv-val">${esc(F.ground_pass)}</span></div><div class="kv-row"><span class="kv-key">Safety probes</span><span class="kv-val">${esc(F.safety_pass)}</span></div><div class="kv-row"><span class="kv-key">pytest</span><span class="kv-val">${esc(F.pytest_pass)}</span></div></div></div></div>
      <h2 class="section-title">Where every figure comes from</h2><div class="provenance-row">${s.provenance.map((p, i) => `<div class="provenance-step ${i === 3 ? "final" : ""}"><b>${esc(p.k)}</b>${esc(p.v)}</div>`).join("")}</div>
      <h2 class="section-title" style="margin-top:32px">Ask the data directly</h2><p class="section-subtitle">Three grounded questions. Each answer names the tables it read; the live agent runs on this server.</p>
      <div class="ask-data">${s.ask_data.map((x, i) => `<div class="card"><div class="q">${esc(x.q)}</div><div class="chip-row">${x.tables.map((t) => `<span class="arch-chip">${esc(t)}</span>`).join("")}</div><button class="btn btn-outline" data-askd="${i}">Ask live</button></div>`).join("")}</div>
      <h2 class="section-title">What the demo simulates, and what production uses</h2><div class="table-scroll"><table class="pp-table"><thead><tr><th>Layer</th><th>This demo simulates</th><th>Production uses</th></tr></thead><tbody>${s.production.map((row) => `<tr>${row.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <p class="cite" style="margin-top:10px">${esc(s.collab_note)}</p>
      ${techDrawer("Technical detail", [["Dataset", `${esc(D.meta.dataset)} on ${esc(D.meta.backend)} · ${D.meta.tables.length} tables · seed ${esc(D.meta.seed)}`], ["Windows", `telemetry ${esc(D.meta.windows.telemetry.join(" to "))} · site history ${esc(D.meta.windows.site_history.join(" to "))}`], ["Evaluation", "eval/results: adk_summary.json, grounding_results.json, safety_results.json, pytest_last.json (see /api/proof)"], ["Deploy", "Cloud Run; UI_VARIANT=alpha serves this front end at / with version 2 at /v2/ and version 1 at /v1/"]])}
      <div class="disclaimer">${esc(S().disclaimer)}</div>`;
    pane.querySelectorAll("[data-askd]").forEach((b) => b.addEventListener("click", () => { const x = s.ask_data[Number(b.dataset.askd)]; ask(x.agent, x.q); }));
  }

  /* ---- boot ---- */
  async function boot() {
    A().mount();
    const get = (p) => A().api(p);
    try {
      const [overview, research, prize, flex, bess, pv, jepx, dr_events, anomalies, gain, agents, personas, prompts, proof, meta, strip, timeline, schematic] = await Promise.all([
        get("/api/overview"), get("/api/research"), get("/api/prize"), get("/api/flex"), get("/api/bess"), get("/api/pv"), get("/api/jepx"), get("/api/dr-events"), get("/api/anomalies"),
        get("/api/gain-share?month=2026-07"), get("/api/agents"), get("/api/personas"), get("/api/suggested-prompts"), get("/api/proof"), get("/api/meta"), get("/api/strip"), get("/api/alpha/timeline"), get("/api/alpha/schematic")]);
      Object.assign(D, { overview, research, prize, flex, bess, pv, jepx, dr_events, anomalies, gain, agents, personas, prompts, proof, meta, strip, timeline, schematic });
      buildFigures();
      renderWhy(document.getElementById("pane-why")); renderSystem(document.getElementById("pane-system")); window.Call.render(document.getElementById("pane-call"));
      renderWho(document.getElementById("pane-who")); renderTeam(document.getElementById("pane-team")); renderBuilt(document.getElementById("pane-built"));
      document.addEventListener("alpha:screen", (e) => { if (e.detail.id === "system") requestAnimationFrame(() => window.Schematic.draw()); if (e.detail.id === "built") A().play(document.getElementById("arch-stack")); });
      if (location.hash.slice(1) === "system") requestAnimationFrame(() => window.Schematic.draw());
    } catch (err) {
      document.getElementById("pane-why").innerHTML = `<div class="boundary-hero"><div class="boundary-headline">Data unavailable</div><div class="boundary-sub">${esc(err.message)}</div></div>`;
    }
  }
  document.addEventListener("DOMContentLoaded", boot);
  return { tpl, txt, md, promptText, techDrawer, ask, recorded, LABEL, onRunFinished: null };
})();
