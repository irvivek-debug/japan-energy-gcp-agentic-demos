/* Workspace · Agent teams: who is on the team, and how a question moves through it, lit live from the SSE trace.
 * 1 The lead -> 2 Specialists -> 3 The reviewer -> 4 The edge (deterministic, not an LLM) -> 5 Your sign-off. */
(async function () {
  const { esc, num } = UI;
  await Shell.mountNav("workspace", "/workspace/swarm.html");
  const root = document.getElementById("page");
  try {
    const [ag, prompts, proof, meta] = await Promise.all([Shell.api("/api/agents"), Shell.api("/api/suggested-prompts"), Shell.api("/api/proof"), Shell.api("/api/meta")]);
    const by = Object.fromEntries(ag.agents.map((a) => [a.agent_id, a]));
    const specs = ag.agents.filter((a) => a.role === "Specialist");
    const label = (id) => UI.AGENT_LABEL[id] || id;
    const node = (id, extra = "") => `<div class="flow-node ${extra}" id="n-${esc(id)}"><span class="state badge b-idle">idle</span><div class="who">${esc(label(id))}</div>
      <div class="what">${esc((by[id] || {}).description || "")}</div><div class="tools" id="t-${esc(id)}"></div></div>`;
    const lat = proof.adk.latency_s;
    root.innerHTML = `<section class="hero reveal"><div class="eyebrow">Workspace · Agent teams</div><h1>Ask the team, and watch the question move</h1>
      <p class="lede">${num(ag.agents.length)} agents: one lead, ${num(specs.length)} specialists and a reviewer. ${num(ag.agents.filter((a) => a.hitl_required).length)} of them can only propose actions that wait for your sign-off. The edge interlock engine is not an agent; it decides whether each action is allowed.</p></section>
      <section><div class="bento">
        <div class="card c4 reveal teamlist"><div class="card-cap">The team</div>${ag.agents.map((a) => `<div class="agent"><div class="row"><b>${esc(label(a.agent_id))}</b>
          ${a.hitl_required ? '<span class="badge b-warn">SIGN-OFF</span>' : '<span class="badge b-idle">advisory</span>'}</div>
          <div class="id">${esc(a.agent_id)} · pattern ${esc(a.pattern)} · ${esc(a.tier)} model</div><div class="desc">reads ${esc(a.reads.join(", "))}</div></div>`).join("")}</div>
        <div class="card c8 reveal"><div class="card-cap">How the question moves<span class="spacer"></span><span class="pill" id="runstate">waiting for a question</span></div>
          <div class="flow-step">1 · The lead</div>${node("optimization_orchestrator")}
          <div class="flow-arrow">asks the specialists, in parallel</div><div class="flow-step">2 · Specialists, working together</div><div class="flow-row">${specs.map((a) => node(a.agent_id)).join("")}</div>
          <div class="flow-arrow">sends the plan for review</div><div class="flow-step">3 · The reviewer</div>${node("safety_auditor")}
          <div class="flow-arrow">every action is checked where the plant runs</div><div class="flow-step">The edge · between review and sign-off</div>
          <div class="flow-node edge" id="n-edge"><span class="state badge b-idle">idle</span><div class="who">Edge interlock engine</div><div class="what">Deterministic rules on live PLC state; accepts, limits or rejects each action with a rule id.</div><div class="tools" id="t-edge"></div></div>
          <div class="flow-arrow">nothing moves until</div><div class="flow-step">4 · Your sign-off</div>
          <div class="flow-node signoff" id="n-signoff"><span class="state badge b-idle">idle</span><div class="who">You</div><div class="what">A ${num(SignOff.HOLD_MS / 1000)}-second hold approves; the edge re-checks at dispatch and one audit record is written.</div><div id="t-signoff"></div></div>
        </div>
        <div class="card c12 reveal"><div class="card-cap">Run a scenario</div><div class="runner" id="runner">${prompts.prompts.map((p) => `<button class="btn" data-p="${esc(p.prompt)}" title="${esc(p.prompt)}"><b class="mono">${esc(p.id)}</b>&nbsp;${esc(p.label)}</button>`).join("")}</div>
          <form class="composer" id="ask"><label class="sr" for="q">Ask the team</label><textarea id="q" rows="2" placeholder="Or ask your own question about today's event, the battery, prices or anomalies"></textarea><button class="btn primary" type="submit" id="go">Ask</button></form></div>
        <div class="card c7 reveal"><div class="card-cap">Trace<span class="spacer"></span><span class="mono dim" id="tstat"></span></div><div class="console" id="trace" aria-live="off"><span class="dim">The trace of agents, tool calls and results appears here.</span></div></div>
        <div class="card c5 reveal"><div class="card-cap">The lead's answer</div><div id="answer" class="msg agent"><span class="dim">No question asked yet in this session.</span></div></div>
        <div class="card c12 reveal"><div class="card-cap">What stands between this team and a run</div><ul class="limits">
          <li>Full plans take ${lat ? `${num(lat[0], 0)} to ${num(lat[1], 0)}` : "NOT IN THE DATA"} seconds in evaluation: a reasoning model leads and several specialists run.</li>
          <li>The edge here is a deterministic simulator of the plant's interlocks, not a controller; nothing reaches real equipment.</li>
          <li>The approval queue and audit log live in this server's memory for the demo; production keeps them in a durable store.</li>
          <li>The final evaluation ran each case once; earlier runs had failures that are recorded on the proof chapter.</li>
          <li>Market, weather and plant data are synthetic; the aggregator, JEPX and OCCTO connections are not live.</li></ul></div>
      </div></section>
      ${Shell.provenance(UI.provRows(meta, ["agent inventory", "/api/chat (live trace)"]))}`;

    const $ = (id) => document.getElementById(id);
    const setState = (id, cls, text) => { const n = $(`n-${id}`); if (!n) return; n.classList.remove("active", "done"); if (cls) n.classList.add(cls);
      const b = n.querySelector(".state"); b.className = `state badge ${cls === "active" ? "b-info" : cls === "done" ? "b-ok" : "b-idle"}`; b.textContent = text; };
    const addTool = (id, t) => { const el = $(`t-${id}`); if (el && !el.textContent.includes(t)) el.textContent += (el.textContent ? " · " : "") + t; };
    const line = (t, who, html, cls = "") => { const tr = $("trace"); if (tr.querySelector(".dim") && tr.children.length === 1) tr.innerHTML = "";
      tr.insertAdjacentHTML("beforeend", `<div class="${cls}"><span class="dim">${num(t, 1)}s</span> <b>${esc(label(who))}</b> ${html}</div>`); tr.scrollTop = tr.scrollHeight; };
    let busy = false;
    async function run(q) {
      if (busy || !q.trim()) return;
      busy = true; $("go").disabled = true;
      ["optimization_orchestrator", ...specs.map((a) => a.agent_id), "safety_auditor"].forEach((id) => { setState(id, "", "idle"); $(`t-${id}`).textContent = ""; });
      setState("edge", "", "idle"); $("t-edge").textContent = ""; setState("signoff", "", "idle"); $("t-signoff").innerHTML = "";
      $("trace").innerHTML = ""; $("answer").innerHTML = '<span class="dim">Working…</span>'; $("runstate").textContent = "running";
      setState("optimization_orchestrator", "active", "working");
      let calls = 0, failed = null;
      try {
        await UI.ask(q, (e, final) => {
          if (e.type === "tool_call") {
            calls++;
            if (by[e.tool]) { setState(e.tool, "active", "asked"); line(e.t, e.author, `asks <b>${esc(label(e.tool))}</b>`); }
            else { setState(e.author, "active", "working"); addTool(e.author, e.tool); line(e.t, e.author, `→ ${esc(e.tool)}(${esc(JSON.stringify(e.args).slice(0, 140))})`); }
            if (e.tool === "simulate_edge_interlock") setState("edge", "active", "checking");
          } else if (e.type === "tool_result") {
            const r = e.result || {};
            if (e.tool === "simulate_edge_interlock" && r.summary) {
              setState("edge", "done", "decided");
              $("t-edge").textContent = `${r.plan_id}: ${r.summary.accepted} accepted, ${r.summary.limited} limited, ${r.summary.rejected} rejected; firm ${num(r.summary.firm_reduction_kw)} kW` +
                ((r.rejected_actions || []).length ? ` · REJECT ${r.rejected_actions.map((x) => `${x.asset_id} (${x.rule_ids.join(", ")})`).join("; ")}` : "");
              line(e.t, "edge", `edge verdicts: ${r.summary.accepted} accept, ${r.summary.limited} limit, ${r.summary.rejected} reject`, r.summary.rejected ? "warn" : "ok");
            } else if (e.tool === "audit_plan") {
              line(e.t, e.author, `audit verdict <b>${esc(r.verdict || r.status)}</b>`, r.verdict === "APPROVED" ? "ok" : "warn");
            } else if (!by[e.tool]) {
              line(e.t, e.author, `← ${esc(e.tool)}: ${esc(r.status || "")}${r.error ? ` <span class="crit">${esc(String(r.error).slice(0, 100))}</span>` : ""}`, r.status === "error" ? "crit" : "dim");
            }
          } else if (e.type === "pending_action") {
            setState("signoff", "active", "needs you");
            const a = e.action;
            $("t-signoff").insertAdjacentHTML("beforeend", `<div class="queue-item" style="margin-top:8px"><div class="row"><span class="badge b-warn">pending</span><span class="badge b-idle">${esc(a.kind.replaceAll("_", " "))}</span></div>
              <p>${esc(a.summary)}</p><button class="btn primary" data-a="${esc(a.id)}">Review and sign off</button></div>`);
            $("t-signoff").querySelector(`[data-a="${a.id}"]`).addEventListener("click", async () => { const list = await Shell.api("/api/actions"); UI.openAction(list.find((x) => x.id === a.id) || a); });
            line(e.t, e.author, `queued <b>${esc(a.kind)}</b> for your sign-off`, "warn");
          } else if (e.type === "text") {
            if (e.author === "optimization_orchestrator") $("answer").innerHTML = `<span class="who">Optimization Orchestrator</span>${UI.md(final)}`;
            else if (by[e.author]) { setState(e.author, "done", "done"); line(e.t, e.author, `<span class="dim">${esc(e.text.slice(0, 160))}…</span>`); }
          } else if (e.type === "error") {
            failed = e.error; line(e.t || 0, "server", `<span class="crit">${esc(e.error)}</span>`, "crit");
            if (!final) $("answer").innerHTML = `<span class="badge b-crit">NO ANSWER</span> <span class="dim">${esc(e.error)}</span>`;
          } else if (e.type === "done") {
            setState("optimization_orchestrator", final ? "done" : "", final ? "answered" : "no answer");
            $("tstat").textContent = `${calls} calls · ${num(e.t, 1)} s`; $("runstate").textContent = failed && !final ? "ended without an answer" : "done";
          }
        });
      } catch (err) { $("answer").innerHTML = `<span class="badge b-crit">error</span> ${esc(err.message)}`; }
      busy = false; $("go").disabled = false;
    }
    document.getElementById("runner").addEventListener("click", (ev) => { const b = ev.target.closest("[data-p]"); if (b) { $("q").value = b.dataset.p; run(b.dataset.p); } });
    document.getElementById("ask").addEventListener("submit", (ev) => { ev.preventDefault(); run($("q").value); });
  } catch (e) {
    root.innerHTML = `<div class="note crit"><strong>Data unavailable</strong><br>${esc(e.message)}</div>`;
  }
  Motion.reveal();
})();
