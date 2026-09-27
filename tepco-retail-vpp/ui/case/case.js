/* The case for change: five numbered chapters, one argument. Each chapter opens on a statement (not a label), shows
 * two to four pieces of evidence from /api, names what it replaces, keeps the technical detail in a drawer, and ends
 * on the next chapter. Technology is not named before chapter 4. Every figure comes from /api. */
(function () {
  const D = window.Desk;
  const { esc, num, money, moneyRange, f, el } = D;
  const PAGE = document.body.dataset.page;
  const HOLD = window.SignOff.HOLD_MS / 1000;
  const main = el("chapter");
  const research = (r) => r ? `<div class="note info" style="margin-top:12px"><strong>What the research says</strong><br>${esc(r.claim)}
      <span class="cite mono" style="display:block;color:var(--fg-dim);font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-top:4px">${esc(r.cite)} · ${esc(r.ref)}</span></div>` : "";
  const caption = (list) => `<div class="foot">Source: ${esc((list || []).map(D.srcShort).join(", "))}</div>`;

  function render(ch) {
    Shell.mountNav("case", ch.key);
    main.innerHTML =
      `<section class="hero read reveal"><div class="eyebrow">${esc(ch.n)} · ${esc(ch.eyebrow)}</div><h1>${esc(ch.headline)}</h1>` +
      ch.lede.map((p) => `<p class="lede">${esc(p)}</p>`).join("") + `</section>` +
      ch.blocks.map((b, i) => `<section class="${b.wide ? "" : "read"}"><div class="eyebrow reveal">${esc(b.eyebrow || `Evidence ${i + 1}`)}</div>
        <h2 class="reveal">${esc(b.title)}</h2>${b.lede ? `<p class="lede reveal">${esc(b.lede)}</p>` : ""}<div class="reveal">${b.html}</div></section>`).join("") +
      `<section class="read"><div class="eyebrow reveal">What it replaces</div><div class="before-after reveal">
        <div class="card"><div class="card-cap">Before</div><p>${esc(ch.replaces[0])}</p></div>
        <div class="card after"><div class="card-cap">With the desk</div><p>${esc(ch.replaces[1])}</p></div></div></section>` +
      `<section class="read reveal">${Shell.technicalDrawer(ch.tech, ch.techHint)}</section>` +
      `<div id="prov"></div>` + D.next(ch.next[0], ch.next[1]);
    ch.blocks.forEach((b) => b.after && b.after());
    D.provenance(ch.prov || []).then((h) => { el("prov").innerHTML = h; Motion.reveal(); });
    Motion.reveal();
  }

  /* ================================================================== 1 · The case */
  async function chCase() {
    const [facts, cs, pos] = await Promise.all([Shell.api("/api/story/facts"), Shell.api("/api/story/case"), Shell.api("/api/position")]);
    const o = cs.october;
    const rise = 100 * (o.do_nothing_october_jpy / o.do_nothing_now_jpy - 1);
    const months = cs.monthly_spot.map((m) => `${m.month}: ${num(m.tokyo, 1)} JPY/kWh`).join(", ");
    render({
      n: "1", key: "case", eyebrow: "The case", headline: "Every half hour is now a financial decision with a deadline.",
      lede: [
        `This balancing group plans and settles in half hours. This evening it is ${f(facts.short_mwh, "MWh")} short across four of them, ` +
        `and the first gate closes at ${facts.clock.gate_closure.slice(11)}. Left open on today's penalty curve, the short costs an expected ` +
        `${money(o.do_nothing_now_jpy)}.`,
        `On the curve that applies from the start of October, the same evening costs ${money(o.do_nothing_october_jpy)}, ` +
        `${num(rise, 0)}% more, and the intraday market that could cover it becomes machine to machine the same day. The desk has to ` +
        `decide faster, on better numbers, with fewer people in the loop for the routine and more scrutiny for the exceptional.`,
      ],
      blocks: [
        { eyebrow: "Evidence 1", title: "Every half hour is a decision, and the evening ones are the expensive ones", wide: true,
          lede: "Open position per half hour today. Bars below zero are short; delivered half hours are faded; half hours to the right of the gate marker can still be traded.",
          html: `<div class="card"><div class="chart" id="c-pos" role="img" aria-label="Open position per half hour, 19 August"></div>${caption(pos.source)}</div>${research(cs.research.balancing)}`,
          after: () => {
            const rows = pos.slots;
            D.chart(el("c-pos"), {
              legend: { data: ["Short", "Long or flat"] },
              xAxis: { type: "category", data: rows.map((r) => r.time.slice(0, 5)), axisLabel: { interval: 5 } },
              yAxis: { type: "value", name: "MWh" },
              series: [
                { name: "Short", type: "bar", stack: "p", data: rows.map((r) => r.open_position < -0.5 ? { value: r.open_position, itemStyle: { opacity: r.gate_status === "delivered" ? 0.45 : 1 } } : null), color: D.hue(4), barWidth: "70%",
                  itemStyle: { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: 0.8, color: "rgba(0,0,0,.35)" } },
                  markLine: { symbol: "none", silent: true, lineStyle: { color: D.css("--fg-muted"), type: "dashed" }, label: { color: D.css("--fg-muted"), fontFamily: "JetBrains Mono", fontSize: 10, formatter: "gate open from here" },
                    data: [{ xAxis: rows.findIndex((r) => r.gate_status === "open") }] } },
                { name: "Long or flat", type: "bar", stack: "p", data: rows.map((r) => r.open_position >= -0.5 ? { value: r.open_position, itemStyle: { opacity: r.gate_status === "delivered" ? 0.45 : 1 } } : null), color: D.hue(2) },
              ],
              tooltip: { valueFormatter: (v) => (v === null || v === undefined ? "" : `${num(v, 1)} MWh`) },
            });
          } },
        { eyebrow: "Evidence 2", title: "The price regime moved, and it moved up", wide: true,
          lede: `Tokyo area spot, daily mean, June to August in this data. Monthly means: ${months}.`,
          html: `<div class="card"><div class="chart" id="c-spot" role="img" aria-label="Daily mean spot price"></div>${caption(cs.source.filter((s) => s.includes("spot")))}</div>${research(cs.research.prices)}`,
          after: () => D.chart(el("c-spot"), {
            legend: { data: ["Tokyo area", "System"] },
            xAxis: { type: "category", data: cs.daily_spot.map((d) => d.date.slice(5)), axisLabel: { interval: 13 } },
            yAxis: { type: "value", name: "JPY/kWh" },
            series: [{ name: "Tokyo area", type: "line", showSymbol: false, data: cs.daily_spot.map((d) => d.tokyo), lineStyle: { width: 1.6 } },
                     { name: "System", type: "line", showSymbol: false, data: cs.daily_spot.map((d) => d.system), lineStyle: { width: 1.2 }, color: D.hue(1) }],
            tooltip: { valueFormatter: (v) => `${num(v, 2)} JPY/kWh` } }) },
        { eyebrow: "Evidence 3", title: "The penalty curve steepens in October",
          lede: "The same four half hours, priced on today's imbalance curve and on the one that applies from October, at this evening's forecast reserve margin.",
          html: `<div class="card"><div class="table-scroll"><table class="data"><thead><tr><th>Half hour</th><th>Reserve margin</th><th>Short</th><th>Imbalance today</th><th>From October</th></tr></thead><tbody>${
            o.slots.map((s) => `<tr><td>${esc(s.time)}</td><td class="num">${num(s.reserve_margin_pct, 1)}%</td><td class="num">${num(s.short_mwh, 1)} MWh</td><td class="num">${num(s.imbalance_now_jpy_kwh, 1)} JPY/kWh</td><td class="num">${num(s.imbalance_october_jpy_kwh, 1)} JPY/kWh</td></tr>`).join("")
          }<tr><td><b>Expected cost if left open</b></td><td></td><td></td><td class="num"><b>${esc(money(o.do_nothing_now_jpy))}</b></td><td class="num"><b>${esc(money(o.do_nothing_october_jpy))}</b></td></tr></tbody></table></div>${caption(cs.source.filter((s) => s.includes("imbalance") || s.includes("balance")))}</div>${research(cs.research.scarcity)}` },
        { eyebrow: "Evidence 4", title: "The new demand buys power by the hour, not by the year",
          lede: "The enterprise pipeline in this data, and what each prospect asks for.",
          html: `<div class="card"><div class="table-scroll"><table class="data"><thead><tr><th>Prospect</th><th>Site</th><th>Load a year</th><th>Peak</th><th>Clean share asked for, hour by hour</th></tr></thead><tbody>${
            cs.prospects.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.site)}</td><td class="num">${num(p.projected_annual_gwh, 1)} GWh</td><td class="num">${num(p.projected_peak_mw, 1)} MW</td><td class="num">${num(p.cfe_ambition_pct, 0)}%</td></tr>`).join("")
          }</tbody></table></div>${caption(["prospects", "prospect_load_hourly"])}</div>${research(cs.research.growth)}` },
      ],
      replaces: [`Several screens and a spreadsheet, ${facts.clock.minutes_left} minutes before the gate, and a phone call to ask whether a battery pool is really there. The penalty is known only after settlement.`,
                 `One question to the desk: the short, every way to cover it, what each costs against the penalty, checked against policy and waiting for one person's ${HOLD}-second hold.`],
      tech: `<p>The penalty curve used in Evidence 3: ${esc(o.method)}.</p><dl class="kv">${["today", "october"].map((k) => { const c = cs.curves[k];
             return `<dt>${k === "today" ? "Today" : "From October"}</dt><dd>cap ${num(c.cap_jpy_kwh, 0)} JPY/kWh at ${num(c.cap_at_margin_pct, 0)}% reserve margin, ${num(c.d_jpy_kwh, 0)} JPY/kWh at ${num(c.d_at_margin_pct, 0)}%, no uplift from ${num(c.no_uplift_from_pct, 0)}% (${esc(c.valid)})</dd>`; }).join("")}
             <dt>Source</dt><dd>${esc(cs.curves.cite)} (${esc(cs.curves.ref)})</dd></dl>`,
      techHint: "the imbalance curves and how the October figure is computed",
      prov: [["This chapter", "/api/story/facts, /api/story/case, /api/position"]],
      next: ["/case/gap.html", "2 · The gap"],
    });
  }

  /* ================================================================== 2 · The gap */
  async function chGap() {
    const [plan, gap, heat, cs] = await Promise.all([Shell.api("/api/story/plan"), Shell.api("/api/story/gap"),
      Shell.api("/api/cfe/heatmap?customer_id=C-0001&month=2026-08"), Shell.api("/api/story/case")]);
    const t = plan.totals, rows = plan.per_slot;
    const byHour = Array.from({ length: 24 }, (_, h) => { const c = heat.cells.filter((x) => x.hour === h && x.matched_pct !== null); return c.length ? c.reduce((a, x) => a + x.matched_pct, 0) / c.length : null; });
    const sc = heat.score;
    const classes = Object.entries(plan.fleet_by_class);
    const nice = { residential_battery: "Home batteries", cni_bess: "Business batteries", dr_load: "Demand response", ev_depot: "EV depots", heat_pump_water_heater: "Heat pumps" };
    render({
      n: "2", key: "gap", eyebrow: "The gap", headline: "Every number the desk needs exists. They do not meet before the gate.",
      lede: [
        `The short is ${f(t.short_mwh, "MWh")}. Cover exists: ${f(t.vpp_mwh, "MWh")} from batteries and demand response the desk can trust, and ` +
        `${f(t.intraday_mwh, "MWh")} in a thin intraday book. Together they cost ${money(t.plan_cost_jpy)} against an expected ` +
        `${money(t.do_nothing_expected_cost_p50_jpy)} if nothing is done.`,
        "The gap is not missing data. It is that the position, the order book, the fleet's health and the grid commitments live in different places, and the one person who could join them has minutes.",
      ],
      blocks: [
        { title: "Cover, half hour by half hour", wide: true,
          lede: "The least-cost mix for each short half hour. Imbalance is never chosen as a cheaper option; a residual would appear only if cover were physically unavailable.",
          html: `<div class="card"><div class="chart" id="c-cover" role="img" aria-label="Cover per half hour"></div>${caption(plan.source)}</div>`,
          after: () => D.chart(el("c-cover"), {
            legend: { data: ["Batteries and demand response", "Intraday at best ask", "Intraday, second level", "Left open", "Short"] },
            xAxis: { type: "category", data: rows.map((r) => r.time) }, yAxis: { type: "value", name: "MWh" }, grid: { top: 56 },
            series: [
              { name: "Batteries and demand response", type: "bar", stack: "c", data: rows.map((r) => r.vpp_mwh), color: D.hue(2), barWidth: "46%" },
              { name: "Intraday at best ask", type: "bar", stack: "c", data: rows.map((r) => r.intraday_level1_mwh), color: D.hue(0) },
              { name: "Intraday, second level", type: "bar", stack: "c", data: rows.map((r) => r.intraday_level2_mwh), color: D.hue(1) },
              { name: "Left open", type: "bar", stack: "c", data: rows.map((r) => r.residual_mwh), color: D.hue(4) },
              { name: "Short", type: "line", data: rows.map((r) => r.short_mwh), color: D.css("--fg"), symbol: "rect", symbolSize: 8, lineStyle: { type: "dashed", width: 1 } },
            ], tooltip: { valueFormatter: (v) => `${num(v, 2)} MWh` } }) },
        { title: "What each kilowatt-hour costs in the scarcity half hours", wide: true,
          lede: "Batteries and demand response are cheapest, the intraday book is dearer and thin, and the imbalance price is dearer still, with its p90 at the cap.",
          html: `<div class="card"><div class="chart" id="c-ladder" role="img" aria-label="Price ladder"></div>${caption(["vpp_clusters", "jepx_intraday_30min", "imbalance_30min"])}</div>`,
          after: () => D.chart(el("c-ladder"), {
            legend: { data: ["Batteries and DR, average", "Intraday best ask", "Intraday second level", "Imbalance p50", "Imbalance p90"] },
            xAxis: { type: "category", data: rows.map((r) => r.time) }, yAxis: { type: "value", name: "JPY/kWh" }, grid: { top: 56 },
            series: [
              { name: "Batteries and DR, average", type: "line", data: rows.map((r) => r.vpp_mwh ? r.vpp_cost_jpy / (r.vpp_mwh * 1000) : null), color: D.hue(2), symbol: "circle" },
              { name: "Intraday best ask", type: "line", data: rows.map((r) => r.intraday_level1_price_jpy_kwh), color: D.hue(0), symbol: "rect" },
              { name: "Intraday second level", type: "line", data: rows.map((r) => r.intraday_level2_price_jpy_kwh), color: D.hue(1), symbol: "triangle" },
              { name: "Imbalance p50", type: "line", data: rows.map((r) => r.imbalance_p50_jpy_kwh), color: D.hue(4), symbol: "diamond" },
              { name: "Imbalance p90", type: "line", data: rows.map((r) => r.imbalance_p90_jpy_kwh), color: D.hue(3), lineStyle: { type: "dashed" }, symbol: "none" },
            ], tooltip: { valueFormatter: (v) => (v === null || v === undefined ? "" : `${num(v, 1)} JPY/kWh`) } }) },
        { title: "What the fleet reports against what it can deliver", wide: true,
          lede: `Power at ${rows[0].time.slice(0, 5)} by kind of resource. Capacity already sold to the grid operator must be held back, and ${plan.excluded.map((x) => x.cluster_id).join(", ") || "no pool"} ${plan.excluded.length === 1 ? "has" : "have"} sent no trustworthy heartbeat for hours.`,
          html: `<div class="card"><div class="chart" id="c-fleet" role="img" aria-label="Fleet by class"></div>
            ${plan.excluded.map((x) => `<div class="note crit" style="margin-top:12px"><strong>${esc(x.cluster_id)} is excluded</strong><br>${esc(x.reasons.join("; "))}${x.commitments_at_risk.length ? `. It also carries grid commitment ${esc(x.commitments_at_risk.join(", "))}, which needs a trusted substitute.` : ""}</div>`).join("")}
            ${caption(["vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments"])}</div>`,
          after: () => D.chart(el("c-fleet"), {
            legend: { data: ["Reported available", "Can be counted on", "Sold to the grid operator", "Untrusted"] },
            xAxis: { type: "category", data: classes.map(([k]) => nice[k] || k), axisLabel: { interval: 0 } }, yAxis: { type: "value", name: "MW" }, grid: { top: 56 },
            series: [
              { name: "Reported available", type: "bar", data: classes.map(([, v]) => v.available_mw), color: D.css("--bx") },
              { name: "Can be counted on", type: "bar", data: classes.map(([, v]) => v.dispatchable_mw), color: D.hue(0) },
              { name: "Sold to the grid operator", type: "bar", data: classes.map(([, v]) => v.committed_mw), color: D.hue(1) },
              { name: "Untrusted", type: "bar", data: classes.map(([, v]) => v.untrusted_mw), color: D.hue(4) },
            ], tooltip: { valueFormatter: (v) => `${num(v, 1)} MW` } }) },
        { title: "Two gaps that never reach a dashboard", wide: true,
          lede: `${sc.name} reads ${num(sc.annual_style_volumetric_match_pct, 1)}% clean on an annual view, but only ${num(sc.contracted_hourly_matched_pct, 1)}% hour by hour, and least in the evening. ` +
                `Separately, if spot rises ${num(cs.margin.price_shock_pct, 0)}% from ${cs.margin.from_date} to ${cs.margin.to_date}, ${money(cs.margin.margin_at_risk_jpy)} of margin is at risk, all of it on fixed and bandwidth tariffs.`,
          html: `<div class="split"><div class="card"><div class="card-cap">Matched hour by hour, by hour of day</div><div class="chart short" id="c-cfe" role="img" aria-label="Hourly matched share"></div>${caption(heat.source)}</div>
                 <div class="card"><div class="card-cap">Margin lost at +${num(cs.margin.price_shock_pct, 0)}% spot, by tariff</div><div class="chart short" id="c-mar" role="img" aria-label="Margin at risk by tariff"></div>${caption(cs.source.filter((s) => s.includes("forecast")))}</div></div>`,
          after: () => {
            D.chart(el("c-cfe"), { legend: false, xAxis: { type: "category", data: byHour.map((_, h) => String(h).padStart(2, "0")), axisLabel: { interval: 3 } },
              yAxis: { type: "value", name: "%", max: 120 }, grid: { top: 26 },
              series: [{ type: "bar", data: byHour, color: D.hue(3), markLine: { symbol: "none", lineStyle: { color: D.css("--fg-muted"), type: "dashed" },
                label: { color: D.css("--fg-muted"), fontSize: 10, fontFamily: "JetBrains Mono", formatter: `annual view ${num(sc.annual_style_volumetric_match_pct, 1)}%`, position: "insideEndTop" },
                data: [{ yAxis: sc.annual_style_volumetric_match_pct }] } }], tooltip: { valueFormatter: (v) => `${num(v, 1)}%` } });
            const mt = Object.entries(cs.margin_by_tariff);
            D.chart(el("c-mar"), { legend: false, xAxis: { type: "category", data: mt.map(([k]) => k.replace("_", " ")) }, yAxis: { type: "value", name: "M JPY" }, grid: { top: 26 },
              series: [{ type: "bar", data: mt.map(([, v]) => v.margin_loss_jpy / 1e6), color: D.hue(4), barWidth: "40%" }], tooltip: { valueFormatter: (v) => `${num(v, 1)}M JPY` } });
          } },
      ],
      replaces: ["Each figure sits in its own system: the position in the balancing tool, the book on the exchange screen, battery health with the aggregator, commitments in the balancing-market portal, clean-energy claims in a spreadsheet.",
                 "The same figures meet in one place, per half hour, with the rules applied: untrusted pools out, sold capacity held back, imbalance never chosen, hourly and annual claims kept apart."],
      tech: `<p>${esc(gap.note)}</p><dl class="kv"><dt>Cover plan</dt><dd>a linear program over the short half hours: batteries per pool (power and shared energy limits), two intraday price levels (book depth), and a residual priced far above any market price so that imbalance is never an economic choice</dd>
             <dt>Rules applied</dt><dd>${plan.rules.map(esc).join("<br>")}</dd><dt>Hourly score</dt><dd>contracted clean energy matched in the same hour, capped at the load, plus the grid's clean share on the rest; surplus in one hour never offsets another</dd></dl>`,
      techHint: "how the cover plan and the hourly score are computed",
      prov: [["This chapter", "/api/story/plan, /api/story/gap, /api/cfe/heatmap, /api/story/case"]],
      next: ["/case/prize.html", "3 · The prize"],
    });
  }

  /* ================================================================== 3 · The prize */
  async function chPrize() {
    const prize = await Shell.api("/api/story/prize");
    const priced = prize.branches.filter((b) => b.high !== null);
    const max = Math.max(...priced.map((b) => b.high)) * 1.08;
    const rowsHtml = prize.branches.map((b) => {
      const hue = `var(--${b.hue})`;
      const bar = b.high === null
        ? ""
        : `<div class="vbar" aria-hidden="true"><i style="left:${(b.low / max) * 100}%;width:${Math.max(0.6, ((b.high - b.low) / max) * 100)}%;background:${hue}"></i></div>
           <div class="vbar-scale"><span>0</span><span>${esc(money(max / 2))}</span><span>${esc(money(max))}</span></div>`;
      return `<div class="vrow"><div class="vcode" style="color:${hue};border-color:${hue}">${esc(b.code)}</div><div>
        <h3>${esc(b.title)} <span class="pill" style="margin-left:6px">APQC ${esc(b.apqc)}</span></h3>
        <div class="mech">${esc(b.mechanism)}</div>
        <div class="rng">${b.high === null ? '<span class="nodata">NOT IN THE DATA</span><small>no verified figure held</small>' : `${esc(moneyRange(b.low, b.high))}<small>${esc(b.unit)}</small>`}</div>
        ${bar}<div class="basis">Basis: ${esc(b.basis)}</div><div class="basis">Assumption: ${esc(b.assumption)}</div></div></div>`;
    }).join("");
    render({
      n: "3", key: "prize", eyebrow: "The prize", headline: "The value divides five ways, and none of it is counted twice.",
      lede: [prize.scale_note, "Every line names the mechanism that produces it and the assumption it rests on. A branch the data cannot price says so rather than borrowing a number."],
      blocks: [
        { eyebrow: "Value by branch", title: "Ranges, each with its mechanism", wide: true,
          html: `<div class="card"><div class="legend" style="margin-bottom:6px">${prize.branches.map((b) => `<span><b style="color:var(--${b.hue})">${esc(b.code)}</b> APQC ${esc(b.apqc)}</span>`).join("")}</div>${rowsHtml}</div>` },
      ],
      replaces: ["A single-point business case with one headline number, a model nobody outside finance can open, and the same value claimed by several initiatives at once.",
                 "Ranges on a mutually exclusive tree, each computed from this data and a stated assumption, so a board can challenge the assumption instead of the arithmetic."],
      tech: `<dl class="kv">${prize.branches.map((b) => `<dt>${esc(b.code)} · APQC ${esc(b.apqc)}</dt><dd>${esc(b.title)}: ${esc(b.basis)}. Assumption: ${esc(b.assumption)}.</dd>`).join("")}</dl>
             <p class="foot">The branches follow the issue tree in docs/PRD.md section 5. The units differ (per year, per stress window, per campus), so the ranges are read side by side and never added.</p>`,
      techHint: "how every range is computed",
      prov: [["This chapter", "/api/story/prize"]],
      next: ["/case/solution.html", "4 · The solution"],
    });
  }

  /* ================================================================== 4 · The solution */
  async function chSolution() {
    const [ag, proof, cs] = await Promise.all([Shell.api("/api/agents"), Shell.api("/api/story/proof"), Shell.api("/api/story/case")]);
    const A = ag.agents, lead = A.find((a) => a.step === 1), specs = A.filter((a) => a.step === 2), rev = A.find((a) => a.step === 3);
    const node = (a) => `<div class="flow-node"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="mono" style="color:var(--accent)">${esc(a.code)}</span>
      <span class="who">${esc(a.title)}</span>${a.sign_off ? '<span class="badge b-warn">sign-off</span>' : ""}</div>
      <div class="what">${esc(a.name)} · ${esc(a.tier)} tier · ${a.tool_count} tools</div></div>`;
    const flow = `<div class="card"><div class="flow-step">1 · The lead</div>${node(lead)}<div class="flow-arrow">asks, one at a time</div>
      <div class="flow-step">2 · Specialists, working together</div><div class="flow-row">${specs.map(node).join("")}</div><div class="flow-arrow">every proposal goes to</div>
      <div class="flow-step">3 · The reviewer</div>${node(rev)}<div class="flow-arrow">only then</div>
      <div class="flow-step">4 · Your sign-off</div><div class="flow-node signoff"><div class="who">A person holds for ${HOLD} seconds</div>
      <div class="what">the sheet shows what the proposal could not settle, the agent's case and what it read; approval runs in a sandbox and writes an audit record</div></div></div>`;
    const w = proof.worked_example;
    const path = w ? `<div class="card"><div class="card-cap">${esc(w.question)}</div><pre class="console">${w.tool_calls.map((c) => { const [who, tool] = c.split(":"); return `<span class="dim">${esc(who)}</span> → ${esc(tool)}`; }).join("\n")}</pre>
      <div class="foot">${w.tool_calls.length} steps, ${num(w.latency_s, 1)} s end to end in the last grounding run. Source: eval/results/grounding_results.json</div></div>` :
      '<div class="note">The worked path is not available: no grounding run has been recorded.</div>';
    const arch = [
      ["Sources", [
        ["Exchange prices and order book", "spot and intraday tables with an order-book snapshot at the desk clock", "the JEPX trading API through Apigee (server to server, mutual TLS, quotas, audit)"],
        ["Grid operator signals", "imbalance and reserve-margin tables with forecast bands", "OCCTO reserve-margin feeds and the imbalance price central system"],
        ["Customer meters", "half-hourly load per customer", "the transmission operator's meter data service"],
        ["Batteries, heat pumps, EV depots, demand response", "a telemetry table per pool, including one frozen feed", "aggregator gateways streaming heartbeats and state of charge through Pub/Sub and Dataflow"],
        ["Weather", "an ensemble forecast table for grid cells across Kanto", "WeatherNext 3 hourly ensembles from BigQuery and Earth Engine"],
        ["Clean energy certificates", "a half-hourly claim ledger with planted faults", "a Powerledger-style provenance ledger, reconciled with tracked JEPX certificates"]]],
      ["Store", [["One analytical store", "CSV files read locally, or the same tables in BigQuery", "BigQuery in Tokyo (asia-northeast1): partitioned by date, clustered by half hour, column-level security"]]],
      ["Agents", [["The desk team", `${A.length} ADK agents, run in process or deployed`, "Gemini Enterprise Agent Platform, Agent Runtime (formerly Vertex AI Agent Engine), with Sessions, Memory Bank and Model Armor"],
                  ["Deterministic tools", "the cover plan, fleet trust rules, margin at risk and the hourly clean-supply design are code, not model output", "the same code, versioned and tested"]]],
      ["Decisions", [["Sign-off and audit", `a sign-off sheet with a ${HOLD}-second hold; approval runs in a sandbox and writes an audit row`, "order management, dispatch to the aggregator platform, plan resubmission to OCCTO, audit kept in BigQuery"],
                     ["The screens", "this site, served by the demo server", "Cloud Run behind Identity-Aware Proxy"]]],
    ];
    const archHtml = arch.map(([layer, cards]) => `<div class="layer">${esc(layer)}</div><div class="arch">${cards.map(([name, sim, prod]) =>
      `<div class="card"><h4>${esc(name)}</h4><div class="sim"><b>Demo simulates</b><br>${esc(sim)}</div><div class="sim"><b>Production uses</b><br>${esc(prod)}</div></div>`).join("")}</div>`).join("");
    const writes = A.flatMap((a) => a.proposes.map((p) => `<tr><td class="mono">${esc(p)}</td><td>${esc(a.title)}</td></tr>`)).join("");
    render({
      n: "4", key: "solution", eyebrow: "The solution", headline: "One question, a team of agents, and one person's hold.",
      lede: [`A lead agent takes the question and asks ${specs.length} specialists for their part, one at a time. Every proposal goes to a reviewer before anyone sees it, ` +
             `and nothing executes until a person holds a button for ${HOLD} seconds. The arithmetic is done by tested code the agents call, not by the model.`],
      blocks: [
        { eyebrow: "Evidence 1", title: "How a question moves", html: flow },
        { eyebrow: "Evidence 2", title: "The path of one real answer", lede: "The gate-closure question, as the team actually worked it in the last evaluation run.", html: path },
        { eyebrow: "Evidence 3", title: "What the demo simulates, and what production uses", wide: true, html: `<div class="card">${archHtml}${research(cs.research.api)}</div>` },
        { eyebrow: "Evidence 4", title: "What never happens without you",
          lede: `${A.reduce((n, a) => n + a.proposes.length, 0)} tools can propose a change. None can execute one; there is no execute tool anywhere in the team.`,
          html: `<div class="card"><div class="table-scroll"><table class="data"><thead><tr><th>Proposal tool</th><th>Team</th></tr></thead><tbody>${writes}</tbody></table></div>
                 <div class="foot">Source: /api/agents (read from the agent definitions)</div></div>` },
      ],
      replaces: ["A trader re-keys numbers between systems, a colleague checks policy from memory, and the approval is an email after the order went in.",
                 `The lead gathers the numbers, the specialists apply the rules in code, the reviewer checks the exact proposal, and the approval is a recorded ${HOLD}-second hold.`],
      tech: `<div class="table-scroll"><table class="data"><thead><tr><th>Agent</th><th>Model</th><th>Tools</th><th>Reads</th></tr></thead><tbody>${A.map((a) =>
        `<tr><td><b>${esc(a.code)}</b> ${esc(a.name)}</td><td class="mono">${esc(a.model)}</td><td class="mono">${esc(a.tools.join(", "))}</td><td>${esc(a.reads.join(", "))}</td></tr>`).join("")}</tbody></table></div>`,
      techHint: "every agent, its model, tools and data",
      prov: [["This chapter", "/api/agents, /api/story/proof, /api/story/case"]],
      next: ["/case/proof.html", "5 · The proof"],
    });
  }

  /* ================================================================== 5 · The proof */
  async function chProof() {
    const p = await Shell.api("/api/story/proof");
    const w = p.worked_example;
    const suites = `<div class="card"><div class="table-scroll"><table class="data"><thead><tr><th>Suite</th><th>What it checks</th><th>First attempt</th><th>After one retry</th></tr></thead><tbody>${
      p.suites.map((s) => `<tr><td><b>${esc(s.name)}</b></td><td>${esc(s.what)}</td><td class="num">${s.first} of ${s.total}</td><td class="num">${s.after_retry} of ${s.total}</td></tr>`).join("")
    }<tr><td><b>Unit and property tests</b></td><td>Data generator, the cover plan, margin, hourly scores, compliance checks, the approval queue</td><td class="num" colspan="2">${esc(p.pytest || "NOT IN THE DATA")}</td></tr></tbody></table></div>
      <div class="foot">Live runs on Gemini; the judge is a second model. A case that failed once and passed on its one retry is marked transient; a case that failed twice is persistent.</div></div>`;
    const factRows = w ? w.facts.map((x) => {
      const opts = x.options ? x.options.map((o) => `${o.name}: ${num(o.truth, 0)}${o.matched ? " (found)" : ""}`).join("; ") : null;
      const truth = opts || (typeof x.truth === "number" ? num(x.truth, x.truth > 1000 ? 0 : 1) : (Array.isArray(x.any_of) ? `any of: ${x.any_of.join(", ")}` : "text"));
      return `<tr><td class="mono">${esc(x.name)}</td><td class="num">${esc(truth ?? "")}</td><td class="num">${esc((x.found || []).join(", "))}</td><td>${esc(x.basis || "")}</td><td><span class="badge ${x.matched ? "b-ok" : "b-crit"}">${x.matched ? "matched" : "missing"}</span></td></tr>`;
    }).join("") : "";
    const worked = w ? `<div class="card"><div class="card-cap">Question · ${esc(w.question)}</div>
      <div class="table-scroll"><table class="data"><thead><tr><th>Key figure</th><th>Truth at test time</th><th>Found in the answer</th><th>How truth was computed</th><th>Result</th></tr></thead><tbody>${factRows}</tbody></table></div>
      <div class="flow-step">Truth for the short, recomputed with SQL when the test runs</div><pre class="console">${esc(w.truth_method || "not packaged in this build")}</pre>
      <div class="flow-step">The answer, as the desk gave it (opening excerpt)</div><div class="msg">${D.md(w.reply_excerpt)}</div>
      <div class="foot">Label ${esc(w.label)} · ${esc(w.classification)} · ${num(w.latency_s, 1)} s · ${w.tool_calls.length} tool calls. Source: eval/results/grounding_results.json</div></div>`
      : '<div class="note">No grounding run is recorded.</div>';
    const bySuite = {};
    p.cases.forEach((c) => (bySuite[c.suite] = bySuite[c.suite] || []).push(c));
    const cls = { pass: "b-ok", transient: "b-warn", persistent: "b-crit", not_run: "b-idle", unverifiable: "b-idle" };
    const cases = `<div class="split">${Object.entries(bySuite).map(([s, cs]) => `<div class="card"><div class="card-cap">${esc(s)} · ${cs.length} cases</div>
      <div class="table-scroll"><table class="data"><tbody>${cs.map((c) => `<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.agent || c.desc || c.label || "")}</td><td><span class="badge ${cls[c.result] || "b-idle"}">${esc(c.result)}</span></td></tr>`).join("")}</tbody></table></div></div>`).join("")}</div>`;
    const firstTotal = p.suites.reduce((a, s) => a + s.first, 0), total = p.suites.reduce((a, s) => a + s.total, 0);
    render({
      n: "5", key: "proof", eyebrow: "The proof", headline: "Tested the way a desk tests a new trader: on the numbers.",
      lede: [`${firstTotal} of ${total} live evaluation cases passed at the first attempt across ${p.suites.length} suites; the table shows each suite and what happened on the one retry. ` +
             `Every figure in an answer is checked against truth computed from the tables when the test runs, never against a stored expectation.`],
      blocks: [
        { eyebrow: "Evidence 1", title: "What was tested, with honest denominators", wide: true, html: suites },
        { eyebrow: "Evidence 2", title: "One worked grounding example", wide: true, lede: "The gate-closure question. Each key figure in the answer is compared with the truth recomputed at test time.", html: worked },
        { eyebrow: "Evidence 3", title: "Every case, by suite", wide: true, html: cases },
        { eyebrow: "Evidence 4", title: "What this does not prove",
          html: `<div class="note"><strong>Limits of this evidence</strong><ul class="tight">
            <li>The judge for answer quality is itself a model; its scores are evidence, not proof. The grounding and safety checks are deterministic.</li>
            <li>Each case ran once plus one retry; there is no repeated sampling yet.</li>
            ${p.latency_s ? `<li>Answers took a median of ${num(p.latency_s.median, 1)} s and up to ${num(p.latency_s.max, 1)} s in the last grounding run.</li>` : ""}
            ${p.skipped.map((s) => `<li>Skipped: ${esc(s)}.</li>`).join("")}
            <li>All data is synthetic, calibrated to published market figures; nothing here reads a live market or device.</li></ul></div>` },
      ],
      replaces: ["A pilot judged on a demo that went well once, with no record of what the agent read or whether its numbers were right.",
                 "Every answer's figures checked against the tables at test time, every refusal and approval rule tested, failures kept with their evidence."],
      tech: `<dl class="kv"><dt>Agent evaluation</dt><dd>ADK AgentEvaluator: tool path (any order), rubric-based answer quality and a hallucination score, each against the threshold in eval/test_config.json</dd>
             <dt>Grounding</dt><dd>eval/grounding_eval.py: truth by SQL (and by rerunning the deterministic plans) at test time; GROUNDED only if every required tool ran and every key figure matched</dd>
             <dt>Safety</dt><dd>eval/safety_eval.py: instructions hidden in a customer bill (with the document screen on and off), refusals, and attempts to skip the human hold</dd>
             <dt>Last runs</dt><dd>${esc(Object.entries(p.run_at || {}).map(([k, v]) => `${k} ${v || "not run"}`).join(" · "))}</dd>
             <dt>Evidence</dt><dd>eval/results/ and docs/EVAL_REPORT.md</dd></dl>`,
      techHint: "how each suite works and where its evidence lives",
      prov: [["This chapter", "/api/story/proof, read from eval/results"]],
      next: ["/workspace/value.html", "Open the workspace"],
    });
  }

  const route = { case: chCase, gap: chGap, prize: chPrize, solution: chSolution, proof: chProof }[PAGE];
  route().catch((e) => D.fail(main, e));
})();
