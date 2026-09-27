/* My role: pick one of the four desk roles from the PRD. The page shows what you are answerable for (live figures),
 * your governing question, the day before and with the desk, the agents you ask, and a chat side panel seeded with
 * the questions your role asks. A proposal raised in chat opens through the sign-off sheet. */
(async function () {
  const D = window.Desk, { esc, el, num } = D;
  Shell.mountNav("workspace", "persona");
  const main = el("page");
  let P, ag;
  try { [P, ag] = await Promise.all([Shell.api("/api/personas"), Shell.api("/api/agents")]); } catch (e) { D.fail(main, e); return; }
  const roles = P.personas;
  const byName = Object.fromEntries(ag.agents.map((a) => [a.name, a]));
  let current = (() => { try { return new URLSearchParams(location.search).get("role") || localStorage.getItem("desk-role"); } catch (_) { return null; } })();
  if (!roles.some((r) => r.id === current)) current = roles[0].id;

  main.innerHTML = `
    <section class="reveal" style="padding-top:24px"><div class="eyebrow">Workspace · My role</div>
      <div class="persona-pick" role="group" aria-label="Choose your role">${roles.map((r) => `<button class="card" data-role="${esc(r.id)}" aria-pressed="false">
        <div class="mono-cap">${esc(r.subtitle)}</div><div style="font:600 15px var(--sans);margin-top:4px">${esc(r.title)}</div></button>`).join("")}</div></section>
    <section class="bento">
      <div class="c7" id="role"></div>
      <aside class="c5"><div class="card" style="position:sticky;top:84px">
        <div class="card-cap">Ask the desk as this role<span class="spacer"></span><button class="btn" id="reset" style="min-height:32px;padding:0 12px">New conversation</button></div>
        <div class="chips" id="chips"></div>
        <div class="chatlog" id="log" style="margin-top:12px"><p class="dim">Pick a suggested question or write your own. Answers take a little while; the status line shows which agent is working.</p></div>
        <div class="composer"><textarea id="q" rows="2" placeholder="Enter sends, Shift+Enter adds a new line" aria-label="Question for the desk"></textarea>
          <div class="btn-row"><button class="btn primary" id="send">Send</button><button class="btn" id="stop" hidden>Stop</button></div></div>
        <div class="status-line" id="status"></div>
        <details class="drawer" style="margin-top:10px"><summary>Trace<span class="hint">every agent and tool call</span></summary><div class="body"><div class="console" id="trace"></div></div></details>
      </div></aside>
    </section>
    <div id="prov"></div>`;

  function renderRole() {
    const r = roles.find((x) => x.id === current);
    main.querySelectorAll("[data-role]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.role === current)));
    const agents = r.agents.map((n) => byName[n]).filter(Boolean);
    el("role").innerHTML = `
      <div class="reveal"><h1 style="margin-top:8px">${esc(r.title)}</h1><p class="lede">${esc(r.subtitle)}</p></div>
      <div class="card reveal" style="margin-top:16px"><div class="card-cap">What you're answerable for</div>
        <div class="bento" style="gap:12px">${r.answerable_for.map((m, i) => `<div class="c4 kpi"><div class="mono-cap">${esc(m.label)}</div>
          <div class="metric" id="m-${i}">${m.value === null ? '<span class="metric gap">NOT IN THE DATA</span>' : ""}</div>
          <div class="metric-sub">${esc(m.source.map(D.srcShort).join(", "))}</div></div>`).join("")}</div></div>
      <div class="jtbd reveal" style="margin-top:16px"><div class="eyebrow">Your governing question</div><div class="q">${esc(r.question)}</div></div>
      <div class="before-after reveal" style="margin-top:16px"><div class="card"><div class="card-cap">Today</div><p>${esc(r.today)}</p></div>
        <div class="card after"><div class="card-cap">With the desk</div><p>${esc(r.with_desk)}</p></div></div>
      <div class="card reveal" style="margin-top:16px"><div class="card-cap">In your words</div><dl class="kv">${Object.entries(r.empathy).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
      <h2 class="reveal" style="margin-top:32px">The agents you ask</h2>
      <div class="stack">${agents.map((a) => `<div class="card reveal"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <span class="mono" style="background:var(--surface-top);border-radius:8px;padding:3px 7px">${esc(a.code)}</span><h3 style="margin:0">${esc(a.title)}</h3>
          <span class="spacer" style="flex:1"></span><span class="badge b-idle">pattern ${esc(a.pattern)}</span>${a.sign_off ? '<span class="badge b-warn">sign-off</span>' : '<span class="badge b-info">advisory</span>'}</div>
          <p style="margin:8px 0">${esc(a.role)}</p><div class="dim mono">reads: ${esc(a.reads.join(", "))}</div></div>`).join("")}</div>`;
    r.answerable_for.forEach((m, i) => { if (m.value !== null) Motion.countUp(el(`m-${i}`), m.value, { dp: Number.isInteger(m.value) ? 0 : 1, unit: m.unit }); });
    el("chips").innerHTML = r.suggested.map((s) => `<button class="chip" data-p="${esc(s.prompt)}"><span class="mono">${esc(s.id)}</span>${esc(s.title)}</button>`).join("");
    try { localStorage.setItem("desk-role", current); } catch (_) {}
    Motion.reveal();
  }
  main.querySelectorAll("[data-role]").forEach((b) => b.addEventListener("click", () => { current = b.dataset.role; renderRole(); }));

  const log = el("log");
  const msg = (who, html, cls = "") => { const d = document.createElement("div"); d.className = `msg ${cls}`; d.innerHTML = `<div class="who">${esc(who)}</div>${html}`; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; };
  let pendingBox = null;
  const runner = window.Runner({
    consoleEl: el("trace"), statusEl: el("status"),
    onEvent: (e) => {
      if (e.type === "pending_action") {
        if (!pendingBox) pendingBox = msg("Needs your sign-off", '<div class="btn-row" id="pa"></div>');
        const b = document.createElement("button");
        b.className = "btn"; b.textContent = `Review ${D.KIND[e.action.kind] || e.action.kind}`;
        b.addEventListener("click", async () => { const all = await Shell.api("/api/actions"); const a = all.find((x) => x.id === e.action.id); if (a) D.openAction(a); });
        pendingBox.querySelector(".btn-row").appendChild(b);
      }
    },
    onDone: (st) => {
      msg("The desk", st.answer ? D.md(st.answer) : `<p class="nodata">NO ANSWER WRITTEN</p><p class="dim">${esc(st.errors[0] || "The lead did not reply.")}</p>`);
      busy(false);
    },
  });
  function busy(b) { el("send").disabled = b; el("stop").hidden = !b; el("chips").querySelectorAll(".chip").forEach((c) => (c.disabled = b)); }
  function ask(text) {
    if (!text.trim() || runner.running) return;
    if (log.querySelector("p.dim")) log.innerHTML = "";
    msg("You", `<p>${esc(text)}</p>`, "user"); pendingBox = null;
    el("trace").innerHTML = ""; el("q").value = ""; busy(true);
    runner.run(text.trim());
  }
  el("chips").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) ask(b.dataset.p); });
  el("send").addEventListener("click", () => ask(el("q").value));
  el("stop").addEventListener("click", () => runner.stop());
  el("reset").addEventListener("click", () => { runner.reset(); log.innerHTML = '<p class="dim">A new conversation. The desk does not remember the previous one.</p>'; el("trace").innerHTML = ""; });
  el("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(el("q").value); } });

  renderRole();
  el("prov").innerHTML = await D.provenance([["This page", "roles from docs/PRD.md section 4 via /api/personas; figures computed live by the same tools the agents call"]]);
  Motion.reveal();
})();
