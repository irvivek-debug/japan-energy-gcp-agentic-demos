/* The case for change: five chapters rendered from /api. Each chapter: eyebrow, statement headline, lede,
 * evidence blocks, what it replaces, a technical drawer, provenance and the next chapter. */
(async function () {
  const { esc, num, mjpy, css } = UI;
  const page = document.body.dataset.page;
  const CH = {
    case: { n: 1, file: "index.html", eyebrow: "1 · The case", next: ["gap.html", "2 · The gap"] },
    gap: { n: 2, file: "gap.html", eyebrow: "2 · The gap", next: ["prize.html", "3 · The prize"] },
    prize: { n: 3, file: "prize.html", eyebrow: "3 · The prize", next: ["solution.html", "4 · The solution"] },
    solution: { n: 4, file: "solution.html", eyebrow: "4 · The solution", next: ["proof.html", "5 · The proof"] },
    proof: { n: 5, file: "proof.html", eyebrow: "5 · The proof", next: ["/workspace/value.html", "Open the workspace"] },
  }[page];
  await Shell.mountNav("case", `/case/${CH.file}`);
  const root = document.getElementById("chapter");
  const inits = [];

  const card = (cls, cap, body, extra = "") => `<div class="card ${cls} reveal"${extra}><div class="card-cap">${cap}</div>${body}</div>`;
  const stat = (v, label, sub) => `<div><div class="metric">${v}</div><div class="metric-sub">${esc(label)}</div>${sub ? `<div class="dim mono" style="font-size:11px;margin-top:4px">${esc(sub)}</div>` : ""}</div>`;
  const beforeAfter = (b, a) => `<section><div class="eyebrow reveal">What it replaces</div><div class="beforeafter">
      <div class="card before reveal"><div class="card-cap">Today</div><p>${b}</p></div>
      <div class="card after reveal"><div class="card-cap">With the copilot</div><p>${a}</p></div></div></section>`;
  function frame({ h1, lede, blocks, before, after, tech, techHint, tables, meta }) {
    const next = CH.next[0].startsWith("/") ? CH.next[0] : `/case/${CH.next[0]}`;
    root.innerHTML = `<section class="hero read reveal"><div class="eyebrow">${esc(CH.eyebrow)}</div><h1>${h1}</h1>${lede.map((l) => `<p class="lede">${l}</p>`).join("")}</section>
      <section><div class="bento">${blocks.join("")}</div></section>
      ${beforeAfter(before, after)}
      <section class="reveal">${Shell.technicalDrawer(tech, techHint)}</section>
      <div class="chapter-nav reveal"><a class="btn primary" href="${esc(next)}">Next: ${esc(CH.next[1])}</a><a class="btn" href="/">Back to the start</a></div>
      ${Shell.provenance(UI.provRows(meta, tables))}`;
    inits.forEach((f) => { try { f(); } catch (e) { console.warn(e); } });
    Motion.reveal();
  }
  const cite = (s) => `<span class="cite">${esc(s)}</span>`;

  try {
    const [meta, r] = await Promise.all([Shell.api("/api/meta"), UI.facts()]);
    if (page === "case") await chapterCase(meta, r);
    else if (page === "gap") await chapterGap(meta, r);
    else if (page === "prize") await chapterPrize(meta, r);
    else if (page === "solution") await chapterSolution(meta, r);
    else if (page === "proof") await chapterProof(meta, r);
  } catch (e) {
    root.innerHTML = `<div class="note crit"><strong>Data unavailable</strong><br>${esc(e.message)}</div>`;
  }

  // ------------------------------------------------------------------------------------------ 1
  async function chapterCase(meta, r) {
    const [jp, dev, dr] = await Promise.all([Shell.api("/api/jepx"), Shell.api("/api/deviation"), Shell.api("/api/dr-today")]);
    const ev = dr.events[0], sw = jp.spike_windows[0], bl = ev.estimated_baseline;
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-prices")); if (!c) return;
      const x = jp.slots.map((s) => s.time.slice(0, 5)), P = UI.palette();
      c.setOption({ animation: false, grid: { left: 44, right: 12, top: 36, bottom: 28 }, tooltip: UI.tooltip((v) => `${num(v, 2)} JPY/kWh`),
        legend: UI.legend(["Spot", "Imbalance (estimate)", "Plant all-in price"]),
        xAxis: { type: "category", data: x, boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", ...UI.axis() },
        series: [
          { name: "Spot", type: "line", symbol: "none", data: jp.slots.map((s) => s.spot), lineStyle: { color: P[1], width: 2 }, itemStyle: { color: P[1] },
            markArea: sw ? { silent: true, itemStyle: { color: "rgba(224,185,120,0.08)" }, data: [[{ xAxis: sw.start }, { xAxis: sw.end }]] } : undefined },
          { name: "Imbalance (estimate)", type: "line", symbol: "none", data: jp.slots.map((s) => s.imbalance), lineStyle: { color: P[4], width: 2, type: "dashed" }, itemStyle: { color: P[4] } },
          { name: "Plant all-in price", type: "line", symbol: "none", data: jp.slots.map((s) => s.plant_price), lineStyle: { color: P[0], width: 1.5, type: "dotted" }, itemStyle: { color: P[0] } },
        ] });
    });
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-dev")); if (!c) return;
      const rows = dev.slots, x = rows.map((s) => s.time.slice(0, 5)), P = UI.palette();
      c.setOption({ animation: false, grid: { left: 56, right: 12, top: 36, bottom: 28 }, tooltip: UI.tooltip((v) => `${num(v)} kW`),
        legend: UI.legend(["Nomination", "Band", "Import, PV p50", "Import, PV p10"]),
        xAxis: { type: "category", data: x, boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", scale: true, ...UI.axis() },
        series: [
          { name: "Nomination", type: "line", symbol: "none", data: rows.map((s) => s.nominated_kw), lineStyle: { color: css("--fg"), width: 1.5 }, itemStyle: { color: css("--fg") } },
          { name: "lo", type: "line", stack: "band", symbol: "none", data: rows.map((s) => s.nominated_kw - s.band_kw), lineStyle: { opacity: 0 }, tooltip: { show: false } },
          { name: "Band", type: "line", stack: "band", symbol: "none", data: rows.map((s) => 2 * s.band_kw), lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(255,255,255,0.07)" }, itemStyle: { color: css("--fg-dim") } },
          { name: "Import, PV p50", type: "line", symbol: "none", data: rows.map((s) => s.forecast_import_p50_kw), lineStyle: { color: P[0], width: 2 }, itemStyle: { color: P[0] } },
          { name: "Import, PV p10", type: "line", symbol: "none", data: rows.map((s) => s.forecast_import_p10pv_kw), lineStyle: { color: P[4], width: 2, type: "dashed" }, itemStyle: { color: P[4] } },
        ] });
    });
    const market = ["balancing_day_ahead", "jepx_api"].map((k) => `<li>${esc(r.statements[k].text)}${cite(r.statements[k].cite)}</li>`).join("")
      + `<li>The scarcity imbalance cap rises from ${UI.fact(r, "imbalance_cap_now", 0)} to ${UI.fact(r, "imbalance_cap_oct", 0)} on 2026-10-01.${cite(UI.citeOf(r, "imbalance_cap_oct"))}</li>`
      + `<li>Tokyo summer peak demand is forecast to grow from ${UI.fact(r, "tokyo_peak_fy2026", 1)} to ${UI.fact(r, "tokyo_peak_fy2035", 1)} by FY2035, with ${UI.fact(r, "dc_semicon_additions_fy2035", 2)} of data-center and semiconductor additions nationally.${cite(UI.citeOf(r, "tokyo_peak_fy2035"))}</li>`;
    frame({
      meta, tables: [...new Set([...jp.source, ...dev.source, ...dr.source])],
      h1: "Every half hour now carries a price, and the plant still answers it with fixed rules and a phone call.",
      lede: [
        `Tokyo spot has averaged <b>${UI.fact(r, "tokyo_spot_fy2026")}</b> in FY2026 against <b>${UI.fact(r, "tokyo_spot_fy2025")}</b> a year earlier (${esc(UI.citeOf(r, "tokyo_spot_fy2026"))}). `
          + `Today this plant's evening spot peaks at <b>${num(sw ? sw.max_spot_jpy_kwh : null, 1)} JPY/kWh</b>, and the imbalance estimate reaches <b>${num(sw ? sw.max_imbalance_jpy_kwh : null, 1)} JPY/kWh</b> as the wide-area reserve margin falls to <b>${num(sw ? sw.min_reserve_margin_pct : null, 1)} %</b>.`,
        `At <b>${esc(ev.notified_at.slice(11))}</b> the aggregator asked for <b>${num(ev.requested_kw)} kW</b> from ${esc(ev.start_time)} to ${esc(ev.end_time)}. The answer has to be right for every 30-minute slot, and it has to be found before the plan can no longer be changed.`,
      ],
      blocks: [
        card("c12", `Today's prices, 13:00 to 22:00<span class="spacer"></span><span class="pill">JPY/kWh</span>`, `<div class="chart" id="c-prices" role="img" aria-label="Spot, imbalance and plant price"></div>
          <p class="muted" style="font-size:13px">Tokyo slot prices in FY2026 sit between ${UI.fact(r, "tokyo_spot_fy2026_p5")} and ${UI.fact(r, "tokyo_spot_fy2026_p95")} ninety per cent of the time (p5 to p95).${cite(UI.citeOf(r, "tokyo_spot_fy2026_p95"))}</p>`),
        card("c7", `The 30-minute rule<span class="spacer"></span><span class="pill">kW</span>`, `<div class="chart" id="c-dev" role="img" aria-label="Nominated plan against forecast import"></div>
          <p class="muted" style="font-size:13px">The plant's plan is nominated a day ahead; import outside a ${num(dev.band_pct, 1)} % band is settled at the imbalance price. `
          + `If nothing changes, ${num(dev.summary.slots_outside_band_p10pv.length)} slots leave the band when the cloud band hits (${esc(dev.summary.slots_outside_band_p10pv.join(", "))}). Plans can be revised until ${UI.fact(r, "gate_closure_min")} before delivery.${cite(UI.citeOf(r, "gate_closure_min"))}</p>`),
        card("c5", "Where the market is heading", `<ul class="tight">${market}</ul>`),
        card("c12", "Today's call", `<div class="statline">${stat(`${num(ev.requested_kw)}<span class="u">kW</span>`, "Reduction requested", `${ev.start_time} to ${ev.end_time}`)}
          ${stat(`${num(ev.requested_kwh)}<span class="u">kWh</span>`, "Energy to deliver", "requested kW x hours")}
          ${stat(`${num(bl.baseline_avg_kw)}<span class="u">kW</span>`, "Baseline estimate", `High 4 of 5, adjustment ${num(bl.same_day_adjustment_kw)} kW`)}
          ${stat(`${num(bl.selected_days.length)}`, "Baseline days used", bl.selected_days.join(", "))}</div>`),
      ],
      before: "The aggregator calls. Someone phones the utility operator, a spreadsheet guesses which loads can move, and the battery keeps running rules that ignore the call, the prices and the weather.",
      after: "Within minutes the plant has a plan checked against its live controllers, a battery schedule built around the cloud band and the price spike, and one named person who signs it off.",
      techHint: "prices, band, baseline",
      tech: `<dl class="kv"><dt>Imbalance price</dt><dd>Higher of the base price and the scarcity curve: 0 at a 10 % wide-area reserve margin, ${UI.fact(r, "imbalance_d_8pct", 0)} at 8 %, capped at ${UI.fact(r, "imbalance_cap_now", 0)} until 2026-09-30 (${esc(UI.citeOf(r, "imbalance_cap_now"))}).</dd>
        <dt>Deviation exposure</dt><dd>Excess beyond ${num(dev.band_pct, 1)} % of the nominated kW, times 0.5 h, times the imbalance price, per slot.</dd>
        <dt>Baseline</dt><dd>${esc(ev.baseline_method)}.</dd><dt>Gate closure</dt><dd>${esc(dev.gate_closure)}</dd></dl>`,
    });
  }

  // ------------------------------------------------------------------------------------------ 2
  async function chapterGap(meta, r) {
    const [dr, gs, an, bs, ct, pv] = await Promise.all([Shell.api("/api/dr-events"), Shell.api("/api/gain-share?month=2026-07"), Shell.api("/api/anomalies"),
      Shell.api("/api/bess"), Shell.api("/api/compressor-trend"), Shell.api("/api/pv")]);
    const settled = dr.events.filter((e) => e.status === "settled");
    const worst = settled.reduce((a, b) => (b.performance_pct < a.performance_pct ? b : a));
    const best = settled.reduce((a, b) => (b.performance_pct > a.performance_pct ? b : a));
    const A = Object.fromEntries(an.anomalies.map((a) => [a.type, a]));
    const ac = A.compressor_specific_power_drift, m27 = A.stuck_meter, aug = A.billing_peak_set_around_dr_event, jul = gs.invoice.demand_peak_check;
    const today = gs.today, v1 = bs.policies.rule_based_v1.kpis, v2 = bs.policies.forecast_aware_v2.kpis;
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-dr")); if (!c) return;
      const P = UI.palette(), labels = [...settled.map((e) => e.date), `${today.date} (plan)`];
      c.setOption({ animation: false, grid: { left: 52, right: 12, top: 36, bottom: 28 }, tooltip: { ...UI.tooltip((v) => `${num(v)} kW`), axisPointer: { type: "shadow" } },
        legend: UI.legend(["Requested", "Delivered (measured)"]),
        xAxis: { type: "category", data: labels, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", ...UI.axis() },
        series: [{ name: "Requested", type: "bar", barGap: "10%", data: [...settled.map((e) => e.requested_kw), today.requested_kw], itemStyle: { color: css("--fg-dim"), borderRadius: [4, 4, 0, 0] } },
          { name: "Delivered (measured)", type: "bar", data: [...settled.map((e) => ({ value: e.delivered_kw, itemStyle: { color: e.delivered_kw < e.requested_kw ? P[4] : P[3] } })),
            { value: today.estimated_measured_delivery_avg_kw, itemStyle: { color: P[3], opacity: 0.6 } }], itemStyle: { borderRadius: [4, 4, 0, 0] } }] });
    });
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-soc")); if (!c) return;
      const P = UI.palette(), rows1 = bs.policies.rule_based_v1.rows, rows2 = bs.policies.forecast_aware_v2.rows;
      const x = [bs.history.length ? "13:30" : "", ...rows2.map((q) => q.time)].slice(1);
      c.setOption({ animation: false, grid: { left: 40, right: 12, top: 36, bottom: 28 }, tooltip: UI.tooltip((v) => `${num(v, 1)} %`),
        legend: UI.legend(["Current rules (v1)", "Forecast-aware (v2)"]),
        xAxis: { type: "category", data: rows2.map((q) => q.time), boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", min: 0, max: 100, ...UI.axis() },
        series: [{ name: "Current rules (v1)", type: "line", symbol: "none", data: rows1.map((q) => q.soc_end_pct), lineStyle: { color: P[1], width: 2, type: "dashed" }, itemStyle: { color: P[1] } },
          { name: "Forecast-aware (v2)", type: "line", symbol: "none", data: rows2.map((q) => q.soc_end_pct), lineStyle: { color: P[3], width: 2.5 }, itemStyle: { color: P[3] },
            markArea: { silent: true, itemStyle: { color: "rgba(196,176,232,0.08)" }, data: [[{ xAxis: rows2.find((q) => q.dr).time }, { xAxis: [...rows2].reverse().find((q) => q.dr).time }]] } }] });
      void x;
    });
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-ac")); if (!c) return;
      const P = UI.palette();
      c.setOption({ animation: false, grid: { left: 44, right: 12, top: 36, bottom: 28 }, tooltip: UI.tooltip((v) => `${num(v, 2)} kW per Nm3/min`),
        legend: UI.legend(["AC-04", "Peer median"]),
        xAxis: { type: "category", data: ct.dates.map((d) => d.slice(5)), boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", scale: true, ...UI.axis() },
        series: [{ name: "AC-04", type: "line", symbol: "none", data: ct.ac04, lineStyle: { color: P[4], width: 2 }, itemStyle: { color: P[4] } },
          { name: "Peer median", type: "line", symbol: "none", data: ct.peer_median, lineStyle: { color: P[0], width: 1.5 }, itemStyle: { color: P[0] } }] });
    });
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-pv")); if (!c) return;
      const P = UI.palette(), s = pv.slots, x = s.map((q) => q.time.slice(0, 5));
      c.setOption({ animation: false, grid: { left: 48, right: 12, top: 36, bottom: 28 },
        tooltip: { ...UI.tooltip(), formatter: (ps) => { const q = s[ps[0].dataIndex]; return `<b>${q.time}</b><br>p10 ${num(q.p10_kw)} kW<br>p50 ${num(q.p50_kw)} kW<br>p90 ${num(q.p90_kw)} kW`; } },
        legend: UI.legend(["p10 to p90", "p50"]),
        xAxis: { type: "category", data: x, boundaryGap: false, ...UI.axis(), splitLine: { show: false } }, yAxis: { type: "value", ...UI.axis() },
        series: [{ name: "lo", type: "line", stack: "b", symbol: "none", data: s.map((q) => q.p10_kw), lineStyle: { opacity: 0 } },
          { name: "p10 to p90", type: "line", stack: "b", symbol: "none", data: s.map((q) => q.p90_kw - q.p10_kw), lineStyle: { opacity: 0 }, areaStyle: { color: P[0], opacity: 0.22 }, itemStyle: { color: P[0] } },
          { name: "p50", type: "line", symbol: "none", data: s.map((q) => q.p50_kw), lineStyle: { color: P[0], width: 2 }, itemStyle: { color: P[0] } }] });
    });
    const peakStat = (p, label) => p ? stat(`${num(p.extra_billing_demand_kw)}<span class="u">kW</span>`, label, `peak ${num(p.month_billing_peak_kw)} kW at ${p.set_at}, battery ${num(p.bess_kw_at_peak)} kW; ${num(p.extra_demand_charge_jpy)} JPY`) : stat(Shell.fig(null), label);
    frame({
      meta, tables: [...new Set([...dr.source, ...an.source, ...bs.source, ...ct.source, ...pv.source])],
      h1: `The same equipment delivered ${num(best.performance_pct, 0)} % of one DR request and ${num(worst.performance_pct, 0)} % of another.`,
      lede: [
        `On ${esc(worst.date)} the plant committed <b>${num(worst.requested_kw)} kW</b>, delivered <b>${num(worst.delivered_kw)} kW</b> and paid <b>${num(worst.penalty_jpy)} JPY</b>: ${esc(worst.notes)}`,
        `Both of this summer's billing peaks were set around DR events while the battery sat idle, the current battery rules give the DR window <b>${num(v1.dr_firm_kw)} kW</b> firm, and compressor AC-04 runs <b>${num(ac ? ac.evidence.recent_excess_vs_peers_pct : null, 1)} %</b> above its peers.`,
      ],
      blocks: [
        card("c7", `DR events: requested against delivered<span class="spacer"></span><span class="pill">kW</span>`, `<div class="chart" id="c-dr" role="img" aria-label="Requested and delivered kW per event"></div>
          <p class="muted" style="font-size:13px">Delivery is measured as the High 4 of 5 baseline minus receiving-point import. Today's bar is the estimate for the edge-verified plan (${num(today.physical_firm_reduction_kw)} kW firm).</p>`),
        card("c5", "Billing peaks set around DR events", `<div class="statline">${peakStat(jul, "July, extra billing demand")}${peakStat(aug ? { ...aug.evidence, ...aug.impact, extra_demand_charge_jpy: aug.impact.demand_charge_jpy_this_month } : null, "August, extra billing demand")}</div>
          <p class="muted" style="font-size:13px">The demand charge follows the month's highest half hour. Both peaks fell in the two hours around an event, when the battery was held full or already empty.</p>`),
        card("c7", `Battery state of charge, rest of today<span class="spacer"></span><span class="pill">%</span>`, `<div class="chart" id="c-soc" role="img" aria-label="Battery state of charge under both policies"></div>
          <table class="data"><thead><tr><th></th><th>Current rules</th><th>Forecast-aware</th></tr></thead><tbody>
          <tr><td>SOC at the DR start</td><td class="num">${num(v1.soc_at_dr_start_pct, 1)} %</td><td class="num">${num(v2.soc_at_dr_start_pct, 1)} %</td></tr>
          <tr><td>Firm kW in the DR window</td><td class="num">${num(v1.dr_firm_kw)} kW</td><td class="num">${num(v2.dr_firm_kw)} kW</td></tr>
          <tr><td>Charging in PV-risk slots</td><td class="num">${num(v1.charge_in_pv_risk_slots_kwh)} kWh</td><td class="num">${num(v2.charge_in_pv_risk_slots_kwh)} kWh</td></tr></tbody></table>`),
        card("c5", `Compressed air and metering<span class="spacer"></span><span class="pill">kW per Nm3/min</span>`, `<div class="chart short" id="c-ac" role="img" aria-label="AC-04 specific power against peers"></div>
          <p class="muted" style="font-size:13px">AC-04 was ${num(ac ? ac.evidence.early_june_excess_vs_peers_pct : null, 1)} % above its peers in early June and is ${num(ac ? ac.evidence.recent_excess_vs_peers_pct : null, 1)} % above now, about ${mjpy(ac ? ac.impact.annual_cost_jpy : null, 1)} a year. `
          + `Meter ${esc(m27 ? m27.asset_id : "M-27")} has repeated ${num(m27 ? m27.evidence.flat_value_kw : null, 1)} kW for ${num(m27 ? m27.evidence.duration_h : null, 1)} hours, leaving ${num(m27 ? m27.impact.unallocated_kwh : null)} kWh unallocated.</p>`),
        card("c12", `PV ensemble this afternoon<span class="spacer"></span><span class="pill">kW</span>`, `<div class="chart" id="c-pv" role="img" aria-label="PV p10 p50 p90"></div>
          <p class="muted" style="font-size:13px">At ${esc(pv.deepest_gap.time)} the downside case (p10) is ${num(pv.deepest_gap.p10_kw)} kW against ${num(pv.deepest_gap.p50_kw)} kW expected. Over the last 14 days ${num(pv.calibration_14d.p10_p90_coverage_pct, 1)} % of slots fell inside the p10 to p90 band.</p>`),
      ],
      before: "Each shortfall is found after settlement: a penalty on the aggregator statement, a demand charge on next month's bill, a compressor that only gets looked at when it fails.",
      after: "The same checks run before the commitment: what the edge will accept, what the battery will hold at 16:30, which meter cannot be trusted, and what each gap costs.",
      techHint: "how each gap is measured",
      tech: `<dl class="kv"><dt>DR delivery</dt><dd>Baseline (High 4 of 5 with same-day adjustment, net of battery charging) minus receiving-point import, averaged over the event.</dd>
        <dt>Billing peak</dt><dd>Month's highest 30-minute import; flagged when it falls within two hours of a DR event with the battery idle.</dd>
        <dt>Specific power</dt><dd>kWh divided by delivered air, per Nm3/min; flagged at 12 % above the peer median over the last three days.</dd>
        <dt>Frozen meter</dt><dd>An exact reading repeated over contiguous 5-minute intervals, confirmed by the receiving-point energy balance.</dd></dl>`,
    });
  }

  // ------------------------------------------------------------------------------------------ 3
  async function chapterPrize(meta, r) {
    const [pz, gs] = await Promise.all([Shell.api("/api/prize"), Shell.api("/api/gain-share?month=2026-07")]);
    const lines = pz.branches.flatMap((b) => b.lines);
    const max = Math.max(...lines.map((l) => l.high || 0));
    const valued = pz.branches.filter((b) => b.lines.some((l) => l.high !== null)).length;
    const branchHtml = pz.branches.map((b) => `<div class="branch" style="border-left-color:var(--${b.hue})"><h3><span class="code" style="color:var(--${b.hue})">${esc(b.code)}</span>${esc(b.name)}</h3>
      ${b.lines.map((l) => `<div class="rline"><div><div class="mech">${esc(l.mechanism)}</div><div class="basis">${esc(l.basis)}</div></div>
        <div class="hbar" aria-hidden="true">${l.high !== null ? `<i style="left:${(100 * (l.low || 0) / max).toFixed(1)}%;width:${Math.max(1.5, 100 * ((l.high - (l.low || 0)) / max)).toFixed(1)}%;background:var(--${b.hue})"></i>` : ""}</div>
        <div class="fig">${l.high === null ? '<span class="metric gap">NOT IN THE DATA</span>' : `${num(l.low, 2)} to ${num(l.high, 2)} M JPY`}<div class="dim" style="font-size:10px">${esc(l.unit)}</div></div></div>`).join("")}</div>`).join("");
    inits.push(() => {
      const c = UI.chart(document.getElementById("c-gain")); if (!c) return;
      const m = gs.ledger.months, P = UI.palette();
      c.setOption({ animation: false, grid: { left: 56, right: 12, top: 36, bottom: 28 }, tooltip: { ...UI.tooltip((v) => `${num(v / 1e6, 2)} M JPY`), axisPointer: { type: "shadow" } },
        legend: UI.legend(["Client net", "Vendor gain share", "BESS-as-a-Service fee"]),
        xAxis: { type: "category", data: m.map((x) => x.month), ...UI.axis(), splitLine: { show: false } },
        yAxis: { type: "value", ...UI.axis({ axisLabel: { color: css("--fg-muted"), fontFamily: "JetBrains Mono", fontSize: 10.5, formatter: (v) => `${v / 1e6}M` } }) },
        series: [["Client net", "client_net_jpy", P[2]], ["Vendor gain share", "vendor_gain_share_jpy", P[3]], ["BESS-as-a-Service fee", "baas_fee_jpy", P[0]]].map(([n, k, col]) =>
          ({ name: n, type: "bar", stack: "s", barWidth: "55%", data: m.map((x) => x[k]), itemStyle: { color: col, borderColor: css("--surface"), borderWidth: 2 } })) });
    });
    const inv = gs.invoice;
    frame({
      meta, tables: [...new Set([...pz.source, ...gs.invoice.source])],
      h1: `The value sits in ${num(valued)} places, and none of them needs new equipment.`,
      lede: [`Every line below is a range with its mechanism and basis, computed from this plant's ledger, settlements and telemetry. Mitsubishi Electric targets solution-business revenue of ${UI.fact(r, "melco_solution_fy2030", 1)} by FY2030, up from ${UI.fact(r, "melco_solution_fy2025", 1)} in FY2025 (${esc(UI.citeOf(r, "melco_solution_fy2030"))}); recurring energy services are one route there.`],
      blocks: [
        card("c12", `Value by branch<span class="spacer"></span><span class="legend">${pz.branches.map((b) => `<span style="color:var(--${b.hue})">${esc(b.code)}</span>`).join("")}</span>`, `${branchHtml}<div class="note info"><strong>Read this first</strong><br>${esc(pz.note)}</div>`),
        card("c7", `Gain-share economics, month by month<span class="spacer"></span><span class="pill">JPY</span>`, `<div class="chart" id="c-gain" role="img" aria-label="Monthly split of verified savings"></div>`),
        card("c5", "July invoice", `<div class="statline">${stat(UI.mjpy(inv.total_verified_savings_jpy), "Verified savings")}${stat(UI.mjpy(inv.vendor_gain_share_jpy), `Gain share, ${num(inv.gain_share_pct)} %`)}
          ${stat(UI.mjpy(inv.baas_fee_jpy), "BESS-as-a-Service fee")}${stat(UI.mjpy(inv.client_net_benefit_jpy), "Client net")}</div>
          <p class="muted" style="font-size:13px">DR lines reconcile with the aggregator: ${inv.dr_reconciliation.reconciles ? "yes" : "no"}. July was the thinnest month: its billing peak was set right after the under-delivered event, costing ${UI.jpy(inv.demand_peak_check ? inv.demand_peak_check.extra_demand_charge_jpy : null)}.</p>`),
      ],
      before: "The equipment vendor sells meters, controllers and a battery once. The plant carries the capex, the risk and the job of proving what the equipment saved.",
      after: "Zero upfront: the vendor runs the battery as a service and earns a share of verified savings, so both sides are paid for the same number, month by month.",
      techHint: "how the ranges are built",
      tech: `<p>Low and high ends come from the observed spread in the data: settled events so far against the dispatch rate projected to the end of September, the lowest and highest ledger months scaled to a year, and measured incidents. The gain-share branch divides value between vendor and client and is not added to the others.</p>`,
    });
  }

  // ------------------------------------------------------------------------------------------ 4
  async function chapterSolution(meta, r) {
    const [ag, flex, acts] = await Promise.all([Shell.api("/api/agents"), Shell.api("/api/flex"), Shell.api("/api/actions")]);
    const by = Object.fromEntries(ag.agents.map((a) => [a.agent_id, a]));
    const specs = ag.agents.filter((a) => a.role === "Specialist");
    const s = flex.summary, rej = flex.rows.filter((x) => x.edge_verdict === "REJECT"), lim = flex.rows.filter((x) => x.edge_verdict === "LIMIT");
    const node = (a, extra = "") => `<div class="flow-node ${extra}"><div class="who">${esc(UI.AGENT_LABEL[a.agent_id] || a.agent_id)}</div><div class="what">${esc(a.description)}</div>
      <div class="tools">reads ${esc(a.reads.join(", "))}</div></div>`;
    const flow = `<div class="flow-step">1 · The lead</div>${node(by.optimization_orchestrator)}
      <div class="flow-arrow">asks, in parallel</div><div class="flow-step">2 · Specialists, working together</div><div class="flow-row">${specs.map((a) => node(a)).join("")}</div>
      <div class="flow-arrow">plan goes to review</div><div class="flow-step">3 · The reviewer</div>${node(by.safety_auditor)}
      <div class="flow-arrow">every action is checked where the plant runs</div><div class="flow-step">The edge · between review and sign-off</div>
      <div class="flow-node edge"><div class="who">Edge interlock engine <span class="badge b-idle">not an LLM</span></div>
        <div class="what">Today's plan: ${num(s.accepted)} accepted, ${num(s.limited)} limited, ${num(s.rejected)} rejected; slowest decision ${num(s.max_action_decision_ms, 2)} ms (simulated). Firm ${num(s.firm_reduction_kw)} kW against ${num(flex.target_kw)} kW.</div>
        ${rej.map((x) => `<div class="tools">REJECT ${esc(x.asset_label)} (${esc(x.rule_ids.join(", "))}): ${esc(x.edge_reason)}</div>`).join("")}
        ${lim.slice(0, 2).map((x) => `<div class="tools">LIMIT ${esc(x.asset_label)}: ${esc(x.edge_reason)}</div>`).join("")}</div>
      <div class="flow-arrow">nothing moves until</div><div class="flow-step">4 · Your sign-off</div>
      <div class="flow-node signoff"><div class="who">A named person holds for ${num(SignOff.HOLD_MS / 1000)} seconds</div><div class="what">${num(acts.filter((a) => a.status === "pending").length)} actions waiting now. On approval the edge re-checks the plan at dispatch and one audit record is written.</div></div>`;
    const arch = [
      ["Plant data", "Seeded generator writes the tables", "ME96 meters, MELSEC iQ-R and ICONICS over OPC UA / MQTT, Pub/Sub and Dataflow into BigQuery"],
      ["Edge control", "Deterministic interlock engine in Python", "The same rules as signed code on Google Distributed Cloud connected next to the PLCs, running air-gapped if the link drops"],
      ["Weather", "Simulated ensemble summary (p10, p50, p90)", "WeatherNext 3 hourly ensembles through BigQuery"],
      ["Market", "Synthetic JEPX, reserve margin and imbalance tables", "JEPX and aggregator APIs behind Apigee"],
      ["Agents", "ADK runner in the server process", "Agent Runtime (formerly Vertex AI Agent Engine) on Gemini Enterprise Agent Platform"],
      ["Screens", "This server on one machine", "Cloud Run behind IAP"],
      ["Policy search", "Hand-tuned forecast-aware battery policy", "AlphaEvolve search over the policy family, shown in the Energy Lab demo"],
      ["Other clouds", "Not exercised", "Connectors to the AWS or Azure estate already in place; ICONICS and Serendie data stay in open formats"],
    ];
    frame({
      meta, tables: [...new Set([...flex.source])],
      h1: "A question passes the lead, the specialists, a reviewer and the plant's own interlocks before anyone signs.",
      lede: [`${esc(r.statements.no_partnership.text)} (${esc(r.statements.no_partnership.cite)}) This design is therefore a proposal, built to sit beside the clouds the plant already uses: the agents run on Google Cloud, the interlocks run in the plant, and the data stays portable.`,
        "Cloud agents propose. The edge disposes. A named person confirms."],
      blocks: [
        card("c12", "How a question moves", flow),
        card("c12", "Demo simulates, production uses", `<div class="table-scroll"><table class="data"><thead><tr><th>Layer</th><th>This demo simulates</th><th>Production uses</th></tr></thead><tbody>${arch.map((a) =>
          `<tr><td>${esc(a[0])}</td><td>${esc(a[1])}</td><td>${esc(a[2])}</td></tr>`).join("")}</tbody></table></div>
          <p class="muted" style="font-size:13px">${esc(r.statements.gdc_japan.text)}${cite(r.statements.gdc_japan.cite)} ${esc(r.statements.agent_platform_names.text)}${cite(r.statements.agent_platform_names.cite)}</p>`),
        card("c12", "The agents", `<div class="table-scroll"><table class="data"><thead><tr><th>Agent</th><th>Role</th><th>Pattern</th><th>Model tier</th><th>Sign-off</th><th>Reads</th></tr></thead><tbody>${ag.agents.map((a) =>
          `<tr><td>${esc(UI.AGENT_LABEL[a.agent_id] || a.agent_id)}<span class="cite">${esc(a.agent_id)}</span></td><td>${esc(a.role)}</td><td>${esc(a.pattern)}</td><td>${esc(a.tier)}</td>`
          + `<td>${a.hitl_required ? '<span class="badge b-warn">SIGN-OFF</span>' : '<span class="badge b-idle">advisory</span>'}</td><td class="dim">${esc(a.reads.join(", "))}</td></tr>`).join("")}</tbody></table></div>`),
      ],
      before: "Advice arrives as a spreadsheet or a chat message: no record of which figure came from where, no check against the controllers, and no clear moment when a person said yes.",
      after: `Every figure carries its table, every action carries an edge verdict and a rule, and every change waits for a ${num(SignOff.HOLD_MS / 1000)}-second hold that writes an audit record.`,
      techHint: "tools per agent",
      tech: `<dl class="kv">${ag.agents.map((a) => `<dt>${esc(a.agent_id)}</dt><dd>${esc(a.tools.join(", "))}</dd>`).join("")}</dl>`,
    });
  }

  // ------------------------------------------------------------------------------------------ 5
  async function chapterProof(meta, r) {
    const pf = await Shell.api("/api/proof");
    const a = pf.adk, g = pf.grounding.summary || {}, sf = pf.safety.summary || {}, pt = pf.pytest, w = pf.worked_example;
    const sc = (v) => (v === null || v === undefined ? "n/a" : num(v, 2));
    frame({
      meta, tables: pf.source,
      h1: "The agents were tested the way a plant tests a new operator: against the data, and against bad instructions.",
      lede: [`Final run: <b>${num(a.pass_first)} of ${num(a.total)}</b> agent evaluation cases passed on the first attempt, <b>${num(g.grounded)} of ${num(g.total)}</b> scenario answers matched figures recomputed from the data, and <b>${num(sf.passed)} of ${num(sf.total)}</b> safety probes held. Earlier runs, shown below, did not all pass; what failed and how it was fixed is part of the proof.`],
      blocks: [
        card("c12", "Pass counts, honest denominators", `<div class="statline">${stat(`${num(a.pass_first)} / ${num(a.total)}`, "Agent evaluation, first attempt", a.criteria.join(" · "))}
          ${stat(`${num(g.grounded)} / ${num(g.total)}`, "Grounded answers", `${num(g.unverifiable)} unverifiable, ${num(g.ungrounded)} ungrounded`)}
          ${stat(`${num(sf.passed)} / ${num(sf.total)}`, "Safety probes", `no execute tool in the agent tree: ${pf.safety.static && pf.safety.static.no_execute_tool_in_agent_tree ? "confirmed" : "NOT CONFIRMED"}`)}
          ${stat(pt ? `${num(pt.passed)}` : Shell.fig(null), "Unit and property tests passed", pt ? `${num(pt.skipped)} skipped: ${pt.skipped_reason}` : "")}</div>`),
        card("c12", "One worked grounding example", `<dl class="kv"><dt>Question</dt><dd>${esc(w.question)}</dd>
          <dt>Truth, computed now</dt><dd><code>${esc(w.sql)}</code><br>${Object.entries(w.truth).map(([k, v]) => `${esc(k)} = <b>${num(v, 1)}</b>`).join(" · ")}</dd>
          <dt>What the agent said</dt><dd>“${esc(w.reply_excerpt || "NOT IN THE DATA")}”</dd>
          <dt>Verdict</dt><dd><span class="badge ${w.label === "GROUNDED" ? "b-ok" : "b-crit"}">${esc(w.label)}</span> ${w.checks.map((c) => `${esc(c.figure)}: ${c.matched ? "matched" : "missing"}`).join(" · ")}</dd></dl>`),
        card("c12", "Agent evaluation, case by case", `<div class="table-scroll"><table class="data"><thead><tr><th>Case</th><th>Set</th><th>Result</th><th>Trajectory</th><th>Rubric</th><th>Hallucination</th><th>Seconds</th></tr></thead><tbody>${a.cases.map((c) =>
          `<tr><td><code>${esc(c.id)}</code></td><td>${esc(c.set)}</td><td><span class="badge ${c.first === "PASSED" ? "b-ok" : "b-crit"}">${esc(c.first)}</span></td>`
          + `<td class="num">${sc(c.metrics.tool_trajectory_avg_score)}</td><td class="num">${sc(c.metrics.rubric_based_final_response_quality_v1)}</td><td class="num">${sc(c.metrics.hallucinations_v1)}</td><td class="num">${num(c.latency_s, 1)}</td></tr>`).join("")}</tbody></table></div>`),
        card("c6", "Safety probes", `<ul class="tight">${pf.safety.probes.map((p) => `<li><span class="badge ${p.passed ? "b-ok" : "b-crit"}">${p.passed ? "held" : "failed"}</span> <span class="mono dim">${esc(p.category)}</span> ${esc(p.prompt)}</li>`).join("")}</ul>`),
        card("c6", "Run history", `<table class="data"><thead><tr><th>Run</th><th>Cases</th><th>First attempt</th><th>After one retry</th><th>Failed first</th></tr></thead><tbody>${pf.runs.map((x) =>
          `<tr><td>${esc(x.run.replaceAll("_", " "))}</td><td class="num">${num(x.cases)}</td><td class="num">${num(x.pass_first)}</td><td class="num">${num(x.pass_after_retry)}</td><td class="dim">${esc(x.failed_first.join(", ") || "none")}</td></tr>`).join("")}</tbody></table>
          <div class="note" style="margin-top:12px"><strong>Limits</strong><br>Each case ran once in the final run, so the pass count is not a rate; the earlier runs are the evidence of variance. The judge shares a model family with the agents; the grounding and safety checks do not use a judge.</div>`),
      ],
      before: "A demo that asks to be trusted: plausible numbers, no record of where they came from, and no test of what happens when someone asks for something unsafe.",
      after: "A copilot that is checked like an operator: every figure against the data, every refusal against the rules, and every failure written down.",
      techHint: "what each suite measures",
      tech: `<dl class="kv"><dt>Agent evaluation</dt><dd>ADK AgentEvaluator: tool trajectory (the specialist and its key tool), rubric-based response quality (shared and case rubrics), and hallucinations (each sentence supported by a tool result).</dd>
        <dt>Grounding</dt><dd>Truth is computed by SQL at test time, never stored; an answer is grounded only if tools were called and every key figure matches within tolerance.</dd>
        <dt>Safety</dt><dd>Structural checks on the captured run: no unsafe asset in any proposal, no execute call, no claim of execution, the expected explanation present.</dd>
        <dt>Latency</dt><dd>Agent evaluation cases took ${a.latency_s ? `${num(a.latency_s[0], 1)} to ${num(a.latency_s[1], 1)}` : "NOT IN THE DATA"} seconds.</dd></dl>`,
    });
  }
})();
