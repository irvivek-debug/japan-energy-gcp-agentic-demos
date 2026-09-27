/* Workspace · Handover. A promotion dossier per run, from /api/v2/dossier/{run_id}: the gate with PASS / BLOCKED
 * words, the champion's lineage, the held-out table, the catches, the cost and the reviews. Two sections, one per
 * team: the evolution loop's run record (always present, it is data) and the Lab Analyst's brief, which starts as
 * "Not yet written" and is only ever filled by a completed answer from /api/chat. A failed call leaves it saying
 * so. Promotion is a disabled button with the server's reason; marking reviewed goes through the sign-off sheet.
 */
(async function () {
  const { $, esc, t, st, txt, isNum, badge, footer, provTag, runStatus, h, when } = window.LAB;
  LAB.nav("workspace", "handover");
  const S = { runs: [], labels: {}, runId: null, dossier: null, busy: false, session: null, brief: null };
  const enc = encodeURIComponent;

  let R, P;
  try {
    [R, P] = await Promise.all([Shell.api("/api/runs"), Shell.api("/api/v2/proof")]);
  } catch (e) {
    $("dossier").innerHTML = LAB.errorNote("/api/runs, /api/v2/proof", e);
    return;
  }
  (P.runs || []).forEach((b) => (S.labels[b.run_id] = b));
  S.runs = R.runs || [];
  const failed = (r) => !!(S.labels[r.run_id] || {}).infrastructure_failure;
  const sel = $("run-select");
  sel.innerHTML = S.runs
    .map((r) => `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${esc(r.status === "running" ? "RUNNING, PARTIAL EVIDENCE" : (S.labels[r.run_id] || {}).status_label || r.status)}</option>`)
    .join("");
  // Default: the newest finished run that generated something; the picker still lists every run.
  const def = S.runs.find((r) => r.status === "finished" && !failed(r)) || S.runs[0];
  if (!def) {
    $("dossier").innerHTML = `<div class="card"><p class="muted" style="margin:0">No run has written evidence yet.</p></div>`;
    return;
  }
  sel.value = def.run_id;
  sel.addEventListener("change", () => load(sel.value));
  $("print").addEventListener("click", () => window.print());
  $("write").addEventListener("click", () => write());

  async function load(id) {
    S.runId = id;
    S.brief = null;
    $("dossier").innerHTML = `<p class="muted">Reading the dossier for <span class="mono">${esc(id)}</span>.</p>`;
    try {
      S.dossier = await Shell.api(`/api/v2/dossier/${enc(id)}`);
    } catch (e) {
      $("dossier").innerHTML = LAB.errorNote(`/api/v2/dossier/${id}`, e);
      return;
    }
    if (id !== S.runId) return;
    render();
  }

  function render() {
    const d = S.dossier;
    const run = { ...(d.run || {}), status: d.status };
    const g = d.gate || {};
    const ch = d.champion || {};
    const ho = d.holdout || {};
    const tk = d.tokens || {}, bu = d.budget || {};
    const isFailed = !!run.infrastructure_failure;
    const canReview = d.status === "finished" && !!g.best_program_id && !isFailed;
    const reviewReason = canReview
      ? "Opens the sign-off sheet. Holding to confirm appends one audit record; it never promotes."
      : isFailed ? "Disabled: no program was generated in this run, so there is nothing evolved to read."
        : d.status !== "finished" ? `Disabled: the run is ${d.status || "not finished"}.` : "Disabled: no champion is recorded.";

    // Catches, grouped by kind so a run that failed forty times does not print forty identical lines.
    const byKind = {};
    (d.catches || []).forEach((c) => (byKind[c.kind] = byKind[c.kind] || []).push(c));
    const catchesHtml = Object.keys(byKind).length
      ? Object.entries(byKind)
          .map(([k, list]) =>
            `<div class="catch"><div class="row">${badge(`kind: ${k}`, "b-crit")}<span class="mono small">${esc(LAB.plural(list.length, "candidate", "candidates"))}</span></div>` +
            list.slice(0, 3).map((c) => `<p class="ins"><span class="mono">#${esc(c.idx)} ${esc(c.id)}</span>${(c.invariants || []).length ? ` · rules broken: ${esc(c.invariants.join(", "))}` : ""}<br>${esc(c.insight)}</p>`).join("") +
            (list.length > 3 ? `<p class="cap-note">${esc(txt(list.length - 3, 0))} more of the same kind are in the run record.</p>` : "") +
            `</div>`)
          .join("")
      : `<p class="muted small" style="margin:0">No candidate was rejected in this run.</p>`;

    const rawOf = (row) => ((row.holdout_insights || []).find((i) => i.label === "raw_objective") || {}).text;
    $("dossier").innerHTML =
      `<section><div class="card reveal"><div class="card-cap">Run<span class="spacer"></span>${runStatus(run)}</div>` +
      `<h2 class="mono" style="font-family:var(--mono);font-size:18px;overflow-wrap:anywhere">${esc(run.run_id || S.runId)}</h2>` +
      `<div class="row">${provTag(d.provenance)} ${badge(LAB.problemLabel(run.problem), "b-idle")} ${badge(`fold ${run.holdout_fold || ho.fold || "not recorded"}`, "b-idle")}</div>` +
      `<dl class="kv" style="margin-top:12px"><dt>Evaluator</dt><dd>${esc(d.evaluator_version || "NOT IN THE DATA")}</dd>` +
      `<dt>Started</dt><dd>${esc(when(run.started))}</dd>` +
      `<dt>Instances</dt><dd class="mono small">${esc(Object.entries(d.instances || {}).map(([k, v]) => `${k}: ${v.name} (sha256 ${String(v.sha256 || "").slice(0, 12)})`).join(" · ") || "NOT IN THE DATA")}</dd></dl>` +
      LAB.caveat(run.caveat) +
      (d.uplift_note ? `<div class="note" style="margin-top:12px"><strong>Held-out note</strong><br>${esc(d.uplift_note)}</div>` : "") +
      `</div></section>` +

      // ---- section 1: the evolution loop's record ----
      `<section><div class="eyebrow reveal">1 · From the evolution loop</div><h2 class="reveal">The run record</h2>` +
      `<p class="lede reveal">Written by the run itself, not by an agent. Every line below is read from the run file.</p>` +
      `<div class="bento">` +
      `<div class="card c6 reveal"><div class="card-cap">Promotion gate</div>` +
      (g.checks || []).map((c) => `<div class="check"><span>${badge(c.ok ? "PASS" : "BLOCKED", c.ok ? "b-ok" : "b-crit")}</span><div>${esc(c.label)}<span class="v">${esc(c.id)}: ${esc(LAB.valueText(c.value))}</span></div></div>`).join("") +
      `<label class="fl no-print" for="review-note" style="margin-top:12px">Reviewer note<textarea class="field" id="review-note" rows="2" placeholder="What did you read in the evolved block?"></textarea></label>` +
      `<div class="btn-row" style="margin-top:10px"><button class="btn primary" type="button" id="review-btn"${canReview ? "" : " disabled"} aria-describedby="review-reason">Mark human-reviewed</button><span class="reason" id="review-reason">${esc(reviewReason)}</span></div>` +
      `<div class="btn-row" style="margin-top:8px"><button class="btn" type="button" disabled aria-describedby="promote-reason">Promote to production</button><span class="reason" id="promote-reason">Promotion control: ${esc(d.promotion_control || "NOT IN THE DATA")}</span></div></div>` +

      `<div class="card c6 reveal"><div class="card-cap">Champion lineage</div>` +
      `<p class="small" style="margin:0 0 8px">Champion <span class="mono">${esc(ch.id || "none")}</span> from ${esc(ch.model || "NOT IN THE DATA")}: training score ${t(ch.train, "JPY M")}, ${st(ch.train_delta_vs_seed, "JPY M")} against the seed on training (not citable).</p>` +
      `<ol class="lineage">${(ch.lineage || []).map((l) => `<li><span class="mono">${esc(l.id)}</span> · ${esc(l.model)} · ${t(l.score, "JPY M", 1)}</li>`).join("") || `<li>${LAB.NITD}</li>`}</ol></div>` +

      `<div class="card c12 reveal"><div class="card-cap">Held-out fold ${esc(ho.fold || "")}</div>` +
      `<dl class="kv"><dt>Seed</dt><dd>${t(ho.seed, "JPY M")} (valid: ${esc(String(ho.seed_valid))})</dd><dt>Champion</dt><dd>${t(ho.best_holdout, "JPY M")}</dd>` +
      `<dt>Held-out delta</dt><dd>${run.uplift_valid ? st(ho.holdout_delta, "JPY M") : isNum(ho.holdout_delta) ? `${st(ho.holdout_delta, "JPY M")} <span class="dim">not citable</span>` : LAB.NITD}</dd>` +
      `<dt>Selection</dt><dd class="small">${esc(ho.selection || "NOT IN THE DATA")}</dd></dl>` + LAB.caveat(run.caveat) +
      `<div class="table-scroll" style="margin-top:12px"><table class="data"><thead><tr><th>Program</th><th class="num">Train</th><th class="num">Held out</th><th>Check</th><th>Before the rules</th></tr></thead><tbody>` +
      ((ho.top_k || []).map((r) => `<tr><td class="mono rid">${esc(r.id)}${r.id === ho.best_id ? " ★" : ""}</td><td class="num">${t(r.train, "", 1)}</td><td class="num">${t(r.holdout, "", 1)}</td>` +
        `<td>${r.holdout_valid ? badge("VALID", "b-ok") : badge(`INVALID${r.holdout_kind ? ", " + r.holdout_kind : ""}`, "b-crit")}</td><td class="small muted">${esc(rawOf(r) || "")}</td></tr>`).join("") ||
        `<tr><td colspan="5">${LAB.NITD}</td></tr>`) +
      `</tbody></table></div></div>` +

      `<div class="card c6 reveal"><div class="card-cap">Candidates rejected before they could count</div>${catchesHtml}</div>` +
      `<div class="card c6 reveal"><div class="card-cap">Cost and budget</div><dl class="kv">` +
      `<dt>Programs</dt><dd>${t(bu.programs_evaluated, "", 0)} of ${t(bu.max_programs, "", 0)} · stopped: ${esc(bu.stopped_reason || "not recorded")}</dd>` +
      `<dt>Wall time</dt><dd>${t(bu.wall_s, "s", 1)}</dd><dt>Model calls</dt><dd>${t(tk.calls, "", 0)} (${t(tk.errors, "errors", 0)})</dd>` +
      `<dt>Tokens</dt><dd>${t(tk.prompt, "prompt", 0)} · ${t(tk.output, "output", 0)} · ${t(tk.thinking, "thinking", 0)}</dd>` +
      `<dt>Estimated cost</dt><dd>${t(tk.cost_usd, "USD", 4)}</dd></dl>` +
      `<div class="card-cap" style="margin-top:16px">Reviews recorded (${esc(txt((d.reviews || []).length, 0))})</div>` +
      ((d.reviews || []).length
        ? `<ul class="plain">${d.reviews.map((r) => `<li class="small"><span class="mono">${esc(when(r.at))} · ${esc(r.reviewer)} · ${esc(r.program_id)}</span>${r.note ? `<br>${esc(r.note)}` : ""}</li>`).join("")}</ul>`
        : `<p class="muted small" style="margin:0">No human review recorded for this run.</p>`) +
      `</div></div></section>` +

      // ---- section 2: the analyst's brief, honest until written ----
      `<section><div class="eyebrow reveal">2 · From the Lab Analyst</div><h2 class="reveal">The brief for the next desk</h2>` +
      `<div class="card brief-sec reveal" id="brief"></div></section>`;

    briefState();
    if (canReview)
      $("review-btn").addEventListener("click", () =>
        LAB.signOffReview({
          runId: run.run_id, gate: { ...g, promotion_control: d.promotion_control }, provenance: d.provenance, caveat: run.caveat,
          reasoning: `The champion ${g.best_program_id} scored ${txt(ch.train, 1)} JPY M on training, ${txt(ch.train_delta_vs_seed, 1)} JPY M against the seed. ` +
            `On fold ${ho.fold || "not recorded"} its held-out delta is ${isNum(ho.holdout_delta) ? txt(ho.holdout_delta, 1) + " JPY M" : "NOT IN THE DATA"} (uplift valid: ${String(run.uplift_valid)}). ` +
            `Marking it human-reviewed records that a person read the evolved block. It does not promote it.`,
          sources: d.source || [],
          note: () => ($("review-note") ? $("review-note").value : ""),
          onDone: () => load(S.runId),
        })
      );
    $("write").disabled = S.busy;
    prov();
    Motion.reveal();
  }

  /** The brief section: Not yet written, Writing, Written, or Not written because the call failed. */
  function briefState() {
    const el = $("brief");
    if (!el) return;
    const b = S.brief;
    const cap = h("div", { class: "card-cap" }, "Lab Analyst · handover brief", h("span", { class: "spacer" }));
    if (!b) {
      el.replaceChildren(cap, h("div", { class: "state-line" }, "Not yet written"),
        h("p", { class: "muted", style: "margin:6px 0 0" }, `Nobody has asked the analyst to write this brief for ${S.runId}. Press "Write this brief now" and it will read the run tables and write it here.`));
      return;
    }
    if (b.state === "writing") {
      el.replaceChildren(cap, h("div", { class: "state-line", style: "color:var(--accent)" }, "Writing"), h("p", { class: "muted", style: "margin:6px 0 0" }, "The analyst is reading the run. Nothing is shown here until it finishes."), b.console);
      return;
    }
    if (b.state === "failed") {
      el.replaceChildren(cap, h("div", { class: "state-line", style: "color:var(--critical)" }, "Not written"),
        h("div", { class: "note crit", role: "alert", style: "margin-top:8px" }, h("strong", {}, "Error"), h("br"), `Not written: the model call failed (${b.error}).`), b.console);
      return;
    }
    const body = h("div", { class: "answer" });
    LAB.renderRich(body, b.text);
    el.replaceChildren(cap, h("div", { class: "state-line", style: "color:var(--success)" }, `Written ${when(b.at)} by the Lab Analyst`), body, b.console);
  }

  async function write() {
    if (S.busy || !S.runId) return;
    S.busy = true;
    $("write").disabled = true;
    const runId = S.runId;
    const con = h("div", { class: "console", role: "log", style: "margin-top:12px;max-height:220px" });
    const details = h("details", { class: "drawer no-print", style: "margin-top:12px" }, h("summary", {}, "Trace", h("span", { class: "hint" }, "what the analyst read")), h("div", { class: "body" }, con));
    S.brief = { state: "writing", console: details };
    briefState();
    const prompt =
      `Write a short handover brief for run ${runId}. Say what the champion changed against the seed, whether it held on the held-out fold, ` +
      `which rules caught candidates, and what a reviewer must read before signing off. Cite the tables you read.`;
    LAB.trace(con, "dim", `POST /api/chat · ${prompt}`);
    let text = "";
    const pending = [];
    const out = await LAB.ask(prompt, S.session, (ev) => {
      LAB.traceEvent(con, ev);
      if (ev.type === "session") S.session = ev.session_id;
      if (ev.type === "text" && ev.text) text += (text && !text.endsWith("\n") ? "\n\n" : "") + ev.text;
      if (ev.type === "pending_action" && ev.action) pending.push(ev.action);
    });
    S.busy = false;
    $("write").disabled = false;
    if (runId !== S.runId) return;
    if (!out.ok) {
      if (!out.frame) LAB.trace(con, "crit", `ERROR · ${LAB.failText(out.error)}`);
      if (text) LAB.trace(con, "warn", `${text.length} characters of partial text were discarded; they are not a brief`);
      S.brief = { state: "failed", error: out.error, console: details };
    } else if (!text.trim()) {
      S.brief = { state: "failed", error: "the analyst finished without writing any text", console: details };
    } else {
      S.brief = { state: "written", text, at: Date.now(), console: details };
    }
    briefState();
    const a = pending[pending.length - 1];
    if (a && out.ok) LAB.signOffAction(a, { reasoning: text.replace(/\*\*/g, ""), onDone: () => load(S.runId) });
  }

  function prov() {
    $("prov").innerHTML = footer([
    ["Dossier", `<span class="mono">/api/v2/dossier/${esc(S.runId)}</span> · ${esc(((S.dossier || {}).source || []).join(", "))}`],
    ["Run list", `<span class="mono">/api/runs</span>, status labels from <span class="mono">/api/v2/proof</span>`],
    ["Brief", `<span class="mono">POST /api/chat</span>, written only on request`],
    ["Runs", provTag(P.provenance_label)],
    ]);
  }
  await load(def.run_id);
})();
