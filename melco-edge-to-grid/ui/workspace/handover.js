/* Workspace · Handover: a brief the agents write on request for the next shift. Each section starts honestly empty;
 * "Write this brief now" runs the lead, and each team's own words fill its section with what it read. */
(async function () {
  const { esc, num } = UI;
  await Shell.mountNav("workspace", "/workspace/handover.html");
  const root = document.getElementById("page");
  const TEAMS = [
    ["market_intelligence_agent", "Market and weather"], ["factory_interlock_agent", "Plant and edge interlocks"], ["bess_strategy_agent", "Battery"],
    ["asset_health_agent", "Asset health"], ["gain_share_agent", "Gain share"], ["safety_auditor", "Safety review"], ["optimization_orchestrator", "Summary from the lead"],
  ];
  const PROMPT = "Write the shift handover brief for the incoming afternoon shift. Cover today's DR event and the edge-verified load-shed plan with any rejected actions, "
    + "the market and PV risks this evening, the battery plan, the energy anomalies and the work orders worth raising, this month's gain-share position, "
    + "and a safety review that includes anything flagged in today's shift handover note. Keep each part short and factual.";
  try {
    const [ov, meta, actions] = await Promise.all([Shell.api("/api/overview"), Shell.api("/api/meta"), Shell.api("/api/actions")]);
    const k = ov.kpis;
    root.innerHTML = `<section class="hero read reveal"><div class="eyebrow">Workspace · Shift handover</div><h1>Shift handover brief</h1>
      <p class="lede">What the next shift needs to know, written by the agents on request, one section per team, each in its own words with what it read. Nothing here is written until you ask, and a section no agent writes says so.</p>
      <div class="btn-row noprint"><button class="btn primary" id="write">Write this brief now</button><button class="btn" id="print">Print this brief</button><a class="btn" href="/workspace/swarm.html">See the agent team that writes it</a></div></section>
      <section><div class="card reveal"><div class="card-cap">Shift window</div><dl class="kv">
        <dt>Demo clock</dt><dd>${esc(ov.demo_now.replace("T", " "))} JST</dd>
        <dt>DR event</dt><dd>${esc(k.dr.event_id)}: ${num(k.dr.target_kw)} kW, ${esc(k.dr.window)}; edge-verified firm ${num(k.dr.firm_kw)} kW</dd>
        <dt>JEPX spike</dt><dd>${esc(k.jepx.spike_window)}, peak ${num(k.jepx.spike_peak, 1)} JPY/kWh</dd>
        <dt>Waiting for sign-off</dt><dd id="pend">${num(actions.filter((a) => a.status === "pending").length)}</dd>
        <dt>Brief status</dt><dd id="bstat"><span class="badge b-idle">NOT YET WRITTEN</span></dd></dl></div></section>
      <section id="secs">${TEAMS.map(([id, title], i) => `<div class="hsec empty reveal" id="s-${id}"><div class="card-cap">${num(i + 1)} · ${esc(title)}<span class="spacer"></span>
        <span class="badge b-idle state">NOT YET WRITTEN</span></div><div class="body">No agent has written this section in this session.</div><div class="mono dim read-by" style="font-size:10.5px;margin-top:8px"></div></div>`).join("")}</section>
      ${Shell.provenance(UI.provRows(meta, ["/api/chat (the brief is written live)", ...ov.source]))}`;
    const $ = (id) => document.getElementById(id);
    const reads = {};
    $("print").addEventListener("click", () => window.print());
    let busy = false;
    $("write").addEventListener("click", async () => {
      if (busy) return;
      busy = true; $("write").disabled = true;
      $("bstat").innerHTML = '<span class="badge b-info">WRITING</span> the lead is asking the teams';
      TEAMS.forEach(([id]) => { const s = $(`s-${id}`); s.querySelector(".state").className = "badge b-idle state"; s.querySelector(".state").textContent = "NOT YET WRITTEN"; reads[id] = new Set(); });
      const stamp = () => new Date().toTimeString().slice(0, 5);
      const fill = (id, text) => {
        const s = $(`s-${id}`); if (!s) return;
        s.classList.remove("empty");
        s.querySelector(".body").innerHTML = UI.md(text);
        const b = s.querySelector(".state"); b.className = "badge b-ok state"; b.textContent = `WRITTEN ${stamp()}`;
        s.querySelector(".read-by").textContent = reads[id] && reads[id].size ? `what it read: ${[...reads[id]].join(", ")}` : "";
      };
      let failed = null;
      try {
        await UI.ask(PROMPT, (e, final) => {
          if (e.type === "tool_call" && reads[e.author]) reads[e.author].add(e.tool);
          if (e.type === "tool_result" && e.result && e.result.source && reads[e.author]) [].concat(e.result.source).forEach((x) => reads[e.author].add(x));
          if (e.type === "text" && e.author !== "optimization_orchestrator" && reads[e.author]) fill(e.author, e.text);
          if (e.type === "text" && e.author === "optimization_orchestrator") fill("optimization_orchestrator", final);
          if (e.type === "pending_action") $("pend").textContent = String(Number($("pend").textContent || 0) + 1);
          if (e.type === "error") failed = e.error;
        });
        if (failed) throw new Error(failed);
        TEAMS.forEach(([id]) => { const s = $(`s-${id}`); if (s.classList.contains("empty")) { s.querySelector(".body").textContent = "Not written this time: the lead did not consult this team for the brief."; s.querySelector(".state").textContent = "NOT WRITTEN"; } });
        $("bstat").innerHTML = `<span class="badge b-ok">WRITTEN</span> ${stamp()}; proposals raised while writing wait in the cockpit for sign-off`;
      } catch (err) {
        $("bstat").innerHTML = `<span class="badge b-crit">NOT WRITTEN</span> ${esc(err.message)}`;
      }
      busy = false; $("write").disabled = false;
    });
  } catch (e) {
    root.innerHTML = `<div class="note crit"><strong>Data unavailable</strong><br>${esc(e.message)}</div>`;
  }
  Motion.reveal();
})();
