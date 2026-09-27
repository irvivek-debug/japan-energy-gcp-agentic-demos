/* Workspace · My role. The PRD personas from /api/v2/personas: what each is answerable for, the question that
 * governs their work, the agents they ask (from /api/v2/teams), their latest runs with the server's status label
 * and provenance, their suggested questions, and a chat side panel on the Lab Analyst (/api/chat).
 */
(async function () {
  const { $, esc, t, st, txt, isNum, badge, footer, provTag, runStatus, h } = window.LAB;
  LAB.nav("workspace", "persona");
  const S = { p: null, session: null, busy: false };

  let PS, TM;
  try {
    [PS, TM] = await Promise.all([Shell.api("/api/v2/personas"), Shell.api("/api/v2/teams")]);
  } catch (e) {
    $("role-lede").innerHTML = LAB.errorNote("/api/v2/personas, /api/v2/teams", e);
    return;
  }
  const personas = PS.personas || [];
  const teams = TM.teams || [];
  const sel = $("role-select");
  sel.innerHTML = personas.map((p, i) => `<option value="${i}">${esc(p.name)}, ${esc(p.role)}</option>`).join("");
  const fromUrl = new URLSearchParams(location.search).get("role");
  const start = Math.max(0, personas.findIndex((p) => p.id === fromUrl));
  sel.value = String(start);
  sel.addEventListener("change", () => {
    const p = personas[Number(sel.value)];
    try { history.replaceState(null, "", `?role=${encodeURIComponent(p.id)}`); } catch (e) { /* file or sandboxed view */ }
    show(p);
  });

  function show(p) {
    S.p = p;
    $("role-title").textContent = `${p.name}, ${p.role}`;
    $("role-lede").innerHTML =
      `Seen from ${esc(p.org_view)}. Works on ${esc((p.problems || []).map(LAB.problemLabel).join(" and "))}. ` +
      `<span class="dim">Source: ${esc(PS.source || "not stated")}.</span>`;

    const agents = (p.agents || []).map((id) => teams.find((x) => x.id === id) || { id, name: id });
    const latest = Object.entries(p.latest_runs || {});
    $("panel").innerHTML =
      `<div class="card reveal" style="margin-bottom:16px"><div class="card-cap">Your governing question</div><p class="quote">${esc(p.governing_question)}</p></div>` +
      `<div class="bento" style="margin-bottom:16px">` +
      `<div class="card c6 reveal"><div class="card-cap">What you're answerable for</div><ul class="plain">${(p.answerable_for || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` +
      `<div class="card c6 reveal"><div class="card-cap">Your latest runs</div>` +
      (latest.length
        ? `<ul class="plain">${latest
            .map(([prob, b]) =>
              `<li><div class="row" style="justify-content:space-between"><b>${esc(LAB.problemLabel(prob))}</b>${runStatus(b)}</div>` +
              `<div class="mono small" style="margin-top:4px">${esc(b.run_id)}</div>` +
              `<div class="small muted" style="margin-top:4px">Held-out delta ${b.uplift_valid ? st(b.holdout_delta, "JPY M") : isNum(b.champion_raw_delta) && !b.infrastructure_failure ? `not citable; raw ${st(b.champion_raw_delta, "JPY M")} before the rules` : LAB.NITD} · fold <span class="mono">${esc(b.holdout_fold)}</span></div>` +
              LAB.caveat(b.caveat) +
              `<div style="margin-top:6px">${provTag(b.provenance)}</div></li>`)
            .join("")}</ul>`
        : `<p class="muted small" style="margin:0">No finished run for your problems yet.</p>`) +
      `</div></div>` +
      `<div class="card-cap reveal" style="border:0;margin-bottom:8px">The agents you ask</div>` +
      agents
        .map((a) =>
          `<div class="card agent-card reveal" style="margin-bottom:16px"><div class="row" style="justify-content:space-between;margin:0"><h3 style="margin:0">${esc(a.name)}</h3>` +
          `<span class="row">${(a.signoff_tools || []).length ? badge("SIGN-OFF", "b-warn") : badge("READ ONLY", "b-idle")}${a.pattern ? badge(`PATTERN ${a.pattern}`, "b-info") : ""}</span></div>` +
          `<p class="small muted" style="margin:8px 0 0">${a.model ? `Runs on ${esc(a.model)}. ` : ""}${(a.signoff_tools || []).length ? `It can call ${esc(a.signoff_tools.join(", "))} to propose a write; nothing is written until you confirm on the sign-off sheet.` : ""}</p>` +
          (a.reads ? `<div class="card-cap" style="margin-top:12px">What it reads</div><div class="chips">${a.reads.map((x) => `<span class="pill">${esc(x)}</span>`).join("")}</div>` : "") +
          `</div>`)
        .join("") +
      `<div class="card reveal"><div class="card-cap">Questions to start with</div><div class="q-list">` +
      (p.suggested_questions || []).map((q, i) => `<button class="btn" type="button" data-q="${i}">${esc(q)}</button>`).join("") +
      `</div></div>`;
    $("panel").querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => send(p.suggested_questions[Number(b.dataset.q)])));
    Motion.reveal();
  }

  /* ---------- chat side panel ---------- */
  function msg(role, text) {
    const body = h("div", { class: "body" });
    const el = h("div", { class: `msg ${role}` }, h("span", { class: "who" }, role === "user" ? "You" : "Lab Analyst"), body);
    if (text) LAB.renderRich(body, text);
    $("transcript").append(el);
    $("transcript").scrollTop = $("transcript").scrollHeight;
    return { el, body };
  }
  function busy(b) {
    S.busy = b;
    $("chat-send").disabled = b;
    $("panel").querySelectorAll("[data-q]").forEach((x) => (x.disabled = b));
  }
  async function send(question) {
    const q = String(question || "").trim();
    if (!q || S.busy) return;
    busy(true);
    msg("user", q);
    const reply = msg("assistant", "");
    reply.body.textContent = "Working.";
    let text = "";
    const pending = [];
    LAB.trace($("trace"), "dim", `POST /api/chat (session ${S.session || "new"})`);
    const out = await LAB.ask(q, S.session, (ev) => {
      LAB.traceEvent($("trace"), ev);
      if (ev.type === "session") S.session = ev.session_id;
      if (ev.type === "text" && ev.text) {
        text += (text && !text.endsWith("\n") ? "\n\n" : "") + ev.text;
        LAB.renderRich(reply.body, text);
        $("transcript").scrollTop = $("transcript").scrollHeight;
      }
      if (ev.type === "pending_action" && ev.action) pending.push(ev.action);
    });
    busy(false);
    if (!out.ok) {
      reply.el.classList.add("err");
      reply.el.querySelector(".who").textContent = "Lab Analyst · ERROR";
      reply.body.replaceChildren(h("strong", {}, "Error: "), LAB.failText(out.error));
      if (!out.frame) LAB.trace($("trace"), "crit", `ERROR · ${LAB.failText(out.error)}`);
      if (text) LAB.trace($("trace"), "warn", `${text.length} characters of partial text were discarded; they are not an answer`);
      if (pending.length) LAB.trace($("trace"), "warn", "A proposal arrived before the failure. It was not opened here; it waits in the Cockpit approval queue.");
      return;
    }
    if (!text) reply.body.textContent = "The analyst finished without writing any text. Open the trace to see what it did.";
    const a = pending[pending.length - 1];
    if (a) {
      const open = () => LAB.signOffAction(a, { reasoning: text.replace(/\*\*/g, ""), onDone: (r) => LAB.trace($("trace"), "ok", `sign-off recorded for ${a.id}: server status ${r && r.status}`) });
      reply.el.append(h("div", { class: "btn-row", style: "margin-top:8px" }, h("button", { class: "btn", type: "button", onclick: open }, "Open the sign-off sheet")));
      open();
    }
  }
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("chat-input").value;
    if (!v.trim() || S.busy) return;
    $("chat-input").value = "";
    send(v);
  });
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); }
  });
  msg("assistant", "Ask about a run, a rule or the market. Answers cite the lab tables they came from, and anything that writes to the record waits for your sign-off.");
  LAB.trace($("trace"), "dim", "Trace ready.");

  show(personas[start]);
  $("prov").innerHTML = footer([
    ["Roles", `<span class="mono">/api/v2/personas</span> · ${esc(PS.source || "")}`],
    ["Agents", `<span class="mono">${esc((TM.source || []).join(", "))}</span>`],
    ["Chat", `<span class="mono">POST /api/chat</span> (server-sent events)`],
    ["Runs", provTag((teams.find((x) => x.provenance) || {}).provenance)],
  ]);
  Motion.reveal();
})();
