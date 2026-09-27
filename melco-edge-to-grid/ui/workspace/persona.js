/* Workspace · My role: the PRD personas, what each answers for, the agents they ask, and a chat side panel. */
(async function () {
  const { esc, num } = UI;
  await Shell.mountNav("workspace", "/workspace/persona.html");
  const root = document.getElementById("page");
  try {
    const [ps, ag, prompts, ov, flex, an, gs, meta] = await Promise.all([Shell.api("/api/personas"), Shell.api("/api/agents"), Shell.api("/api/suggested-prompts"),
      Shell.api("/api/overview"), Shell.api("/api/flex"), Shell.api("/api/anomalies"), Shell.api("/api/gain-share?month=2026-07"), Shell.api("/api/meta")]);
    const by = Object.fromEntries(ag.agents.map((a) => [a.agent_id, a]));
    const P = Object.fromEntries(prompts.prompts.map((p) => [p.id, p]));
    const k = ov.kpis, A = Object.fromEntries(an.anomalies.map((a) => [a.type, a]));
    let actions = await Shell.api("/api/actions");
    const KPI = {
      dr_firm: () => [Shell.fig(k.dr.firm_kw, "kW", 0), `DR firm today against ${num(k.dr.target_kw)} kW`],
      month_peak: () => [Shell.fig(k.plant_load.month_peak_kw, "kW", 0), `Month billing peak, set ${k.plant_load.month_peak_at}`],
      bess_soc: () => [Shell.fig(k.bess.soc_pct, "%", 1), `Battery now, ${k.bess.mode} under ${k.bess.policy}`],
      edge_rejected: () => [Shell.fig(flex.summary.rejected, "", 0), "Actions the edge rejected in today's plan"],
      edge_limited: () => [Shell.fig(flex.summary.limited, "", 0), "Actions the edge limited in today's plan"],
      pending_actions: () => [Shell.fig(actions.filter((a) => a.status === "pending").length, "", 0), "Actions waiting for sign-off"],
      anomalies: () => [Shell.fig(an.anomalies_found, "", 0), "Energy anomalies found this week"],
      plant_load: () => [Shell.fig(k.plant_load.value_kw, "kW", 0), `Plant load now, ${k.plant_load.ts.replace("T", " ")}`],
      july_client_net: () => [Shell.fig(gs.invoice.client_net_benefit_jpy / 1e6, "M JPY", 2), "July client net after fees"],
      july_gain_share: () => [Shell.fig(gs.invoice.vendor_gain_share_jpy / 1e6, "M JPY", 2), `July gain share at ${num(gs.invoice.gain_share_pct)} %`],
      ac04_cost: () => [Shell.fig(A.compressor_specific_power_drift ? A.compressor_specific_power_drift.impact.annual_cost_jpy / 1e6 : null, "M JPY", 1), "AC-04 excess, per year"],
    };
    root.innerHTML = `<section class="hero reveal"><div class="eyebrow">Workspace · My role</div><h1>Start from the job you answer for</h1>
      <p class="lede">Pick your role. The page shows what you are answerable for, the question that governs your shift, your figures today, and the agents that work for you.</p>
      <div class="rolepick" role="group" aria-label="Choose a role">${ps.personas.map((p, i) => `<button class="btn" aria-pressed="${i === 0}" data-role="${esc(p.id)}">${esc(p.title)}</button>`).join("")}</div></section>
      <section><div class="bento"><div class="c7" id="role"></div>
        <div class="card c5 reveal"><div class="card-cap">Ask your agents<span class="spacer"></span><span class="pill">Optimization Orchestrator</span></div>
          <div class="chatpanel"><div class="qchips" id="chips"></div><div class="thread" id="thread"></div>
          <form class="composer" id="ask"><label class="sr" for="q">Ask a question</label><textarea id="q" rows="2" placeholder="Ask about your part of today's event"></textarea><button class="btn primary" type="submit" id="go">Ask</button></form></div></div>
      </div></section>
      ${Shell.provenance(UI.provRows(meta, ["personas (docs/PRD.md section 4)", ...ov.source]))}`;
    const $ = (id) => document.getElementById(id);
    function show(p) {
      document.querySelectorAll("[data-role]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.role === p.id)));
      $("role").innerHTML = `<div class="card reveal in"><div class="eyebrow">${esc(p.local_title)}</div><h2>${esc(p.title)}</h2><p class="muted">${esc(p.one_line)}</p>
        <div class="jtbd" style="margin:14px 0"><div class="metric-sub" style="margin:0 0 6px">Your governing question</div><div class="q">${esc(p.governing_question)}</div></div>
        <div class="statline" style="margin:14px 0">${p.kpis.map((key) => { const [v, l] = KPI[key](); return `<div><div class="metric" style="font-size:24px">${v}</div><div class="metric-sub">${esc(l)}</div></div>`; }).join("")}</div>
        <div class="card-cap">What you're answerable for</div><ul class="tight">${p.answerable_for.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <div class="card-cap" style="margin-top:16px">A day in the role</div><p class="muted">${esc(p.day_in_life)}</p>
        <div class="card-cap" style="margin-top:16px">The agents you ask</div>${p.agents.map((id) => { const a = by[id]; return `<div class="agentcard"><div><span class="tag">pattern ${esc(a.pattern)}</span><b>${esc(UI.AGENT_LABEL[id] || id)}</b>
          <div class="dim" style="font-size:12.5px;margin-top:4px">${esc(a.description)}</div><div class="mono dim" style="font-size:10.5px;margin-top:4px">reads ${esc(a.reads.join(", "))}</div></div>
          ${a.hitl_required ? '<span class="badge b-warn">SIGN-OFF</span>' : '<span class="badge b-idle">advisory</span>'}</div>`; }).join("")}</div>`;
      $("chips").innerHTML = p.questions.map((q) => P[q] ? `<button class="btn" data-q="${esc(P[q].prompt)}" title="${esc(P[q].prompt)}"><b class="mono">${esc(q)}</b>&nbsp;${esc(P[q].label)}</button>` : "").join("");
      if (!$("thread").children.length) $("thread").innerHTML = `<div class="msg agent"><span class="who">Optimization Orchestrator</span>Ask about your part of today's event. Every figure comes from the plant's data, and anything I propose waits for your sign-off.</div>`;
    }
    document.querySelectorAll("[data-role]").forEach((b) => b.addEventListener("click", () => show(ps.personas.find((p) => p.id === b.dataset.role))));
    show(ps.personas[0]);
    let busy = false;
    async function ask(q) {
      if (busy || !q.trim()) return;
      busy = true; $("go").disabled = true;
      $("thread").insertAdjacentHTML("beforeend", `<div class="msg user"><span class="who">You</span>${esc(q)}</div>`);
      const out = document.createElement("div"); out.className = "msg agent"; out.innerHTML = '<span class="who">Optimization Orchestrator</span><span class="dim">Asking the specialists…</span>';
      $("thread").appendChild(out);
      const proposals = [];
      try {
        await UI.ask(q, (e, final) => {
          if (e.type === "tool_call" && by[e.tool]) out.innerHTML = `<span class="who">Optimization Orchestrator</span><span class="dim">Asking ${esc(UI.AGENT_LABEL[e.tool] || e.tool)}…</span>`;
          if (e.type === "pending_action") proposals.push(e.action);
          if (e.type === "text" && e.author === "optimization_orchestrator") out.innerHTML = `<span class="who">Optimization Orchestrator</span>${UI.md(final)}`;
          if (e.type === "error") out.innerHTML = `<span class="who">Optimization Orchestrator</span>${final ? UI.md(final) : ""}<div><span class="badge b-crit">NO ANSWER</span> <span class="dim">${esc(e.error)}</span></div>`;
        });
      } catch (err) { out.innerHTML = `<span class="badge b-crit">error</span> ${esc(err.message)}`; }
      if (proposals.length) {
        actions = await Shell.api("/api/actions");
        const box = document.createElement("div");
        box.innerHTML = proposals.map((a) => `<div class="queue-item"><div class="row"><span class="badge b-warn">needs your sign-off</span><span class="badge b-idle">${esc(a.kind.replaceAll("_", " "))}</span></div><p>${esc(a.summary)}</p>
          <button class="btn primary" data-a="${esc(a.id)}">Review and sign off</button></div>`).join("");
        out.appendChild(box);
        box.querySelectorAll("[data-a]").forEach((b) => b.addEventListener("click", () => UI.openAction(actions.find((x) => x.id === b.dataset.a) || proposals.find((x) => x.id === b.dataset.a))));
      }
      $("thread").scrollTop = $("thread").scrollHeight;
      busy = false; $("go").disabled = false;
    }
    $("chips").addEventListener("click", (ev) => { const b = ev.target.closest("[data-q]"); if (b) ask(b.dataset.q); });
    $("ask").addEventListener("submit", (ev) => { ev.preventDefault(); const v = $("q").value; $("q").value = ""; ask(v); });
  } catch (e) {
    root.innerHTML = `<div class="note crit"><strong>Data unavailable</strong><br>${esc(e.message)}</div>`;
  }
  Motion.reveal();
})();
