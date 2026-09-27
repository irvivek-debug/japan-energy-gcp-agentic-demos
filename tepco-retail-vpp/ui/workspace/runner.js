/* One live run of the desk team over /api/chat, shared by Agent teams, My role and Handover.
 * It keeps the session, streams the trace into a console, tracks what each agent did (tool calls, sources, its own
 * last words) and reports progress in plain words. It never approves anything: pending actions are only surfaced. */
(function () {
  const LEAD = "desk_orchestrator";

  function Runner({ consoleEl, statusEl, onEvent = () => {}, onDone = () => {} } = {}) {
    let sessionId = null, ctrl = null, t0 = 0, tick = null, running = false;
    const state = { agents: {}, pending: [], answer: "", errors: [] };
    const ag = (n) => (state.agents[n] = state.agents[n] || { calls: 0, sources: new Set(), text: "", asked: false, done: false });
    const say = (t) => { if (statusEl) statusEl.textContent = t; };
    const log = (html) => {
      if (!consoleEl || !html) return;
      const d = document.createElement("div");
      d.innerHTML = html;
      consoleEl.appendChild(d);
      consoleEl.scrollTop = consoleEl.scrollHeight;
    };

    function handle(e) {
      if (e.type === "tool_call") {
        const a = ag(e.author); a.calls += 1;
        if (e.author === LEAD && e.tool !== "get_desk_clock" && e.tool !== "read_handover_note") { ag(e.tool).asked = true; }
        say(`${e.author} is calling ${e.tool}`);
      } else if (e.type === "tool_result") {
        [].concat(e.source || []).forEach((s) => ag(e.author).sources.add(window.Desk.srcShort(s)));
        if (e.author === LEAD && state.agents[e.tool]) state.agents[e.tool].done = true;
      } else if (e.type === "text") {
        if (e.author === LEAD) state.answer = e.text; else ag(e.author).text = e.text;
      } else if (e.type === "pending_action") {
        state.pending.push(e.action);
        say(`${e.action.id} needs your sign-off`);
      } else if (e.type === "error") {
        state.errors.push(e.error);
      }
      log(window.Desk.traceLine(e));
      onEvent(e, state);
    }

    async function run(message) {
      if (running) return;
      running = true;
      state.agents = {}; state.pending = []; state.answer = ""; state.errors = [];
      ctrl = new AbortController();
      t0 = Date.now();
      if (consoleEl) log(`<span class="dim">you → ${window.Desk.esc(message)}</span>`);
      say("desk_orchestrator is reading the question");
      tick = setInterval(() => { if (statusEl) statusEl.dataset.elapsed = `${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
      try {
        sessionId = await window.Desk.chat(message, { sessionId, onEvent: handle, signal: ctrl.signal });
        say(state.errors.length ? `Stopped with an error after ${Math.round((Date.now() - t0) / 1000)} s` : `Answered in ${Math.round((Date.now() - t0) / 1000)} s`);
      } catch (e) {
        state.errors.push(e.name === "AbortError" ? "stopped by you" : e.message);
        say(e.name === "AbortError" ? "Stopped. Nothing was executed." : `The desk could not answer: ${e.message}`);
      } finally {
        clearInterval(tick); running = false; ctrl = null;
        onDone(state);
      }
    }
    return { run, stop: () => ctrl && ctrl.abort(), get running() { return running; }, state, reset: () => { sessionId = null; } };
  }

  window.Runner = Runner;
  window.Runner.LEAD = LEAD;
})();
