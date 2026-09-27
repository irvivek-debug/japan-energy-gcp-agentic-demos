/* Workspace · Agent teams. Left: the teams from /api/v2/teams, each with a SIGN-OFF badge where a person has to
 * confirm. Right: "How the question moves", four flow nodes that light as the live SSE trace from /api/chat
 * reaches them (lead, specialists, reviewer, your sign-off), a trace console, and a scenario runner built from
 * the roles' own suggested questions. Below: what stands between this team and a run.
 */
(async function () {
  const { $, esc, t, txt, isNum, badge, footer, provTag, h, plural } = window.LAB;
  LAB.nav("workspace", "swarm");
  const S = { team: null, session: null, busy: false, tracker: null, text: "", pending: [], persona: 0 };

  let TM, PS;
  try {
    [TM, PS] = await Promise.all([Shell.api("/api/v2/teams"), Shell.api("/api/v2/personas")]);
  } catch (e) {
    $("lede-data").innerHTML = LAB.errorNote("/api/v2/teams, /api/v2/personas", e);
    return;
  }
  const teams = TM.teams || [];
  const talk = teams.filter((x) => Array.isArray(x.tools));
  const personas = PS.personas || [];
  const hasSignoff = (tm) => (tm.signoff_tools || []).length > 0 || (tm.stages || []).some((s) => /sign-off/i.test(s.role));
  const provenance = (teams.find((x) => x.provenance) || {}).provenance;

  $("lede-data").innerHTML =
    `${esc(plural(teams.length, "team works", "teams work"))} in this lab. ${esc(txt(talk.length, 0))} of them answers questions in plain language; ` +
    `the other writes and scores programs as a batch job. Anything that writes to the record stops at your sign-off. ` +
    `Every run either team reports on came from the ${provTag(provenance)}.`;

  /* ---------- rail ---------- */
  $("rail-cap").textContent = `Teams · ${teams.length}`;
  $("rail").innerHTML = teams
    .map(
      (tm, i) =>
        `<button type="button" class="rail-row" data-team="${i}" aria-pressed="false">` +
        `<span class="nm">${esc(tm.name)}${hasSignoff(tm) ? badge("SIGN-OFF", "b-warn") : ""}${Array.isArray(tm.tools) ? badge("YOU CAN ASK", "b-info") : badge("BATCH", "b-idle")}</span>` +
        `<span class="sb">${esc(tm.pattern ? `pattern ${tm.pattern}` : tm.provenance || "")}${tm.model ? ` · ${esc(tm.model)}` : ""}</span>` +
        `<span class="sb">${Array.isArray(tm.tools) ? `${esc(txt(tm.tools.length, 0))} tools · reads ${esc(txt((tm.reads || []).length, 0))} tables` : `${esc(txt((tm.stages || []).length, 0))} stages, counted per finished run`}</span>` +
        `</button>`
    )
    .join("");
  $("rail").querySelectorAll(".rail-row").forEach((b) => b.addEventListener("click", () => selectTeam(Number(b.dataset.team))));

  /* ---------- flow ---------- */
  function statHtml(stat) {
    if (!stat) return "";
    const v = stat.value;
    if (v && typeof v === "object")
      return `<div class="stat-l" style="margin-top:8px">${esc(stat.label)}</div><div class="chips" style="margin-top:4px">${Object.entries(v).map(([k, n]) => `<span class="pill">${esc(k)}: ${esc(txt(n, 0))}</span>`).join("") || '<span class="pill">none</span>'}</div>`;
    return `<div class="stat">${isNum(v) ? esc(txt(v, 0)) : LAB.NITD}</div><div class="stat-l">${esc(stat.label)}</div>`;
  }
  function selectTeam(i) {
    S.team = teams[i];
    $("rail").querySelectorAll(".rail-row").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.team) === i)));
    const tm = S.team;
    $("team-tag").innerHTML = `${esc(tm.name)}`;
    $("flow").innerHTML = (tm.stages || [])
      .map(
        (s, k) =>
          (k ? '<div class="flow-arrow" aria-hidden="true">↓</div>' : "") +
          `<div class="flow-step">${esc(s.step)} · ${esc(s.role)}</div>` +
          `<div class="flow-node${/sign-off/i.test(s.role) ? " signoff" : ""}" data-step="${esc(s.step)}"><div class="node-head"><span class="who">${esc(s.name)}</span><span class="state badge b-idle">WAITING</span></div>` +
          `<div class="what">${esc(s.detail)}</div>` +
          (s.step === 2 && Array.isArray(tm.tools) ? `<div class="chips" style="margin-top:8px">${tm.tools.map((x) => `<span class="pill" data-tool="${esc(x)}">${esc(x)}${(tm.signoff_tools || []).includes(x) ? " · SIGN-OFF" : ""}</span>`).join("")}</div>` : "") +
          statHtml(s.stat) +
          (/sign-off/i.test(s.role) && Array.isArray(tm.tools) ? `<div class="btn-row" style="margin-top:10px"><button class="btn" type="button" id="reopen" hidden>Open the sign-off sheet</button></div>` : "") +
          `</div>`
      )
      .join("");
    S.tracker = LAB.flowTracker([...$("flow").querySelectorAll(".flow-node")]);
    S.tracker.reset();
    if ($("reopen")) $("reopen").addEventListener("click", openPending);
    runner();
  }

  /* ---------- scenario runner ---------- */
  function runner() {
    const tm = S.team;
    if (!Array.isArray(tm.tools)) {
      $("runner").innerHTML =
        `<p class="muted" style="margin:0">This team runs as a batch job and does not take questions. Its trace is the run record: ` +
        `open the <a href="/workspace/">Cockpit</a> to read it, or ask the Lab Analyst about any run.</p>`;
      return;
    }
    const p = personas[S.persona] || {};
    $("runner").innerHTML =
      `<div class="controls"><label class="fl" for="persona-pick" style="flex:0 1 360px">Scenario from a role<select class="field" id="persona-pick">` +
      personas.map((x, i) => `<option value="${i}"${i === S.persona ? " selected" : ""}>${esc(x.name)}, ${esc(x.role)}</option>`).join("") +
      `</select></label></div><div class="q-list" style="margin-top:12px">` +
      (p.suggested_questions || []).map((q, i) => `<button class="btn" type="button" data-q="${i}">${esc(q)}</button>`).join("") +
      `</div><form class="composer" id="ask" style="margin-top:12px"><label class="sr-only" for="ask-input">Your own question</label>` +
      `<input class="field" id="ask-input" type="text" placeholder="Or ask your own question"><button class="btn primary" type="submit">Run</button></form>` +
      `<div id="answer" style="margin-top:16px"></div>`;
    $("persona-pick").addEventListener("change", (e) => { S.persona = Number(e.target.value); runner(); });
    $("runner").querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => run(p.suggested_questions[Number(b.dataset.q)])));
    $("ask").addEventListener("submit", (e) => { e.preventDefault(); const v = $("ask-input").value.trim(); if (v) { $("ask-input").value = ""; run(v); } });
  }

  function setBusy(b) {
    S.busy = b;
    $("runner").querySelectorAll("button").forEach((x) => (x.disabled = b));
  }

  async function run(question) {
    if (S.busy) return;
    setBusy(true);
    S.text = "";
    S.pending = [];
    S.tracker.reset();
    if ($("reopen")) $("reopen").hidden = true;
    $("flow").querySelectorAll("[data-tool]").forEach((c) => c.classList.remove("b-info"));
    const box = $("answer");
    const body = h("div", { class: "answer" });
    box.replaceChildren(h("div", { class: "card-cap" }, "The question"), h("p", { style: "margin:0 0 12px" }, question), h("div", { class: "card-cap" }, "The answer, as it arrives"), body);
    body.textContent = "Waiting for the lead.";
    LAB.trace($("trace"), "dim", `POST /api/chat (session ${S.session || "new"})`);
    const out = await LAB.ask(question, S.session, (ev) => {
      LAB.traceEvent($("trace"), ev);
      if (ev.type !== "error") S.tracker.event(ev);
      if (ev.type === "session") S.session = ev.session_id;
      if (ev.type === "tool_call") {
        const chip = $("flow").querySelector(`[data-tool="${CSS.escape(String(ev.tool))}"]`);
        if (chip) chip.classList.add("b-info");
      }
      if (ev.type === "text" && ev.text) {
        S.text += (S.text && !S.text.endsWith("\n") ? "\n\n" : "") + ev.text;
        LAB.renderRich(body, S.text);
      }
      if (ev.type === "pending_action" && ev.action) S.pending.push(ev.action);
    });
    setBusy(false);
    if (!out.ok) {
      // A failure is shown as a failure: no partial text is left looking like an answer, no later step is lit.
      S.tracker.fail();
      if (S.text) LAB.trace($("trace"), "warn", `${S.text.length} characters of partial text were discarded; they are not an answer`);
      body.replaceChildren(h("div", { class: "note crit", role: "alert" }, h("strong", {}, "Error"), h("br"), LAB.failText(out.error)));
      if (!out.frame) LAB.trace($("trace"), "crit", `ERROR · ${LAB.failText(out.error)}`);
      if (S.pending.length) LAB.trace($("trace"), "warn", "A proposal arrived before the failure. It was not opened here; it waits in the Cockpit approval queue.");
      return;
    }
    if (!S.text) body.textContent = "The analyst finished without writing any text. The trace below shows what it did.";
    if (S.pending.length) {
      if ($("reopen")) $("reopen").hidden = false;
      openPending();
    }
  }
  function openPending() {
    const a = S.pending[S.pending.length - 1];
    if (!a) return;
    LAB.signOffAction(a, {
      reasoning: S.text.replace(/\*\*/g, ""),
      onDone: (r) => {
        const rejected = r && r.status === "rejected";
        LAB.trace($("trace"), rejected ? "warn" : "ok", `${rejected ? "rejected" : "sign-off recorded"} for ${a.id}: server status ${r && r.status}`);
        const st = $("flow").querySelector('.flow-node[data-step="4"] .state');
        if (st) { st.textContent = rejected ? "REJECTED BY YOU" : "SIGNED OFF"; st.className = `state badge ${rejected ? "b-idle" : "b-ok"}`; }
        if ($("reopen")) $("reopen").hidden = true;
      },
    }).then((opened) => { if (!opened) LAB.trace($("trace"), "warn", `pending action ${a.id} (${a.kind}) is not a review; it waits in the Cockpit queue`); });
  }
  $("trace-clear").addEventListener("click", () => $("trace").replaceChildren());
  LAB.trace($("trace"), "dim", "Trace ready. Tool calls from the Lab Analyst appear here as they happen.");

  /* ---------- honest limits ---------- */
  $("limits").innerHTML = (TM.limits || [])
    .map((x) => `<li>${badge(x.ok ? "READY" : "BLOCKED", x.ok ? "b-ok" : "b-warn")}<div><b>${esc(x.item)}</b><br><span class="small muted">${esc(x.text)}</span></div></li>`)
    .join("");

  selectTeam(Math.max(0, teams.findIndex((x) => Array.isArray(x.tools))));

  $("prov").innerHTML =
    Shell.technicalDrawer(
      `<p class="small">The flow nodes light from the event stream: text before any tool call is the lead, tool calls and results are the specialists, ` +
        `text after the tools and the final frame are the reviewer, and a pending action is your sign-off. Each node carries a word as well as a border.</p>` +
        `<dl class="kv">${teams.map((tm) => `<dt>${esc(tm.id)}</dt><dd class="mono">${esc(tm.name)}${tm.reads ? ` · reads ${esc(tm.reads.join(", "))}` : ""}</dd>`).join("")}</dl>`,
      "how the nodes light"
    ) +
    footer([
      ["Teams and limits", `<span class="mono">${esc((TM.source || []).join(", "))}</span> · day ${esc(TM.day || "NOT IN THE DATA")}`],
      ["Scenarios", `<span class="mono">/api/v2/personas</span> · ${esc(PS.source || "")}`],
      ["Live trace", `<span class="mono">POST /api/chat</span> (server-sent events)`],
      ["Runs", provTag(provenance)],
    ]);
  Motion.reveal();
})();
