/* Agent teams: the team on the left, "How the question moves" on the right. Each flow node lights as the live SSE
 * trace reaches it: the lead while it routes, a specialist while it works, the reviewer while it checks, and your
 * sign-off when a proposal arrives. Approvals open the sign-off sheet, never an inline button. */
(async function () {
  const D = window.Desk, { esc, el } = D, LEAD = window.Runner.LEAD;
  Shell.mountNav("workspace", "swarm");
  const main = el("page");
  let ag, sc, actions;
  try {
    [ag, sc, actions] = await Promise.all([Shell.api("/api/agents"), Shell.api("/api/scenarios"), Shell.api("/api/actions")]);
  } catch (e) { D.fail(main, e); return; }
  const A = ag.agents, lead = A.find((a) => a.step === 1), specs = A.filter((a) => a.step === 2), rev = A.find((a) => a.step === 3);
  const pendingN = () => actions.filter((a) => a.status === "pending").length;

  const item = (a) => `<div class="item"><span class="code">${esc(a.code)}</span><div style="min-width:0">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>${esc(a.title)}</b>${a.sign_off ? '<span class="badge b-warn">sign-off</span>' : ""}<span class="badge b-idle">pattern ${esc(a.pattern)}</span></div>
      <div class="dim mono" style="margin-top:3px">${esc(a.name)} · ${esc(a.tier)} tier · ${a.tool_count} tools</div>
      <details class="drawer" style="margin-top:8px"><summary>What it does<span class="hint">reads ${a.reads.length} sources</span></summary><div class="body">
        <p style="margin:0 0 8px">${esc(a.role)}</p><dl class="kv"><dt>Reads</dt><dd>${esc(a.reads.join(", "))}</dd><dt>Tools</dt><dd class="mono">${esc(a.tools.join(", "))}</dd>
        ${a.proposes.length ? `<dt>Proposes</dt><dd class="mono">${esc(a.proposes.join(", "))}</dd>` : ""}</dl></div></details></div></div>`;
  const node = (a, id) => `<div class="flow-node" id="n-${id}"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span class="mono" style="color:var(--accent)">${esc(a.code)}</span><span class="who">${esc(a.title)}</span>${a.sign_off ? '<span class="badge b-warn">sign-off</span>' : ""}</div>
      <div class="what">${esc(a.name)}</div><div class="state" id="s-${id}">idle</div></div>`;

  main.innerHTML = `
    <section class="hero reveal"><div class="eyebrow">Workspace · Agent teams</div><h1>Watch the desk team work a question, one step at a time.</h1>
      <p class="lede" id="counts"></p>
      <p class="lede">Pick a question below. The flow lights up as the live trace reaches each agent, and anything that needs an action stops at your sign-off.</p></section>
    <section class="bento">
      <div class="card c4 reveal agent-list"><div class="card-cap">The team<span class="spacer"></span><span class="mono">${A.length} agents</span></div>
        <div class="flow-step">The lead</div>${item(lead)}<div class="flow-step">Specialists</div>${specs.map(item).join("")}<div class="flow-step">The reviewer</div>${item(rev)}</div>
      <div class="card c8 reveal"><div class="card-cap">How the question moves<span class="spacer"></span><span class="badge b-idle" id="flow-state">waiting for a question</span></div>
        <div class="flow-step">1 · The lead</div>${node(lead, lead.name)}
        <div class="flow-arrow">asks the specialists it needs, one at a time</div>
        <div class="flow-step">2 · Specialists, working together</div><div class="flow-row">${specs.map((s) => node(s, s.name)).join("")}</div>
        <div class="flow-arrow">every proposal goes to</div>
        <div class="flow-step">3 · The reviewer</div>${node(rev, rev.name)}
        <div class="flow-arrow">only then</div>
        <div class="flow-step">4 · Your sign-off</div>
        <button class="flow-node signoff" id="n-signoff" style="width:100%;text-align:left;color:var(--fg);font:inherit;cursor:pointer">
          <div class="who">You hold to approve</div><div class="what">each proposal opens with what it could not settle, the agent's case and what it read</div>
          <div class="state" id="s-signoff"></div></button>
      </div>
    </section>
    <section><div class="eyebrow reveal">Run a question</div><h2 class="reveal">Ask the team, and watch the trace</h2>
      <div class="card reveal"><div class="chips" id="chips">${sc.map((s) => `<button class="chip" data-p="${esc(s.prompt)}"><span class="mono">${esc(s.id)}</span>${esc(s.title)}</button>`).join("")}</div>
        <div class="composer"><textarea id="q" rows="2" placeholder="Ask the desk. Enter sends, Shift+Enter adds a new line." aria-label="Question for the desk"></textarea>
          <div class="btn-row"><button class="btn primary" id="send">Send</button><button class="btn" id="stop" hidden>Stop</button></div></div>
        <div class="status-line" id="status">No question asked yet.</div></div>
      <div class="split" style="margin-top:16px">
        <div class="card reveal"><div class="card-cap">The desk's answer</div><div id="answer"><p class="dim">No answer yet. The lead's reply appears here when it finishes.</p></div></div>
        <div class="card reveal"><div class="card-cap">Trace</div><div class="console" id="trace"><span class="dim">The trace of every agent and tool call appears here.</span></div></div>
      </div></section>
    <section><div class="eyebrow reveal">Your sign-off</div><h2 class="reveal">Waiting for a person</h2><div class="reveal" id="queue"></div></section>
    <section class="read"><div class="eyebrow reveal">Honest limits</div><h2 class="reveal">What stands between this team and a run</h2>
      <div class="note reveal"><ul class="tight">${ag.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div></section>
    <div id="prov"></div>`;

  function counts() {
    el("counts").textContent = `${A.length} agents you can talk to · ${pendingN()} need your sign-off · ${ag.sign_off_count} of the team can propose an action, none can execute one.`;
    el("s-signoff").textContent = pendingN() ? `${pendingN()} waiting · open the first` : "nothing waiting";
    el("n-signoff").classList.toggle("active", pendingN() > 0);
  }
  async function refreshQueue() {
    actions = await Shell.api("/api/actions");
    el("queue").innerHTML = D.actionRows(actions);
    D.bindQueue(el("queue"), actions, refreshQueue);
    counts();
  }
  el("n-signoff").addEventListener("click", () => { const a = actions.find((x) => x.status === "pending"); if (a) D.openAction(a, refreshQueue); else el("queue").scrollIntoView(); });

  const n$ = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const setNode = (id, cls, text) => {
    const n = el(`n-${id}`); if (!n) return;
    n.classList.remove("active", "done"); if (cls) n.classList.add(cls);
    el(`s-${id}`).textContent = text;
  };
  function resetFlow() { [lead, ...specs, rev].forEach((a) => setNode(a.name, null, "idle")); }

  const runner = window.Runner({
    consoleEl: el("trace"), statusEl: el("status"),
    onEvent: (e, st) => {
      const calls = (n) => (st.agents[n] ? st.agents[n].calls : 0);
      if (e.type === "tool_call") {
        if (e.author === LEAD) {
          setNode(LEAD, "active", `routing · ${n$(calls(LEAD), "call", "calls")}`);
          if (el(`n-${e.tool}`)) setNode(e.tool, "active", "asked by the lead");
        } else setNode(e.author, "active", `working · ${n$(calls(e.author), "tool call", "tool calls")}`);
      } else if (e.type === "tool_result" && e.author === LEAD && el(`n-${e.tool}`)) {
        setNode(e.tool, "done", `done · ${n$(calls(e.tool), "tool call", "tool calls")}`);
      } else if (e.type === "pending_action" || e.type === "audit") {
        refreshQueue();
      } else if (e.type === "text" && e.author === LEAD) {
        el("answer").innerHTML = D.md(e.text);
      }
      el("flow-state").className = "badge b-info"; el("flow-state").textContent = "live";
    },
    onDone: (st) => {
      setNode(LEAD, st.errors.length ? null : "done", st.errors.length ? `stopped: ${st.errors[0]}` : `done · ${n$(st.agents[LEAD] ? st.agents[LEAD].calls : 0, "call", "calls")}`);
      [...specs, rev].forEach((a) => { const s = st.agents[a.name]; if (s && !s.done && s.calls) setNode(a.name, "done", `done · ${n$(s.calls, "tool call", "tool calls")}`); else if (!s) setNode(a.name, null, "not asked this time"); });
      el("flow-state").className = st.errors.length ? "badge b-crit" : "badge b-ok"; el("flow-state").textContent = st.errors.length ? "stopped" : "finished";
      if (!st.answer) el("answer").innerHTML = `<p class="nodata">NO ANSWER WRITTEN</p><p class="dim">${esc(st.errors[0] || "The lead did not write a reply.")}</p>`;
      busy(false); refreshQueue();
    },
  });
  function busy(b) { el("send").disabled = b; el("stop").hidden = !b; el("chips").querySelectorAll(".chip").forEach((c) => (c.disabled = b)); }
  function ask(text) {
    if (!text.trim() || runner.running) return;
    resetFlow(); el("trace").innerHTML = ""; el("answer").innerHTML = '<p class="dim">The team is working. The answer appears when the lead finishes.</p>';
    busy(true); runner.run(text.trim());
  }
  el("chips").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) { el("q").value = b.dataset.p; ask(b.dataset.p); } });
  el("send").addEventListener("click", () => ask(el("q").value));
  el("stop").addEventListener("click", () => runner.stop());
  el("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(el("q").value); } });

  await refreshQueue();
  el("prov").innerHTML = await D.provenance([["This page", "/api/agents, /api/scenarios, /api/actions; the flow is lit from the /api/chat event stream"]]);
  Motion.reveal();
})();
