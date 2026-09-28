/* Screen 3: the 13:00 call, told as beats. The agent pills light from the LIVE /api/chat stream; the replay
 * (/api/alpha/replay, deterministic tools, no model call) is the badged fallback. The decide beat holds for two seconds
 * and POSTs the real /api/actions/{id}/confirm. */
window.Call = (function () {
  const A = () => window.Alpha, esc = (v) => window.Alpha.esc(v);
  const S = () => window.STORY.call;
  const LABEL = { optimization_orchestrator: "The lead", market_intelligence_agent: "Market and weather", factory_interlock_agent: "Plant floor",
    bess_strategy_agent: "Battery", asset_health_agent: "Asset health", gain_share_agent: "Gain share", safety_auditor: "The reviewer", edge: "The edge" };
  const PILL = { optimization_orchestrator: "lead", safety_auditor: "critic", edge: "edge" };
  let pane, option, beatIx = 0, cues = false, session = null;
  const run = fresh();

  function fresh() {
    return { mode: null, status: "idle", pills: {}, said: {}, edge: null, bess: null, audit: null, action: null, answer: "", error: null, calls: 0, t: 0, trace: [], confirmed: null };
  }
  function reset(mode) { Object.assign(run, fresh(), { mode, status: "running" }); }

  function onEvent(e) {
    const F = window.App;
    if (e.type === "session") { if (!e.replay) session = e.session_id; return; }
    if (e.t) run.t = e.t;
    if (e.type === "tool_call") {
      run.calls++;
      if (LABEL[e.tool]) { run.pills[e.tool] = "working"; run.pills[e.author] = "working"; run.trace.push(`${e.t}s ${LABEL[e.author] || e.author} asks ${LABEL[e.tool]}`); }
      else { run.pills[e.author] = "working"; run.trace.push(`${e.t}s ${LABEL[e.author] || e.author}: ${e.tool}`); if (e.tool === "simulate_edge_interlock") run.pills.edge = "working"; }
    } else if (e.type === "tool_result") {
      const r = e.result || {};
      if (e.tool === "simulate_edge_interlock" && r.summary) { run.edge = r; run.pills.edge = "done"; run.trace.push(`${e.t}s the edge: ${r.summary.accepted} accept, ${r.summary.limited} limit, ${r.summary.rejected} reject`); }
      else if (e.tool === "optimize_bess_schedule") { run.bess = r.kpis || (r.policies && r.policies.forecast_aware_v2 && r.policies.forecast_aware_v2.kpis) || null; }
      else if (e.tool === "audit_plan") { run.audit = r; run.trace.push(`${e.t}s the reviewer: ${r.verdict || r.status}`); }
      else if (r.status === "error") { run.trace.push(`${e.t}s ${e.tool} error: ${String(r.error || "").slice(0, 80)}`); }
    } else if (e.type === "pending_action") {
      if (!run.action || e.action.kind === "load_shed_plan") run.action = e.action;
      run.trace.push(`${e.t}s queued ${e.action.kind} for sign-off`);
    } else if (e.type === "text") {
      if (e.author === "optimization_orchestrator") run.answer += e.text;
      else if (LABEL[e.author]) { run.pills[e.author] = "done"; run.said[e.author] = e.text; }
    } else if (e.type === "error") { run.error = e.error; run.trace.push(`error: ${e.error}`); }
    else if (e.type === "done") {
      run.status = "done"; run.pills.optimization_orchestrator = run.answer ? "done" : "failed";
      Object.keys(run.pills).forEach((k) => { if (run.pills[k] === "working") run.pills[k] = run.said[k] ? "done" : "idle"; });
      F.onRunFinished && F.onRunFinished(run);
    }
    renderStage(); renderRunBar();
  }

  async function readSSE(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok || !r.body) throw new Error(`${url}: HTTP ${r.status}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) { try { onEvent(JSON.parse(line.slice(6))); } catch (err) { /* malformed chunk */ } }
      }
    }
  }

  async function start(mode) {
    if (run.status === "running") return;
    reset(mode);
    run.pills.optimization_orchestrator = "working";
    renderStage(); renderRunBar();
    try {
      if (mode === "live") await A().stream("/api/chat", window.App.promptText(S().prompt_id), onEvent, session);
      else await readSSE("/api/alpha/replay");
    } catch (err) { run.error = err.message; }
    if (run.status !== "done") onEvent({ type: "done", t: run.t });
  }

  /* ---- rendering ---- */
  function beats() { return option.beats.map((k) => ({ key: k, ...S().beats[k] })); }
  function lit(key) {
    const need = { lead: ["optimization_orchestrator"], flex: ["factory_interlock_agent"], edge: ["edge"], battery: ["bess_strategy_agent"], review: ["safety_auditor"], decide: [] };
    if (key === "decide") return !!run.action;
    return (need[key] || []).some((a) => run.pills[a] === "done");
  }

  function pills(agents) {
    if (!agents.length) return "";
    return `<div class="mo-pills">${agents.map((a) => { const st = run.pills[a] || "idle";
      return `<span class="mo-pill ${PILL[a] || ""} ${st === "working" ? "working" : st === "done" ? "done" : ""}" title="${esc(st)}"><span class="st"></span>${esc(LABEL[a] || a)}${run.mode && st !== "idle" ? `<span class="rb">${run.mode === "replay" ? "REPLAY" : "LIVE"}</span>` : ""}</span>`; }).join("")}</div>`;
  }

  function said(key) {
    const map = { lead: "market_intelligence_agent", flex: "factory_interlock_agent", battery: "bess_strategy_agent", review: "safety_auditor" };
    if (key === "edge" && run.edge) {
      const s = run.edge.summary, rej = (run.edge.rejected_actions || []).map((x) => `${x.asset_id} ${x.action} (${x.rule_ids.join(", ")}): ${x.reason}`).join(" ");
      return `<div class="mo-said edge"><b>The edge, ${run.mode === "replay" ? "replayed" : "live"}</b>${esc(`${s.actions_evaluated} actions: ${s.accepted} accepted, ${s.limited} limited, ${s.rejected} rejected; firm ${Number(s.firm_reduction_kw).toLocaleString("en-US", { maximumFractionDigits: 0 })} kW in ${s.total_decision_ms} ms. ${rej}`)}</div>`;
    }
    const a = map[key];
    if (a && run.said[a]) return `<div class="mo-said"><b>${esc(LABEL[a])}, in its own words (${run.mode === "replay" ? "replay" : "live"})</b>${esc(run.said[a].slice(0, 420))}${run.said[a].length > 420 ? "…" : ""}</div>`;
    return "";
  }

  function findings(list) {
    if (!list || !list.length) return "";
    return `<div class="mo-findings">${list.map(([k, l]) => `<div class="mo-finding"><div class="fv ${k === "edge_rejected" ? "crit" : k === "dr_firm" || k === "edge_accepted" ? "ok" : ""}">${window.F[k] || '<span class="gap-value">NOT IN THE DATA</span>'}</div><div class="fl">${esc(l)}</div></div>`).join("")}</div>`;
  }

  function techDrawer(b) {
    const rows = run.trace.length ? run.trace.map((t) => `<div>${esc(t)}</div>`).join("") : '<div class="dim">No run yet. Press Run the agents live, or Play the replay.</div>';
    return `<details class="drawer"><summary>How this was produced<span class="hint">${run.mode ? (run.mode === "replay" ? "replay: deterministic tools, no model call" : "live run") : "not run yet"}</span></summary><div class="body">
      <div class="terminal ask-trace">${rows}</div>
      <div class="kv-card" style="margin-top:10px"><div class="kv-row"><span class="kv-key">Prompt</span><span class="kv-val" style="text-align:left;font-weight:500">${esc(window.App.promptText(S().prompt_id))}</span></div>
      <div class="kv-row"><span class="kv-key">Events</span><span class="kv-val">${run.calls} tool calls · ${run.t} s</span></div>
      <div class="kv-row"><span class="kv-key">Figures on this beat</span><span class="kv-val">/api/overview · /api/flex · /api/bess · /api/jepx · /api/pv · /api/dr-events</span></div></div></div></details>`;
  }

  function stageDefault(b) {
    return `<div class="mo-kicker">${esc(b.kicker)}</div><div class="mo-clock">${esc(b.clock)}</div><h2>${window.App.tpl(b.title)}</h2>
      ${b.lines.map((l, i) => `<p class="${i === 0 ? "first" : ""}">${window.App.tpl(l)}</p>`).join("")}
      ${pills(b.agents)}${said(b.key)}${findings(b.findings)}
      ${cues && b.cue ? `<div class="cue">${esc(b.cue)}</div>` : ""}${techDrawer(b)}`;
  }

  function stageContrast(b) {
    const C = S().contrast_rows;
    return `<div class="mo-kicker">${esc(b.kicker)}</div><h2>${window.App.tpl(b.title)}</h2>
      <div class="mo-contrast"><div class="mo-col today"><h4>As it went last time <span class="badge badge-critical">22 July</span></h4>${C.today.map((r) => `<div class="mo-row hit"><span class="mo-clock">${esc(r.clock)}</span><span>${window.App.tpl(r.text)}</span></div>`).join("")}</div>
      <div class="mo-col"><h4>Today, with the agents <span class="badge badge-optimal">19 August</span></h4>${C.agents.map((r) => `<div class="mo-row win"><span class="mo-clock">${esc(r.clock)}</span><span>${window.App.tpl(r.text)}</span></div>`).join("")}</div></div>
      ${cues && b.cue ? `<div class="cue">${esc(b.cue)}</div>` : ""}${techDrawer(b)}`;
  }

  function stageOptions(b) {
    const D = window.D, rej = (run.edge && run.edge.rejected_actions && run.edge.rejected_actions[0]) || (D.flex.rows.find((r) => r.edge_verdict === "REJECT") && { asset_id: "FN-02", rule_ids: D.flex.rows.find((r) => r.edge_verdict === "REJECT").rule_ids, reason: D.flex.rows.find((r) => r.edge_verdict === "REJECT").edge_reason });
    return `<div class="mo-kicker">${esc(b.kicker)}</div><div class="mo-clock">${esc(b.clock)}</div><h2>${window.App.tpl(b.title)}</h2>${b.lines.map((l) => `<p class="first">${window.App.tpl(l)}</p>`).join("")}
      <div class="mo-opts">${S().options_cards.map((o) => `<div class="mo-option ${o.kind === "struck" ? "crit struck" : o.kind}" ${o.struck ? `data-struck="${esc(o.struck)}"` : ""}>${o.rec ? `<span class="rec">${esc(o.rec)}</span>` : ""}<div class="mo-option-id">Option ${esc(o.id)}</div><h4>${esc(o.name)}</h4>
        <dl>${o.rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${window.App.tpl(v)}</dd>`).join("")}</dl>
        ${o.kind === "struck" && rej ? `<div class="struck-why"><b>${esc(rej.asset_id)} ${esc((rej.rule_ids || []).join(", "))}:</b> ${esc(rej.reason)}</div>` : ""}</div>`).join("")}</div>
      ${cues && b.cue ? `<div class="cue">${esc(b.cue)}</div>` : ""}${techDrawer(b)}`;
  }

  function stageDecide(b) {
    const a = run.action;
    let body;
    if (!a) {
      body = `<div class="mo-decide"><div class="mo-box unsettled"><div class="lab">What it could not settle</div><p>No plan is waiting yet. The agents have to run first; their plan, its rejected actions and its sources then appear here.</p></div>
        <div class="mo-box"><div class="lab">Start the run</div><p style="margin-bottom:10px">Live uses the real agents on this server. The replay uses the same deterministic tools with no model call and is badged as such.</p>
        <div class="ask-actions"><button class="btn btn-primary" id="dec-live" ${run.status === "running" ? "disabled" : ""}>Run the agents live</button><button class="btn" id="dec-replay" ${run.status === "running" ? "disabled" : ""}>Play the replay</button></div></div></div>`;
    } else {
      const un = a.unverified && a.unverified.length ? a.unverified : ["Nothing flagged by the agents."];
      body = `<div class="mo-decide"><div class="mo-box unsettled"><div class="lab">What it could not settle</div><ul style="padding-left:16px;font-size:12.5px;margin:0">${un.map((u) => `<li>${esc(u)}</li>`).join("")}</ul></div>
        <div class="mo-box"><div class="lab">The agents' case <span class="badge ${run.mode === "replay" ? "badge-replay" : "badge-live"}" style="margin-left:6px">${run.mode === "replay" ? "replay" : "live"}</span></div><p><b>${esc(a.summary)}</b></p><p style="margin-top:6px">${esc(a.reasoning || "")}</p>
        <div class="chip-row" style="margin-top:8px">${(a.sources || []).map((s) => `<span class="chip">${esc(s.replace(/^.*\./, ""))}</span>`).join("")}</div>
        ${a.audit ? `<p style="margin-top:8px;font-size:12px">Reviewer: <b>${esc(a.audit)}</b></p>` : ""}</div></div>
        <div class="ask-actions" style="margin-top:6px"><button class="mo-hold" id="dec-hold" ${run.confirmed || a.status !== "pending" ? "disabled" : ""}><span class="lbl">${run.confirmed || a.status !== "pending" ? "Approved" : "Hold 2 s to approve"}</span></button>
        <button class="btn" id="dec-reject" ${run.confirmed || a.status !== "pending" ? "disabled" : ""}>Reject</button></div>
        <div class="mo-released ${run.confirmed ? "on" : ""}" id="dec-released">${run.confirmed ? releasedText(run.confirmed) : ""}</div>`;
    }
    return `<div class="mo-kicker">${esc(b.kicker)}</div><div class="mo-clock">${esc(b.clock)}</div><h2>${window.App.tpl(b.title)}</h2>${b.lines.map((l, i) => `<p class="${i === 0 ? "first" : ""}">${window.App.tpl(l)}</p>`).join("")}${body}
      ${cues && b.cue ? `<div class="cue">${esc(b.cue)}</div>` : ""}${techDrawer(b)}`;
  }

  function releasedText(r) {
    const rc = r.audit_record && r.audit_record.edge_recheck;
    return `<div class="lab">What the server did</div>Status <b>${esc(r.status)}</b>${rc ? `; the edge re-checked plan ${esc(rc.plan_id)} at dispatch: ${esc(rc.rejected)} rejected, firm ${Number(rc.firm_kw || 0).toLocaleString("en-US", { maximumFractionDigits: 0 })} kW` : ""}. One audit record written${r.audit_record ? ` (${esc(r.audit_record.decision)} by ${esc(r.audit_record.by)})` : ""}. Nothing reached a real controller.`;
  }

  function stageMap(b) {
    return `<div class="mo-kicker">${esc(b.kicker)}</div><h2>${window.App.tpl(b.title)}</h2>${b.lines.map((l) => `<p class="first">${window.App.tpl(l)}</p>`).join("")}
      <div class="mo-map">${S().map_tiles.map((t) => `<div class="mo-node ${t.cls}"><div class="t">${esc(t.t)}</div><div class="v">${window.F[t.fig] || '<span class="gap-value">NOT IN THE DATA</span>'}</div></div>`).join("")}</div>
      ${run.answer ? `<div class="mo-box" style="margin-top:12px"><div class="lab">The lead's answer <span class="badge ${run.mode === "replay" ? "badge-replay" : "badge-live"}">${run.mode === "replay" ? "replay" : "live"}</span></div><div class="mo-answer">${window.App.md(run.answer)}</div></div>` : ""}
      ${cues && b.cue ? `<div class="cue">${esc(b.cue)}</div>` : ""}${techDrawer(b)}`;
  }

  function renderStage() {
    const st = pane.querySelector("#mo-stage"); if (!st) return;
    const list = beats(); if (beatIx >= list.length) beatIx = list.length - 1;
    const b = list[beatIx];
    st.className = `mo-stage${b.key === "edge" || b.key === "decide" ? " turn" : ""}`;
    st.innerHTML = (b.key === "contrast" ? stageContrast(b) : b.key === "options" ? stageOptions(b) : b.key === "decide" ? stageDecide(b) : b.key === "map" ? stageMap(b) : stageDefault(b))
      + `<div class="mo-nav"><button class="btn" id="mo-prev" ${beatIx === 0 ? "disabled" : ""}>Previous</button><span class="mo-clock" style="align-self:center">${beatIx + 1} of ${list.length}</span><button class="btn btn-primary" id="mo-next" ${beatIx === list.length - 1 ? "disabled" : ""}>Next</button></div>`;
    st.querySelector("#mo-prev").onclick = () => go(beatIx - 1);
    st.querySelector("#mo-next").onclick = () => go(beatIx + 1);
    const live = st.querySelector("#dec-live"), rep = st.querySelector("#dec-replay");
    if (live) live.onclick = () => start("live");
    if (rep) rep.onclick = () => start("replay");
    const hold = st.querySelector("#dec-hold");
    if (hold && !hold.disabled) A().hold(hold, async () => {
      try {
        const r = await A().api(`/api/actions/${run.action.id}/confirm`, { method: "POST" });
        const audit = await A().api("/api/audit");
        r.audit_record = audit.find((x) => x.action_id === run.action.id) || null;
        run.confirmed = r; run.action.status = r.status;
        const rel = st.querySelector("#dec-released"); if (rel) { rel.innerHTML = releasedText(r); rel.classList.add("on"); }
        A().toast("Approved and re-checked at the edge");
      } catch (err) { A().toast(`Confirm failed: ${err.message}`); }
    });
    const rej = st.querySelector("#dec-reject");
    if (rej && !rej.disabled) rej.onclick = async () => {
      try { const r = await A().api(`/api/actions/${run.action.id}/reject`, { method: "POST" }); run.action.status = r.status; A().toast("Rejected; one audit record written"); renderStage(); }
      catch (err) { A().toast(`Reject failed: ${err.message}`); }
    };
    renderBeats();
  }

  function renderBeats() {
    const nav = pane.querySelector("#mo-beats"); if (!nav) return;
    nav.innerHTML = beats().map((b, i) => `<button type="button" class="mo-beat ${i === beatIx ? "active" : ""} ${lit(b.key) ? "lit" : ""}" data-i="${i}"><span class="mo-beat-clock">${esc(b.clock || "·")}</span><span class="mo-beat-name">${esc(b.kicker.replace(/^\d+ · /, ""))}<span class="st"></span></span></button>`).join("");
    nav.querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => go(Number(b.dataset.i))));
  }

  function renderRunBar() {
    const bar = pane.querySelector("#run-bar"); if (!bar) return;
    const badge = run.mode === "replay" ? `<span class="badge badge-replay"><span class="dot"></span>replay</span>` : run.mode === "live" ? `<span class="badge badge-live ${run.status === "running" ? "on" : ""}"><span class="dot"></span>live</span>` : `<span class="badge badge-stable">not run yet</span>`;
    let text = "The agent pills light as the real stream reaches them.";
    if (run.status === "running") text = `${run.mode === "replay" ? "Replaying the deterministic tools" : "The agents are working"}: ${run.calls} tool calls, ${run.t} s.`;
    else if (run.status === "done" && run.error && !run.answer) text = `The model did not answer: ${run.error}. Play the replay instead.`;
    else if (run.status === "done") text = `${run.mode === "replay" ? "Replay" : "Live run"} finished: ${run.calls} tool calls in ${run.t} s${run.action ? "; a plan waits for sign-off" : ""}.`;
    bar.innerHTML = `${badge}<span>${esc(text)}</span><span class="spacer"></span>
      <button class="btn btn-primary" id="rb-live" ${run.status === "running" ? "disabled" : ""}>Run the agents live</button>
      <button class="btn" id="rb-replay" ${run.status === "running" ? "disabled" : ""}>Play the replay</button>`;
    bar.querySelector("#rb-live").onclick = () => start("live");
    bar.querySelector("#rb-replay").onclick = () => start("replay");
  }

  function go(i) { beatIx = Math.max(0, Math.min(beats().length - 1, i)); renderStage(); }

  function render(el) {
    pane = el; option = S().options[0];
    pane.innerHTML = `<div class="eyebrow">${esc(S().eyebrow)}</div><h1 class="hero-title" style="margin-bottom:8px">${esc(S().hero)}</h1><p class="hero-desc" style="margin-bottom:14px">${esc(S().lede)}</p>
      <div class="mo-options" id="mo-options" role="tablist"></div>
      <div class="run-bar" id="run-bar"></div>
      <div class="mo-toolbar"><label class="mo-toggle"><input type="checkbox" id="mo-cues"> Presenter cues</label><span id="mo-count"></span></div>
      <div class="mo-layout"><nav class="mo-beats" id="mo-beats" aria-label="Beats"></nav><div class="mo-stage" id="mo-stage" aria-live="polite"></div></div>
      ${window.App.techDrawer("Technical detail", [["Live stream", "POST /api/chat, server-sent events: session, tool_call, tool_result, pending_action, text, final, done"], ["Replay", "GET /api/alpha/replay: the same event shapes from the deterministic tools; every event carries replay: true"], ["Sign-off", "POST /api/actions/{id}/confirm after a 2 s hold; the edge re-checks at dispatch and one audit row is written"], ["Figures", "Every finding on every beat comes from /api; the story text carries no number of its own"]])}
      <div class="disclaimer">${esc(window.STORY.disclaimer)}</div>`;
    const opts = pane.querySelector("#mo-options");
    opts.innerHTML = S().options.map((o, i) => `<button type="button" class="mo-opt ${i === 0 ? "active" : ""}" data-o="${esc(o.id)}" role="tab">${esc(o.name)}<small>${esc(o.blurb)}</small></button>`).join("");
    opts.querySelectorAll("[data-o]").forEach((b) => b.addEventListener("click", () => { option = S().options.find((o) => o.id === b.dataset.o); opts.querySelectorAll(".mo-opt").forEach((x) => x.classList.toggle("active", x === b)); beatIx = 0; pane.querySelector("#mo-count").textContent = `${option.beats.length} beats`; renderStage(); }));
    pane.querySelector("#mo-cues").addEventListener("change", (e) => { cues = e.target.checked; renderStage(); });
    pane.querySelector("#mo-count").textContent = `${option.beats.length} beats`;
    renderRunBar(); renderStage();
  }

  return { render, start, go, run };
})();
