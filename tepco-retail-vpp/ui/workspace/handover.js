/* Handover: a brief the agents write, on request, for the trader who takes the desk next. Every section starts in an
 * honest "Not yet written" state. "Write this brief now" runs the lead, which asks the teams it needs; each team's
 * section is that team's own last words in the run, with the sources it read. A team the lead did not ask says so. */
(async function () {
  const D = window.Desk, { esc, el, num } = D, LEAD = window.Runner.LEAD;
  Shell.mountNav("workspace", "handover");
  const main = el("page");
  const KEY = "desk-handover-v2";
  let ag, clock, facts, actions;
  try {
    [ag, clock, facts, actions] = await Promise.all([Shell.api("/api/agents"), Shell.api("/api/clock"), Shell.api("/api/story/facts"), Shell.api("/api/actions")]);
  } catch (e) { D.fail(main, e); return; }
  const order = [ag.agents.find((a) => a.step === 1), ...ag.agents.filter((a) => a.step === 2), ag.agents.find((a) => a.step === 3)];
  const g = clock.next_gate_closure;
  const PROMPT = "Write the shift handover brief for the trader who takes over the desk now. Ask the trading, contract risk and " +
    "clean energy provenance teams for their part, and have the risk auditor review any proposal. For each part say what is open, " +
    "what is waiting for sign-off, and what the next shift must watch before the next gate closures.";

  main.innerHTML = `
    <section class="hero read reveal"><div class="eyebrow">Workspace · Handover</div><h1>Desk handover brief</h1>
      <p class="lede">What the trader taking the desk needs, written by the agents on request. Each team writes its own part from the
        tables it reads; the lead writes the summary; the auditor reviews anything proposed. Nothing here is written until you ask.</p>
      <div class="btn-row no-print"><button class="btn primary" id="write">Write this brief now</button><button class="btn" id="print">Print this brief</button>
        <button class="btn" id="stop" hidden>Stop</button></div>
      <div class="status-line no-print" id="status"></div></section>
    <section class="read"><div class="card reveal"><div class="card-cap">Shift window</div><dl class="kv">
      <dt>Desk clock</dt><dd>${esc(clock.now.replace("T", " "))} JST, half hour ${esc(clock.current_slot_time)}</dd>
      <dt>Next gate closure</dt><dd>${g ? `slot ${g.slot} (${esc(g.slot_time)}) closes at ${esc(g.gate_closure.slice(11))}, in ${g.minutes_left} min` : "no gate open today"}</dd>
      <dt>Open half hours</dt><dd>${esc(clock.open_slots_today)}</dd>
      <dt>Open short</dt><dd>${esc(D.f(facts.short_mwh, "MWh"))} across slots ${esc(Object.keys(facts.short_by_slot).join(", "))}</dd>
      <dt>Waiting for sign-off</dt><dd id="waiting"></dd>
      <dt>Brief written</dt><dd id="written">not yet</dd></dl></div></section>
    <section class="read"><div class="eyebrow reveal">The brief</div><div class="stack" id="secs"></div></section>
    <section class="read no-print"><div class="eyebrow reveal">Raised while writing</div><h2 class="reveal">Waiting for your sign-off</h2><div id="queue" class="reveal"></div></section>
    <section class="read no-print reveal"><details class="drawer"><summary>How this brief was written<span class="hint">the trace of every agent and tool call</span></summary>
      <div class="body"><div class="console" id="trace"><span class="dim">No brief has been written in this browser session.</span></div></div></details></section>
    <div id="prov"></div>`;

  const title = (a) => (a.step === 1 ? "Summary from the lead" : a.title);
  function section(a, s, done) {
    if (!s || (!s.text && !(a.name === LEAD && s.answer))) {
      const asked = done && s && s.asked;
      const state = !done ? ["b-idle", "not yet written"] : asked ? ["b-warn", "asked, no words returned"] : ["b-idle", "not asked"];
      const why = !done ? "No agent has written this section in this browser session." :
        asked ? "The lead asked this team, but the team returned no text of its own. Nothing is claimed for it." :
        "The lead did not ask this team for this brief. Nothing is claimed for it.";
      return `<div class="brief-sec empty"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><h3 style="margin:0">${esc(title(a))}</h3>
        <span class="spacer" style="flex:1"></span><span class="badge ${state[0]}">${esc(state[1])}</span></div>
        <p class="dim" style="margin:8px 0 0">${esc(why)}</p><div class="foot mono">${esc(a.name)}</div></div>`;
    }
    const text = a.name === LEAD ? s.answer : s.text;
    return `<div class="brief-sec"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><h3 style="margin:0">${esc(title(a))}</h3>
      <span class="spacer" style="flex:1"></span><span class="badge b-ok">written</span></div>
      <div style="margin-top:10px">${D.md(text)}</div>
      <div class="foot">Written by <span class="mono">${esc(a.name)}</span> in this session · ${s.calls} tool call${s.calls === 1 ? "" : "s"}${s.sources && s.sources.length ? ` · read ${esc(s.sources.join(", "))}` : ""}</div></div>`;
  }
  function draw(saved) {
    const done = !!saved;
    el("secs").innerHTML = order.map((a) => section(a, saved ? { ...(saved.sections[a.name] || {}), answer: saved.answer } : null, done)).join("");
    el("written").textContent = saved ? `${saved.written_at} (your browser clock), ${saved.seconds} s to write` : "not yet";
    Motion.reveal();
  }
  async function refreshQueue() {
    actions = await Shell.api("/api/actions");
    const pend = actions.filter((a) => a.status === "pending");
    el("waiting").textContent = pend.length ? `${pend.length} proposal${pend.length === 1 ? "" : "s"}` : "nothing";
    el("queue").innerHTML = D.actionRows(actions);
    D.bindQueue(el("queue"), actions, refreshQueue);
  }

  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (_) { saved = null; }
  draw(saved);

  let t0 = 0;
  const runner = window.Runner({
    consoleEl: el("trace"), statusEl: el("status"),
    onEvent: (e) => { if (e.type === "pending_action" || e.type === "audit") refreshQueue(); },
    onDone: (st) => {
      const sections = {};
      Object.entries(st.agents).forEach(([n, a]) => { sections[n] = { text: a.text, calls: a.calls, sources: Array.from(a.sources), asked: a.asked }; });
      sections[LEAD] = { ...(sections[LEAD] || {}), asked: true };
      const out = { written_at: new Date().toLocaleString("en-GB"), seconds: Math.round((Date.now() - t0) / 1000), answer: st.answer, sections, errors: st.errors };
      if (st.answer || Object.values(sections).some((s) => s.text)) {
        saved = out;
        try { sessionStorage.setItem(KEY, JSON.stringify(out)); } catch (_) {}
      }
      draw(saved || out);
      if (st.errors.length) el("status").textContent = `The brief stopped: ${st.errors[0]}. Sections without text stay unwritten.`;
      busy(false); refreshQueue();
    },
  });
  function busy(b) { el("write").disabled = b; el("stop").hidden = !b; }
  el("write").addEventListener("click", () => {
    if (runner.running) return;
    t0 = Date.now(); el("trace").innerHTML = ""; busy(true);
    el("secs").querySelectorAll(".brief-sec .badge").forEach((b) => { b.className = "badge b-info"; b.textContent = "writing"; });
    runner.run(PROMPT);
  });
  el("stop").addEventListener("click", () => runner.stop());
  el("print").addEventListener("click", () => window.print());

  await refreshQueue();
  el("prov").innerHTML = await D.provenance([["This page", "/api/clock, /api/story/facts, /api/agents, /api/actions; sections are written by the agents through /api/chat"]]);
  Motion.reveal();
})();
