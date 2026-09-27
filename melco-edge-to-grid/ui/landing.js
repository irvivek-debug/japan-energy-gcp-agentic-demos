/* Landing: the thesis, the gap in this plant's data against cited research, the evidence strip, two doors. */
(async function () {
  const { esc, num } = UI;
  await Shell.mountNav("landing", "/");
  const $ = (id) => document.getElementById(id);
  try {
    const [ov, flex, dr, gap, strip, meta, proof, agents, actions] = await Promise.all([
      Shell.api("/api/overview"), Shell.api("/api/flex"), Shell.api("/api/dr-events"), Shell.api("/api/gap"), Shell.api("/api/strip"),
      Shell.api("/api/meta"), Shell.api("/api/proof"), Shell.api("/api/agents"), Shell.api("/api/actions"),
    ]);
    const k = ov.kpis;
    const ev = dr.events.find((e) => e.status === "notified");
    const settled = dr.events.filter((e) => e.status === "settled");
    const perf = settled.map((e) => ({ e, p: e.performance_pct }));
    const worst = perf.reduce((a, b) => (b.p < a.p ? b : a));
    const best = perf.reduce((a, b) => (b.p > a.p ? b : a));
    const peakRow = gap.rows.find((r) => r.key === "billing_peak");

    $("lede1").innerHTML = `At <b>${esc(ev.notified_at.slice(11))}</b> the aggregator asked for <b>${num(k.dr.target_kw)} kW</b> between <b>${esc(ev.start_time)}</b> and <b>${esc(ev.end_time)}</b>. `
      + `Checked against the live plant, the flexibility already on site covers <b>${num(k.dr.firm_kw)} kW</b> firm, <b>${num(k.dr.margin_pct, 1)} %</b> more than asked, and no production line is touched.`;
    $("lede2").innerHTML = `The same plant delivered <b>${num(worst.p, 0)} %</b> of one request and <b>${num(best.p, 0)} %</b> of another, and this month's billing peak of `
      + `<b>${esc(peakRow.ordinary.split(" (")[0])}</b> was set around a DR event while the battery sat idle. The difference is timing and proof, not equipment.`;

    $("gap").innerHTML = `<thead><tr><th>Quantity</th><th>Ordinary</th><th>Best / target</th><th>The gap</th><th>What the research says is available</th></tr></thead><tbody>${gap.rows.map((r) =>
      `<tr><td>${esc(r.quantity)}</td><td>${esc(r.ordinary)}</td><td>${esc(r.best)}</td><td class="gapcell">${esc(r.gap)}</td>`
      + `<td class="research">${esc(r.research)}<span class="cite">${esc(r.cite)}</span></td></tr>`).join("")}</tbody>`;
    $("gap-note").innerHTML = `<div class="note"><strong>What the gap is</strong><br>${esc(gap.note.is)}<br><br><strong>What it is not</strong><br>${esc(gap.note.is_not)}</div>`;

    // ---- evidence strip ----
    const n = strip.times.length;
    $("strip-lede").textContent = `${strip.series.length} traces over ${num(n)} recorded hours, ${strip.window[0].replace("T", " ")} to ${strip.window[1].replace("T", " ")}. Move the scrubber and every card reads that hour.`;
    const sc = $("scrub");
    sc.max = String(n - 1); sc.value = String(n - 1);
    const badgeCls = { ok: "b-ok", warn: "b-warn", crit: "b-crit", idle: "b-idle" };
    const WIN = 48;
    function draw(i) {
      $("scrub-at").textContent = strip.times[i].replace("T", " ");
      $("strip").innerHTML = strip.series.map((s) => {
        const lo = Math.max(0, i - WIN + 1);
        const vals = s.values.slice(lo, i + 1);
        const v = s.values[i];
        return `<div class="card spark-card"><div class="top"><span class="lbl">${esc(s.label)}</span><span class="badge ${badgeCls[s.status[i]] || "b-idle"}">${esc(s.badge[i])}</span></div>
          <div class="metric">${Shell.fig(v, s.unit, s.dp)}</div>${UI.spark(vals, { upto: vals.length - 1 })}
          <div class="note-line">${esc(s.note)} · ${esc(s.source.join(", "))}</div></div>`;
      }).join("");
    }
    sc.addEventListener("input", () => draw(Number(sc.value)));
    draw(n - 1);

    // ---- doors ----
    const pending = actions.filter((a) => a.status === "pending").length;
    const hitl = agents.agents.filter((a) => a.hitl_required).length;
    const rules = meta.tables.find((t) => t.name === "interlock_rules");
    $("doors").innerHTML = `
      <div class="card lift door c6 reveal"><div class="eyebrow">For the decision</div><h3>The case for change</h3>
        <p class="muted">Five short chapters: the case, the gap, the prize, the solution and the proof.</p>
        <div class="facts">
          <div><b>${num(settled.length)}</b><span>settled DR events, the worst at ${num(worst.p, 0)} % of the request</span><small>dr_events</small></div>
          <div><b>${num(k.dr.firm_kw)}</b><span>kW edge-verified today against ${num(k.dr.target_kw)} kW asked</span><small>edge interlock engine</small></div>
          <div><b>${num(proof.adk.pass_first)} / ${num(proof.adk.total)}</b><span>agent evaluation cases passed on first attempt</span><small>eval/results</small></div>
        </div><a class="btn primary" href="/case/index.html">Read the case</a></div>
      <div class="card lift door c6 reveal"><div class="eyebrow">For the shift</div><h3>The workspace</h3>
        <p class="muted">Value, the cockpit, the agent teams, your role and the shift handover.</p>
        <div class="facts">
          <div><b>${num(agents.agents.length)}</b><span>agents you can talk to, ${num(hitl)} of them propose actions that need sign-off</span><small>agent inventory</small></div>
          <div><b>${num(pending)}</b><span>actions waiting for your sign-off right now</span><small>/api/actions</small></div>
          <div><b>${num(rules ? rules.rows : null)}</b><span>interlock rules the edge checks before anything moves</span><small>interlock_rules</small></div>
        </div><a class="btn primary" href="/workspace/value.html">Open the workspace</a></div>`;

    const tables = [...new Set([...gap.source, ...strip.series.flatMap((s) => s.source)])];
    $("prov").innerHTML = Shell.provenance(UI.provRows(meta, tables));
  } catch (e) {
    $("lede1").innerHTML = `<span class="badge b-crit">Data unavailable</span> ${esc(e.message)}`;
  }
  Motion.reveal();
})();
