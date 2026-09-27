/* Workspace · Cockpit. The v1 operational panels in the v2 language: a counted KPI row, the experiments (problem
 * tabs, run picker, score by program, islands, seed against champion, held-out fold, promotion gate, catches,
 * budget and ledger), the approval queue, and the scenario explorer. Every figure is read from /api; runs are
 * listed as the server lists them, so a run that starts or finishes appears on the next refresh.
 *
 * Generated text (diffs, rationales, insights, notes) goes into the page as text through LAB.h, never as HTML.
 */
(async function () {
  const { $, esc, t, st, txt, isNum, badge, footer, provTag, runStatus, h, counts, countEl, chart, tokens, grid, axisTip, when, plural } = window.LAB;
  LAB.nav("workspace", "cockpit");
  const T = tokens();
  const POLL_MS = 15000;
  const S = {
    problem: null, runs: [], labels: {}, provenance: null, runId: null, run: null, holdout: null, gate: null,
    programId: null, pinned: false, holdoutMode: "delta", fy: null, costV: "HV", calSorted: false, cal: null, ledger: null, poll: 0,
  };
  const enc = encodeURIComponent;
  const fill = (el, ...kids) => { el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false)); return el; };
  const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
  const htmlNode = (html) => { const d = document.createElement("div"); d.innerHTML = html; return d; };
  const errInto = (el, where, e) => { if (el) el.innerHTML = LAB.errorNote(where, e); };
  const labelOf = (r) => ({ ...(r || {}), ...(S.labels[(r || {}).run_id] || {}) });
  const failedRun = (r) => !!(S.labels[r.run_id] || {}).infrastructure_failure;

  /* ================= header: who you can talk to, what waits for you, and the KPI row ================= */
  async function header() {
    const [teamsR, actionsR, runsR, proofR, ovR] = await Promise.allSettled([
      Shell.api("/api/v2/teams"), Shell.api("/api/actions"), Shell.api("/api/runs"), Shell.api("/api/v2/proof"), Shell.api("/api/overview"),
    ]);
    const val = (r) => (r.status === "fulfilled" ? r.value : null);
    const teams = val(teamsR), actions = val(actionsR) || [], runs = (val(runsR) || {}).runs || [], proof = val(proofR), ov = val(ovR);
    if (proof) {
      (proof.runs || []).forEach((b) => (S.labels[b.run_id] = { status_label: b.status_label, infrastructure_failure: b.infrastructure_failure, uplift_valid: b.uplift_valid, provenance: b.provenance, caveat: b.caveat }));
      S.provenance = proof.provenance_label;
    }
    if (!S.provenance && teams) S.provenance = ((teams.teams || []).find((x) => x.provenance) || {}).provenance;

    // Runs that need a sign-off: finished, generated something, and no human has read the champion yet.
    const candidates = runs.filter((r) => r.status === "finished" && !failedRun(r));
    const gates = await Promise.allSettled(candidates.map((r) => Shell.api(`/api/runs/${enc(r.run_id)}/gate`)));
    const unreviewed = gates.filter((g) => g.status === "fulfilled" && g.value.best_program_id && !(g.value.checks || []).find((c) => c.id === "human_review" && c.ok)).length;
    const pending = actions.filter((a) => a.status === "pending").length;
    const talk = teams ? (teams.teams || []).filter((x) => Array.isArray(x.tools)).length : null;
    $("counts").innerHTML =
      `<b>${esc(isNum(talk) ? plural(talk, "agent", "agents") : "NOT IN THE DATA")}</b> you can talk to · <b>${esc(txt(unreviewed + pending, 0))}</b> need your sign-off` +
      `<span class="dim"> (${esc(plural(unreviewed, "run", "runs"))} without a human review, ${esc(plural(pending, "proposal", "proposals"))} from the analyst)</span>`;

    // Best validated held-out delta per problem: a trading score and a tariff book are not on the same axis.
    const probs = [...new Set(runs.map((r) => r.problem))].sort();
    const bestOf = (p) => runs.filter((r) => r.problem === p && r.uplift_valid && isNum(r.holdout_delta)).reduce((m, r) => (m === null || r.holdout_delta > m.holdout_delta ? r : m), null);
    const programs = runs.reduce((a, r) => a + (Number(r.programs) || 0), 0);
    const port = (ov && ov.portfolio) || {};
    const kpi = (v, unit, label, note, d) => `<div class="card">${countEl(v, unit, d)}<div class="metric-sub">${esc(label)}</div>${note ? `<div class="cap-note" style="margin-top:6px">${note}</div>` : ""}</div>`;
    $("kpis").innerHTML =
      kpi(ov && ov.runs, "", "Finished runs", provTag(S.provenance)) +
      kpi(runs.length ? programs : null, "", "Programs evaluated", `across ${esc(txt(runs.length, 0))} runs listed`) +
      kpi(ov && ov.invalid_caught_total, "", "Invalid candidates caught", "sandbox, diff, rule and generation failures") +
      probs.map((p) => { const b = bestOf(p); const cav = b && (S.labels[b.run_id] || {}).caveat;
        return kpi(b && b.holdout_delta, "JPY M", `Best validated held-out delta, ${LAB.problemLabel(p)}`, b ? `<span class="mono">${esc(b.run_id)}</span>${cav ? `<br>${badge("WITH CAVEAT", "b-warn")}` : ""}` : "no run validated yet", 1); }).join("") +
      kpi(ov && ov.cost_usd_total, "USD", "Estimated search cost", "from token counts, not a bill", 2) +
      kpi(port.customers, "", "Customers in the book", `${t(port.annual_twh, "TWh", 2)} a year`);
    counts($("kpis"));
    return { ov, runs };
  }

  /* ================= experiments ================= */
  function tabs(problems) {
    const bar = $("problem-tabs");
    bar.innerHTML = problems
      .map((p, i) => `<button type="button" role="tab" id="tab-${esc(p)}" data-problem="${esc(p)}" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}" aria-controls="exp-panel">${esc(LAB.problemLabel(p))}</button>`)
      .join("");
    const btns = [...bar.querySelectorAll("button")];
    const select = (i, focus) => {
      btns.forEach((b, j) => { b.setAttribute("aria-selected", String(i === j)); b.tabIndex = i === j ? 0 : -1; });
      if (focus) btns[i].focus();
      $("exp-panel").setAttribute("aria-labelledby", btns[i].id);
      if (S.problem !== btns[i].dataset.problem) { S.problem = btns[i].dataset.problem; S.runId = null; loadRuns(); }
    };
    btns.forEach((b, i) => {
      b.addEventListener("click", () => select(i));
      b.addEventListener("keydown", (e) => {
        const k = { ArrowRight: (i + 1) % btns.length, ArrowLeft: (i - 1 + btns.length) % btns.length, Home: 0, End: btns.length - 1 }[e.key];
        if (k === undefined) return;
        e.preventDefault();
        select(k, true);
      });
    });
    select(0);
  }

  async function loadRuns() {
    let r;
    try { r = await Shell.api(`/api/runs?problem=${enc(S.problem)}`); } catch (e) { errInto($("run-header"), "/api/runs", e); return; }
    S.runs = r.runs || [];
    const sel = $("run-select");
    sel.innerHTML = S.runs
      .map((x) => { const l = labelOf(x); return `<option value="${esc(x.run_id)}">${esc(x.run_id)} · ${esc(x.status === "running" ? "RUNNING, PARTIAL EVIDENCE" : l.status_label || x.status)} · ${esc(txt(x.programs, 0))} programs</option>`; })
      .join("");
    if (!S.runId || !S.runs.some((x) => x.run_id === S.runId)) {
      // Default: the newest finished run that generated something; otherwise the newest run of any kind.
      const pick = S.runs.find((x) => x.status === "finished" && !failedRun(x)) || S.runs[0];
      S.runId = pick ? pick.run_id : null;
      S.programId = null; S.pinned = false;
    }
    sel.disabled = !S.runs.length;
    if (!S.runId) { $("run-header").innerHTML = `<p class="muted">No run evidence for ${esc(LAB.problemLabel(S.problem))} yet. A run appears here as soon as the controller writes its first evidence.</p>`; return; }
    sel.value = S.runId;
    await loadRun();
  }

  async function loadRun() {
    const id = S.runId;
    const [det, cat, ho, gate] = await Promise.allSettled([
      Shell.api(`/api/runs/${enc(id)}`), Shell.api(`/api/runs/${enc(id)}/catches`), Shell.api(`/api/runs/${enc(id)}/holdout`), Shell.api(`/api/runs/${enc(id)}/gate`),
    ]);
    if (id !== S.runId) return;
    if (det.status === "rejected") return errInto($("run-header"), `/api/runs/${id}`, det.reason);
    S.run = det.value;
    runHeader(S.run);
    scoreChart(S.run);
    programs(S.run);
    budget(S.run);
    if (cat.status === "fulfilled") catches(cat.value); else errInto($("catches"), `/api/runs/${id}/catches`, cat.reason);
    if (ho.status === "fulfilled") { S.holdout = ho.value; holdout(); } else errInto($("holdout-body"), `/api/runs/${id}/holdout`, ho.reason);
    if (gate.status === "fulfilled") { S.gate = gate.value; gatePanel(); } else { S.gate = null; errInto($("gate"), `/api/runs/${id}/gate`, gate.reason); }
    islands(S.run);
    if (!S.pinned || !S.programId) await loadDiff(S.pinned ? S.programId : "");
  }

  function runHeader(d) {
    const l = labelOf(d);
    const bl = d.baseline_lock || {};
    const b = d.budget || {};
    $("run-header").innerHTML =
      `<div class="row">${runStatus(l)} ${provTag(l.provenance || S.provenance)} ${badge(`source: ${d.source}`, "b-idle")} ${badge(`evolved: ${d.evolved}`, "b-idle")}</div>` +
      `<p class="mono small" style="margin:10px 0 0">${esc(d.run_id)} · started ${esc(when(d.started))}${d.finished ? ` · finished ${esc(when(d.finished))}` : ""} · ` +
      `${esc(txt(b.programs_evaluated, 0))} programs: ${esc(txt(d.valid, 0))} valid, ${esc(txt(d.invalid, 0))} invalid</p>` +
      LAB.caveat(l.caveat) +
      (d.honesty_note ? `<div class="note info" style="margin-top:12px"><strong>Run note</strong><br>${esc(d.honesty_note)}</div>` : "") +
      `<dl class="kv" style="margin-top:12px"><dt>Baseline lock</dt><dd>seed reproduced: ${esc(String(bl.reproduced))} · seed ${t(bl.seed_raw, "JPY M")} · ` +
      `null program ${t(bl.null_raw, "JPY M")} (valid: ${esc(String(bl.null_valid))}) · seed minus null ${st(bl.seed_minus_null, "JPY M")}</dd>` +
      `<dt>Instance</dt><dd class="mono">${esc(bl.instance_sha256 ? "sha256 " + bl.instance_sha256 : "NOT IN THE DATA")}</dd></dl>`;
  }

  const X_SYMBOL = "path://M2,0 L5,3 L8,0 L10,2 L7,5 L10,8 L8,10 L5,7 L2,10 L0,8 L3,5 L0,2 Z";
  function scoreChart(d) {
    const curve = d.score_curve || [];
    const byIdx = new Map((d.programs || []).map((p) => [p.idx, p]));
    const ok = (p) => p.valid && isNum(p.score);
    const valid = curve.filter(ok), invalid = curve.filter((p) => !ok(p));
    const ys = valid.map((p) => p.score).concat(isNum(d.seed_train) ? [d.seed_train] : []);
    $("score-note").textContent =
      (d.problem === "jepx_trading" ? "Scores are minus annual cost and risk, so they are negative; closer to zero is better. " : "Higher is better; the objective subtracts a tail-risk penalty, so scores can be negative. ") +
      `${valid.length} scored, ${invalid.length} invalid and not scored (crosses in the lower band).`;
    $("score-legend").innerHTML = `<span>● valid</span><span>✕ invalid</span><span>▬ best so far</span><span>┄ seed</span>`;
    if (!ys.length) { $("chart-score").innerHTML = `<p class="chart-missing">No scored programs yet.</p>`; return; }
    const lo = Math.min(...ys), hi = Math.max(...ys);
    const span = hi - lo || Math.max(1, Math.abs(hi) * 0.001);
    const band = lo - span * 0.23, bandTop = lo - span * 0.07, yMin = lo - span * 0.32, yMax = hi + span * 0.08;
    const tip = (idx) => {
      const pr = byIdx.get(idx) || {};
      const cp = curve.find((x) => x.idx === idx) || {};
      const out = [`<b>Program ${esc(idx)}</b> ${esc(pr.id || "")}`, `island ${esc(cp.island ?? pr.island ?? "")} · ${esc(pr.model || "")}`];
      if (ok(cp)) out.push(`score ${esc(txt(cp.score, 1))} JPY M`);
      else {
        out.push(`INVALID, kind ${esc(cp.kind || pr.kind || "unknown")}`);
        if (isNum(pr.raw_score)) out.push(`raw objective ${esc(txt(pr.raw_score, 1))} JPY M, not counted`);
      }
      if (pr.insight && pr.insight.text) out.push(esc(LAB.trunc(pr.insight.text, 160)));
      return out.join("<br>");
    };
    chart("chart-score", {
      grid: grid({ left: 84, top: 20, bottom: 44 }),
      tooltip: { trigger: "item", confine: true, formatter: (p) =>
        p.componentType === "markLine" ? `Seed ${esc(txt(d.seed_train, 1))} JPY M` : p.seriesName === "Best so far" ? `After program ${esc(p.value[0])}<br>best ${esc(txt(p.value[1], 1))} JPY M` : tip(p.value[0]) },
      xAxis: { type: "value", name: "program, in evaluation order", nameLocation: "middle", nameGap: 28, min: 0, max: Math.max(1, curve.length - 1), minInterval: 1, splitLine: { show: false } },
      yAxis: { type: "value", min: yMin, max: yMax,
        axisLabel: { showMinLabel: false, showMaxLabel: false, formatter: (v) => (v < bandTop ? "" : txt(v, 0)) } },
      series: [
        { name: "Valid program", type: "scatter", symbol: "circle", symbolSize: 8, itemStyle: { color: T.accent }, data: valid.map((p) => [p.idx, p.score]) },
        { name: "Invalid program", type: "scatter", symbol: X_SYMBOL, symbolSize: 11, itemStyle: { color: T.crit }, data: invalid.map((p) => [p.idx, band]),
          markArea: { silent: true, itemStyle: { color: "rgba(234,88,12,0.06)" }, label: { show: true, position: "insideTopLeft", color: T.crit, fontFamily: T.mono, fontSize: 10, formatter: "INVALID, NOT SCORED" },
            data: [[{ yAxis: yMin }, { yAxis: bandTop }]] } },
        { name: "Best so far", type: "line", step: "end", showSymbol: false, z: 1, lineStyle: { color: T.b[1], width: 1.75 }, itemStyle: { color: T.b[1] },
          data: curve.filter((p) => isNum(p.best)).map((p) => [p.idx, p.best]),
          markLine: isNum(d.seed_train) ? { symbol: "none", lineStyle: { color: T.fg, type: "dashed", width: 1 }, label: { color: T.muted, fontFamily: T.mono, fontSize: 10, position: "insideStartTop", formatter: `SEED ${txt(d.seed_train, 1)}` }, data: [{ yAxis: d.seed_train }] } : undefined },
      ],
    });
  }

  function islands(d) {
    const lb = d.island_leaderboard || {};
    const keys = Object.keys(lb).sort((a, b) => Number(a) - Number(b));
    const champ = (S.gate && S.gate.best_program_id) || null;
    if (!keys.length) return ($("islands").innerHTML = `<p class="muted small">No scored programs on any island yet.</p>`);
    $("islands").innerHTML = `<p class="cap-note" style="margin-top:0">Top three per island by training score. ★ marks the champion.</p>` + keys
      .map((k) => `<div class="island"><h4>Island ${esc(k)}</h4><table class="data"><tbody>` +
        lb[k].slice(0, 3).map((r, i) => `<tr><td class="mono rid">${i + 1}. ${esc(r.id)}${champ === r.id ? " ★" : ""}</td><td class="num">${t(r.score, "", 1)}</td></tr>`).join("") +
        `</tbody></table></div>`)
      .join("");
  }

  function programs(d) {
    const valid = (d.programs || []).filter((p) => p.valid && isNum(p.score)).sort((a, b) => b.score - a.score);
    const sel = $("program-select");
    sel.innerHTML = valid.map((p, i) => `<option value="${esc(p.id)}">${i + 1}. ${esc(p.id)} · ${esc(txt(p.score, 1))} JPY M · ${esc(p.model)}${p.idx === 0 ? " (seed)" : ""}</option>`).join("");
    if (S.programId && valid.some((p) => p.id === S.programId)) sel.value = S.programId;
  }

  async function loadDiff(pid) {
    const id = S.runId;
    let r;
    try { r = await Shell.api(`/api/runs/${enc(id)}/diff${pid ? `?program_id=${enc(pid)}` : ""}`); }
    catch (e) { errInto($("diff-body"), `/api/runs/${id}/diff`, e); $("diff-side").replaceChildren(); return; }
    if (id !== S.runId) return;
    S.programId = r.program_id;
    const sel = $("program-select");
    if ([...sel.options].some((o) => o.value === r.program_id)) sel.value = r.program_id;
    const lines = String(r.diff_vs_seed || "").split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    let adds = 0, dels = 0;
    const rows = lines.map((line) => {
      let cls = "ctx", g = " ", body = line.slice(1), sr = "";
      if (line.startsWith("+++") || line.startsWith("---")) { cls = "hdr"; body = line; }
      else if (line.startsWith("@@")) { cls = "hunk"; g = "@"; body = line; }
      else if (line.startsWith("+")) { cls = "add"; g = "+"; adds++; sr = "added: "; }
      else if (line.startsWith("-")) { cls = "del"; g = "-"; dels++; sr = "removed: "; }
      return h("div", { class: `dl ${cls}` }, h("span", { class: "g", "aria-hidden": "true" }, g), h("span", { class: "code" }, sr ? h("span", { class: "sr-only" }, sr) : null, body));
    });
    fill($("diff-body"),
      h("p", { class: "mono small", style: "margin:0 0 8px" }, `${r.program_id} · ${txt(r.score, 1)} JPY M · +${adds} lines added, -${dels} removed against the seed`),
      adds || dels ? h("div", { class: "diff", role: "region", tabindex: "0", "aria-label": `Unified diff, seed against ${r.program_id}` }, rows)
        : h("p", { class: "muted small" }, "No change against the seed block: this is the seed, or an identical copy of it."));
    const side = [];
    if ((r.insights || []).length) side.push(h("h4", {}, "What the evaluator saw"), h("ul", { class: "plain" }, r.insights.map((i) => h("li", {}, h("span", { class: "mono dim" }, `${i.label}: `), i.text))));
    side.push(h("h4", {}, "The model's rationale"), h("p", { class: "plain-text" }, r.rationale || "No rationale recorded."));
    if ((r.lineage || []).length) side.push(h("h4", {}, "Lineage, seed to champion"), h("ol", { class: "lineage" }, r.lineage.map((l) => h("li", {}, h("span", { class: "mono" }, `${l.id} · ${l.model} · ${txt(l.score, 1)} JPY M`)))));
    fill($("diff-side"), side);
  }

  function holdout() {
    const res = S.holdout || {};
    const d = S.run || {};
    const ho = res.holdout;
    const body = $("holdout-body");
    if (!ho) {
      body.innerHTML = `<p class="muted">${d.status === "running" ? "Held-out rescoring has not run yet. It runs once, after the search stops, on data the search never sees." : "No held-out record in this run's evidence."}</p>` +
        (res.uplift_note ? `<div class="note">${esc(res.uplift_note)}</div>` : "");
      return;
    }
    const upl = res.uplift_valid;
    const rows = ho.top_k || [];
    const mode = S.holdoutMode;
    const tv = (r) => (!isNum(r.train) ? null : mode === "delta" ? (isNum(d.seed_train) ? r.train - d.seed_train : null) : r.train);
    const hv = (r) => (!isNum(r.holdout) ? null : mode === "delta" ? (isNum(ho.seed) ? r.holdout - ho.seed : null) : r.holdout);
    body.innerHTML =
      `<div class="row" style="justify-content:space-between"><span class="metric">${isNum(ho.holdout_delta) ? `${ho.holdout_delta > 0 ? "+" : ""}${esc(txt(ho.holdout_delta, 1))}<span class="u">JPY M</span>` : LAB.NITD}</span>` +
      `${upl === true ? badge("UPLIFT VALID", "b-ok") : upl === false ? badge("UPLIFT NOT VALID", "b-crit") : badge("UPLIFT NOT RECORDED", "b-idle")}</div>` +
      `<div class="metric-sub">Held-out delta on fold ${esc(ho.fold || "holdout")}, the only citable uplift</div>` +
      LAB.caveat(labelOf(d).caveat) +
      (res.uplift_note ? `<div class="note" style="margin-top:12px">${esc(res.uplift_note)}</div>` : "") +
      (ho.selection ? `<p class="cap-note">Selection rule: ${esc(ho.selection)}</p>` : "") +
      `<dl class="kv" style="margin-top:10px"><dt>Seed</dt><dd>${t(ho.seed, "JPY M")} (valid: ${esc(String(ho.seed_valid))})</dd>` +
      `<dt>Champion</dt><dd><span class="mono">${esc(ho.best_id || "none")}</span>: ${t(ho.best_holdout, "JPY M")}${ho.best_is_seed ? " (the seed itself)" : ""}</dd>` +
      `<dt>Null program</dt><dd>${t(ho.null ?? ho.null_raw, "JPY M")} (valid: ${esc(String(ho.null_valid))})</dd></dl>` +
      `<div class="chart short" id="chart-holdout" role="img" aria-label="Train and held-out change for each top candidate"></div>` +
      `<div class="table-scroll"><table class="data"><thead><tr><th>Program</th><th class="num">Train</th><th class="num">Held out</th><th>Check</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td class="mono rid">${esc(r.id)}${r.id === ho.best_id ? " ★ champion" : ""}</td><td class="num">${t(r.train, "", 1)}</td><td class="num">${t(r.holdout, "", 1)}</td>` +
        `<td>${r.holdout_valid ? badge("VALID", "b-ok") : badge(`INVALID${r.holdout_kind ? ", " + r.holdout_kind : ""}`, "b-crit")}</td></tr>`).join("") +
      `</tbody></table></div><p class="cap-note">${mode === "delta" ? "Bars show change against the seed on the same fold." : "Absolute scores; compare each held-out bar with the seed line."} Invalid held-out bars are outlined and labelled.</p>`;
    chart("chart-holdout", {
      grid: grid({ left: 64, bottom: 40, top: 28 }),
      legend: { top: 0, right: 0, data: ["Train", "Held out"] },
      tooltip: axisTip((p) => `${esc(txt(p.value, 1))} JPY M`),
      xAxis: { type: "category", data: rows.map((r) => r.id), axisLabel: { fontSize: 9.5, rotate: rows.length > 3 ? 18 : 0 }, splitLine: { show: false } },
      yAxis: { type: "value", scale: mode !== "delta", axisLabel: { formatter: (v) => txt(v, 0) } },
      series: [
        { name: "Train", type: "bar", barMaxWidth: 22, data: rows.map(tv), itemStyle: { color: T.bx, decal: { symbol: "rect", symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: -0.785, color: "rgba(0,0,0,0.4)" } } },
        { name: "Held out", type: "bar", barMaxWidth: 22,
          data: rows.map((r) => (r.holdout_valid ? { value: hv(r), itemStyle: { color: T.accent } } : { value: hv(r) ?? 0, itemStyle: { color: "transparent", borderColor: T.crit, borderWidth: 1, borderType: "dashed" }, label: { show: true, position: "top", color: T.crit, fontFamily: T.mono, fontSize: 9.5, formatter: "INVALID" } })),
          markLine: { symbol: "none", lineStyle: { color: T.fg, type: "dashed", width: 1 }, label: { color: T.muted, fontFamily: T.mono, fontSize: 10, formatter: "SEED" }, data: [{ yAxis: mode === "delta" ? 0 : ho.seed }] } },
      ],
    });
  }

  function gatePanel() {
    const g = S.gate || {};
    const d = S.run || {};
    const failed = failedRun(d);
    const canReview = d.status === "finished" && !!g.best_program_id && !failed;
    const reason = canReview
      ? `Opens the sign-off sheet. Holding to confirm appends one audit record; it never promotes.`
      : failed ? "Disabled: no program was generated in this run, so there is nothing evolved to read."
        : d.status !== "finished" ? `Disabled: the run is ${d.status || "not finished"}. Reviews open when it finishes.` : "Disabled: no champion is recorded for this run.";
    const reviews = g.reviews || [];
    $("gate").innerHTML =
      `<div>${(g.checks || []).map((c) => `<div class="check"><span>${badge(c.ok ? "PASS" : "BLOCKED", c.ok ? "b-ok" : "b-crit")}</span><div>${esc(c.label)}<span class="v">${esc(c.id)}: ${esc(LAB.valueText(c.value))}</span></div></div>`).join("")}</div>` +
      `<p class="cap-note">${esc(txt((g.blockers || []).length, 0))} blockers · champion <span class="mono">${esc(g.best_program_id || "none")}</span></p>` +
      `<label class="fl" for="review-note" style="margin-top:12px">Reviewer note<textarea class="field" id="review-note" rows="2" placeholder="What did you read in the evolved block?"></textarea></label>` +
      `<div class="btn-row" style="margin-top:10px"><button class="btn primary" type="button" id="review-btn"${canReview ? "" : " disabled"} aria-describedby="review-reason">Mark human-reviewed</button>` +
      `<span class="reason" id="review-reason">${esc(reason)}</span></div>` +
      `<div class="btn-row" style="margin-top:8px"><button class="btn" type="button" disabled aria-describedby="promote-reason">Promote to production</button>` +
      `<span class="reason" id="promote-reason">Promotion control: ${esc(g.promotion_control || "NOT IN THE DATA")}</span></div>` +
      `<div class="card-cap" style="margin-top:16px">Reviews recorded (${esc(txt(reviews.length, 0))})</div>` +
      (reviews.length ? `<ul class="plain">${reviews.map((r) => `<li class="small"><span class="mono">${esc(when(r.at))} · ${esc(r.reviewer)} · ${esc(r.program_id)}</span>${r.note ? `<br>${esc(r.note)}` : ""}</li>`).join("")}</ul>` : `<p class="muted small" style="margin:0">No human review recorded for this run.</p>`);
    if (!canReview) return;
    $("review-btn").addEventListener("click", () =>
      LAB.signOffReview({
        runId: d.run_id, gate: g, provenance: labelOf(d).provenance || S.provenance, caveat: labelOf(d).caveat,
        reasoning: `The champion ${g.best_program_id} scored ${txt(d.best_train, 1)} JPY M on training against the seed's ${txt(d.seed_train, 1)} JPY M. ` +
          `On the held-out fold its delta is ${isNum(d.holdout_delta) ? txt(d.holdout_delta, 1) + " JPY M" : "NOT IN THE DATA"} (uplift valid: ${String(d.uplift_valid)}). ` +
          `Marking it human-reviewed records that a person read the evolved block. It does not promote it.`,
        sources: [`runs/${d.run_id}.json`, `/api/runs/${d.run_id}/gate`],
        note: () => ($("review-note") ? $("review-note").value : ""),
        onDone: () => refreshGate(),
      })
    );
  }
  async function refreshGate() {
    try { S.gate = await Shell.api(`/api/runs/${enc(S.runId)}/gate`); gatePanel(); } catch (e) { errInto($("gate"), "gate", e); }
    header();
  }

  function catches(c) {
    const list = c.catches || [];
    const kinds = Object.entries(c.by_kind || {});
    if (!list.length) return ($("catches").innerHTML = `<p class="muted small" style="margin:0">No invalid candidates in this run. Every program passed the sandbox and the rules.</p>`);
    const root = $("catches");
    root.innerHTML = `<div class="chips" style="margin-bottom:8px">${kinds.map(([k, n]) => `<span class="pill">✕ ${esc(k)}: ${esc(txt(n, 0))}</span>`).join("")}</div>`;
    const shown = list.slice(0, 12);
    const ul = h("div", {}, shown.map((x) =>
      h("div", { class: "catch" },
        h("div", { class: "row" }, h("span", { class: "mono small" }, `#${x.idx} ${x.id}`), htmlNode(badge(`kind: ${x.kind || "unknown"}`, "b-crit")).firstChild, h("span", { class: "dim small" }, x.model || "")),
        h("p", { class: "ins" }, (x.invariants || []).length ? `Rules broken: ${x.invariants.join(", ")}` : "No rule named for this catch."),
        (x.insights || []).slice(0, 2).map((i) => h("p", { class: "ins" }, `${i.label}: ${i.text}`)),
        h("p", { class: "ins" }, isNum(x.raw_score) ? `Would have scored ${txt(x.raw_score, 1)} JPY M against the seed's ${txt(c.seed_train, 1)} JPY M. Not counted.` : "No raw score: the program produced nothing to evaluate."))));
    root.append(ul);
    if (list.length > shown.length) root.append(h("p", { class: "cap-note" }, `${list.length - shown.length} more catches of the same kinds are in the run record.`));
  }

  function budget(d) {
    const b = d.budget || {}, pol = d.budget_policy || {}, tk = d.tokens || {};
    const pct = b.max_programs ? Math.min(100, (100 * (b.programs_evaluated || 0)) / b.max_programs) : 0;
    const led = S.ledger;
    $("budget").innerHTML =
      `<div class="meter" role="progressbar" aria-label="Programs evaluated" aria-valuemin="0" aria-valuemax="${esc(b.max_programs ?? 0)}" aria-valuenow="${esc(b.programs_evaluated ?? 0)}"><span style="width:${pct}%"></span></div>` +
      `<dl class="kv"><dt>Programs</dt><dd>${t(b.programs_evaluated, "", 0)} of ${t(b.max_programs, "", 0)}</dd>` +
      `<dt>Wall time</dt><dd>${t(b.wall_s, "s", 1)} of a ${t(pol.max_wall_s, "s", 0)} cap</dd>` +
      `<dt>Stopped</dt><dd>${esc(b.stopped_reason || (d.status === "running" ? "still running" : "not recorded"))}</dd>` +
      `<dt>Tokens</dt><dd>${t(tk.calls, "calls", 0)} · ${t(tk.prompt, "prompt", 0)} · ${t(tk.output, "output", 0)} · ${t(tk.thinking, "thinking", 0)}</dd>` +
      `<dt>Estimated cost</dt><dd>${t(tk.cost_usd, "USD", 4)}</dd>` +
      ((d.model_mix || []).length ? `<dt>Model mix</dt><dd class="mono">${esc(d.model_mix.map((m) => `${m.name} ${txt(m.weight * 100, 0)}%`).join(", "))}</dd>` : "") +
      `</dl>${d.pricing_note ? `<p class="cap-note">${esc(d.pricing_note)}</p>` : ""}` +
      `<div class="card-cap" style="margin-top:16px">Ledger</div>` +
      (led
        ? `<dl class="kv">${Object.entries(led.policy || {}).map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(txt(v, 0))}</dd>`).join("")}</dl>` +
          `<div class="table-scroll" style="margin-top:10px"><table class="data"><thead><tr><th>Run</th><th class="num">Programs</th><th>Status</th></tr></thead><tbody>` +
          (led.runs || []).slice().reverse().map((r) => `<tr><td class="mono rid">${esc(r.run_id)}</td><td class="num">${t(r.programs, "", 0)}</td><td>${esc(r.status)}${r.counts_against_budget ? "" : " · not counted"}</td></tr>`).join("") +
          `</tbody></table></div>`
        : `<p class="muted small">Ledger not loaded.</p>`);
  }

  /* ================= approval queue ================= */
  async function queue() {
    let list;
    try { list = await Shell.api("/api/actions"); } catch (e) { return errInto($("actions"), "/api/actions", e); }
    if (!list.length) {
      $("actions").innerHTML = `<p class="muted" style="margin:0">Nothing is waiting. When the Lab Analyst proposes recording a review, the proposal waits here until a person opens the sign-off sheet.</p>`;
      return;
    }
    const root = $("actions");
    root.innerHTML = `<ul class="plain">${list.map((a, i) =>
      `<li><div class="row" style="justify-content:space-between"><b>${esc(a.summary || a.kind)}</b>${badge(a.status === "pending" ? "PENDING" : String(a.status).toUpperCase(), a.status === "pending" ? "b-warn" : a.status === "rejected" ? "b-idle" : "b-ok")}</div>` +
      `<p class="cap-note">${esc(a.id)} · ${esc(a.kind)} · created ${esc(when(a.created))}${a.risk ? ` · risk: ${esc(a.risk)}` : ""}</p>` +
      (a.status === "pending" && a.kind === "mark_human_reviewed" ? `<div class="btn-row" style="margin-top:8px"><button class="btn primary" type="button" data-act="${i}">Open the sign-off sheet</button></div>` : "") +
      `</li>`).join("")}</ul>`;
    root.querySelectorAll("[data-act]").forEach((b) =>
      b.addEventListener("click", () => LAB.signOffAction(list[Number(b.dataset.act)], { onDone: () => { queue(); header(); if (S.runId) refreshGate(); } })));
  }

  /* ================= scenario explorer ================= */
  function fySeg(fys) {
    const seg = $("fy-seg");
    seg.innerHTML = fys.map((fy) => `<button type="button" data-fy="${esc(fy)}" aria-pressed="${fy === S.fy}">FY${esc(fy)}</button>`).join("");
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-fy]");
      if (!b || Number(b.dataset.fy) === S.fy) return;
      S.fy = Number(b.dataset.fy);
      seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(Number(x.dataset.fy) === S.fy)));
      loadFY();
    });
  }
  function loadFY() {
    Shell.api(`/api/market/heatmap?fy=${enc(S.fy)}`).then(heatmap).catch((e) => errInto($("chart-heatmap"), "/api/market/heatmap", e));
    Shell.api(`/api/market/rm_scatter?fy=${enc(S.fy)}`).then(rmScatter).catch((e) => errInto($("chart-rm"), "/api/market/rm_scatter", e));
  }
  const slotLabel = (slot) => { const m = (slot - 1) * 30; return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; };
  function heatmap(d) {
    const flat = [];
    d.z.forEach((row) => row.forEach((v) => isNum(v) && flat.push(v)));
    if (!flat.length) { $("heatmap-note").textContent = "No prices returned for this fiscal year."; return; }
    const sorted = flat.slice().sort((a, b) => a - b);
    const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * (sorted.length - 1)))];
    // Six bins cut at the data's own quantiles; the top bin is the hottest one per cent of slots.
    const cuts = [sorted[0], q(0.5), q(0.75), q(0.9), q(0.97), q(0.99), sorted[sorted.length - 1]];
    const colours = LAB.ramp(T.top, T.b[1], 5).concat([T.crit]);
    const pieces = colours.map((c, i) => ({ min: cuts[i], max: cuts[i + 1], color: c, label: `${txt(cuts[i], 1)} to ${txt(cuts[i + 1], 1)}` }));
    const data = [];
    d.z.forEach((row, yi) => row.forEach((v, xi) => isNum(v) && data.push([xi, yi, v])));
    $("heatmap-note").textContent = `${d.dates.length} days by ${d.slots.length} half-hour slots in ${d.unit}. Colour bins are cut at this year's own price quantiles, and the legend prints each bin's range; the top bin is the hottest slots of the year. Source: ${[].concat(d.source).join(", ")}.`;
    chart("chart-heatmap", {
      grid: grid({ left: 70, right: 12, top: 12, bottom: 96 }),
      tooltip: { trigger: "item", confine: true, formatter: (p) => `${esc(d.dates[p.value[1]])}<br>slot ${esc(d.slots[p.value[0]])}, from ${esc(slotLabel(d.slots[p.value[0]]))}<br><b>${esc(txt(p.value[2], 2))} ${esc(d.unit)}</b>` },
      xAxis: { type: "category", data: d.slots.map(slotLabel), splitLine: { show: false }, axisLabel: { interval: 5 }, name: "half-hour slot start, JST", nameLocation: "middle", nameGap: 26 },
      yAxis: { type: "category", data: d.dates, inverse: true, splitLine: { show: false }, axisLabel: { interval: (i, v) => String(v).endsWith("-01"), formatter: (v) => String(v).slice(0, 7) } },
      visualMap: { type: "piecewise", dimension: 2, pieces, orient: "horizontal", left: "center", bottom: 0, itemWidth: 14, itemHeight: 10, itemGap: 8, textStyle: { color: T.muted, fontFamily: T.mono, fontSize: 10 } },
      series: [{ type: "heatmap", name: `Tokyo price FY${d.fiscal_year}`, data, progressive: 6000, emphasis: { itemStyle: { borderColor: T.fg, borderWidth: 1 } } }],
    });
  }
  function duration(d) {
    const keys = Object.keys(d.series || {}).sort();
    const types = ["solid", "dashed", "dotted"];
    $("duration-note").textContent = `Share of half-hours at or above each price, per fiscal year. Source: ${[].concat(d.source).join(", ")}.`;
    chart("chart-duration", {
      grid: grid({ top: 40, left: 56 }),
      legend: { top: 0, right: 0 },
      tooltip: { trigger: "axis", confine: true, formatter: (ps) => `${esc(txt(ps[0].value[0], 1))}% of hours exceeded<br>` + ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${esc(txt(p.value[1], 2))} ${esc(d.unit)}`).join("<br>") },
      xAxis: { type: "value", min: 0, max: 100, name: d.x, nameLocation: "middle", nameGap: 28, axisLabel: { formatter: (v) => `${v}%` } },
      yAxis: { type: "value", name: d.unit, nameLocation: "end" },
      series: keys.map((k, i) => ({ name: `FY${k}`, type: "line", showSymbol: false, data: d.series[k], lineStyle: { width: 1.75, type: types[i % 3], color: T.b[[0, 5, 3][i % 3]] }, itemStyle: { color: T.b[[0, 5, 3][i % 3]] } })),
    });
  }
  function kinks(curve) {
    const out = [];
    for (let i = 1; i < curve.length - 1; i++) {
      const [x0, y0] = curve[i - 1], [x1, y1] = curve[i], [x2, y2] = curve[i + 1];
      const s1 = (y1 - y0) / (x1 - x0), s2 = (y2 - y1) / (x2 - x1);
      if (Math.abs(s1 - s2) > 1e-6 * Math.max(1, Math.abs(s1), Math.abs(s2))) out.push(curve[i]);
    }
    return out;
  }
  function rmScatter(d) {
    const curve = d.curve || [];
    const ks = kinks(curve);
    const xMax = Math.max(...curve.map((p) => p[0]), 0) * 2;
    const beyond = (d.points || []).filter((p) => p[0] > xMax).length;
    $("rm-note").textContent = `${(d.points || []).length} slots in FY${d.fiscal_year}: every tight-margin slot plus one evening slot a day. ${beyond} high-margin slots sit to the right of this view. ` +
      `The line is the regulatory scarcity price curve; its corners are marked. Source: ${[].concat(d.source).join(", ")}.`;
    chart("chart-rm", {
      grid: grid({ top: 40, left: 56 }),
      legend: { top: 0, right: 0, data: ["Imbalance price by slot", "Scarcity curve"] },
      tooltip: { trigger: "item", confine: true, formatter: (p) => p.seriesName === "Scarcity curve" ? `Scarcity curve<br>margin ${esc(txt(p.value[0], 1))}%, ${esc(txt(p.value[1], 1))} JPY/kWh` : `Reserve margin ${esc(txt(p.value[0], 2))}%<br>imbalance ${esc(txt(p.value[1], 2))} JPY/kWh<br>spot ${esc(txt(p.value[2], 2))} JPY/kWh` },
      xAxis: { type: "value", min: 0, max: xMax || "dataMax", name: "reserve margin, %", nameLocation: "middle", nameGap: 28 },
      yAxis: { type: "value", min: 0, name: "JPY/kWh", nameLocation: "end" },
      series: [
        { name: "Imbalance price by slot", type: "scatter", symbolSize: 4, clip: true, data: d.points, itemStyle: { color: T.b[0], opacity: 0.5 } },
        { name: "Scarcity curve", type: "line", showSymbol: false, symbol: "rect", clip: true, data: curve, lineStyle: { color: T.warn, width: 1.75 }, itemStyle: { color: T.warn },
          markPoint: { symbol: "rect", symbolSize: 7, itemStyle: { color: T.warn }, label: { show: true, position: "right", color: T.fg, fontFamily: T.mono, fontSize: 10, formatter: (p) => p.name },
            data: ks.map((pt) => ({ name: `${txt(pt[1], 0)} at ${txt(pt[0], 1)}%`, coord: pt })) } },
      ],
    });
  }
  function portfolio(p) {
    const segs = (p.by_segment || []).slice().sort((a, b) => b.annual_twh - a.annual_twh);
    const tot = p.portfolio_total || {};
    const ordered = segs.slice().reverse();
    chart("chart-portfolio", {
      grid: grid({ left: 118, right: 64, top: 8, bottom: 28 }),
      tooltip: { trigger: "item", confine: true, formatter: (x) => `${esc(x.name)}<br>${esc(txt(x.value, 3))} TWh a year` },
      xAxis: { type: "value", name: "TWh a year", nameLocation: "middle", nameGap: 22 },
      yAxis: { type: "category", data: ordered.map((s) => s.segment), splitLine: { show: false } },
      series: [{ type: "bar", data: ordered.map((s) => s.annual_twh), barMaxWidth: 12, itemStyle: { color: T.b[2] }, label: { show: true, position: "right", color: T.muted, fontFamily: T.mono, fontSize: 10, formatter: (x) => txt(x.value, 3) } }],
    });
    $("portfolio-table").innerHTML =
      `<div class="table-scroll"><table class="data"><thead><tr><th>Segment</th><th class="num">Customers</th><th class="num">TWh a year</th><th class="num">Load factor</th><th class="num">DR, MW</th></tr></thead><tbody>` +
      segs.map((s) => `<tr><td class="mono rid">${esc(s.segment)}</td><td class="num">${t(s.customers, "", 0)}</td><td class="num">${t(s.annual_twh, "", 3)}</td><td class="num">${t(s.avg_load_factor * 100, "%", 1)}</td><td class="num">${t(s.dr_potential_mw, "", 2)}</td></tr>`).join("") +
      `<tr><td><b>Total</b></td><td class="num">${t(tot.customers, "", 0)}</td><td class="num">${t(tot.annual_twh, "", 3)}</td><td></td><td></td></tr></tbody></table></div>` +
      `<p class="cap-note">${esc(p.note || "")}. Source: ${esc([].concat(p.source).join(", "))}.</p>`;
  }
  const COST_BADGE = { VERIFIED: "b-ok", ESTIMATE: "b-warn", DERIVED: "b-info", "LAB-ASSUMPTION": "b-idle" };
  async function costStack() {
    const v = S.costV;
    let d;
    try { d = await Shell.api(`/api/cost_stack?voltage=${enc(v)}`); } catch (e) { return errInto($("cost-body"), "/api/cost_stack", e); }
    if (v !== S.costV) return;
    const comps = d.components || [];
    const tally = {};
    comps.forEach((c) => (tally[c.status] = (tally[c.status] || 0) + 1));
    const ex = d.worked_example || {};
    $("cost-body").innerHTML =
      `<div class="chips" style="margin-bottom:10px">${Object.entries(tally).map(([k, n]) => `${badge(k, COST_BADGE[k] || "b-idle")}<span class="mono small">${esc(txt(n, 0))}</span>`).join(" ")}</div>` +
      `<div class="table-scroll" style="max-height:340px;overflow-y:auto"><table class="data"><thead><tr><th>Component</th><th class="num">Value</th><th>Unit</th><th>Status</th><th>Source</th></tr></thead><tbody>` +
      comps.map((c) => `<tr><td class="mono rid">${esc(c.component)}<span class="lbl">${esc(c.voltage)} · ${esc(c.period)}</span></td><td class="num">${t(c.value, "")}</td><td class="small">${esc(c.unit)}</td><td>${badge(c.status, COST_BADGE[c.status] || "b-idle")}</td><td class="small">${esc(c.source)}</td></tr>`).join("") +
      `</tbody></table></div><div class="card-cap" style="margin-top:14px">Worked example, ${esc(d.voltage)}</div>` +
      `<dl class="kv">${Object.entries(ex).map(([k, val]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${isNum(val) ? esc(txt(val)) : esc(val)}</dd>`).join("")}</dl>` +
      (d.pass_through ? `<p class="cap-note">Pass-through: ${esc(d.pass_through)}</p>` : "");
  }
  function calibration() {
    const d = S.cal;
    if (!d) return;
    const rows = (d.rows || []).slice();
    const abs = (r) => (isNum(r.rel_error_pct) ? Math.abs(r.rel_error_pct) : -1);
    const worst = rows.reduce((m, r) => (m === null || abs(r) > abs(m) ? r : m), null);
    const statuses = [...new Set(rows.map((r) => r.status))];
    $("cal-summary").innerHTML =
      `${esc(txt(rows.length, 0))} statistics compared with their published targets; server status: ${esc(statuses.join(", "))}. ` +
      (worst ? `The largest relative error is ${st(worst.rel_error_pct, "%", 2)} on <span class="mono">${esc(worst.metric)}</span>, FY${esc(worst.fiscal_year)}.` : "");
    const shown = S.calSorted ? rows.sort((a, b) => abs(b) - abs(a)) : rows;
    const digits = (v) => (Math.abs(v) >= 100 ? 1 : Math.abs(v) >= 1 ? 3 : 4);
    $("cal-table").innerHTML =
      `<div class="table-scroll" style="max-height:420px;overflow-y:auto"><table class="data"><thead><tr><th>FY</th><th>Metric</th><th class="num">Synthetic</th><th class="num">Target</th><th class="num">Relative error</th><th>Published section</th><th>Status</th></tr></thead><tbody>` +
      shown.map((r) => `<tr><td class="mono">FY${esc(r.fiscal_year)}</td><td class="mono rid">${esc(r.metric)}</td><td class="num">${t(r.synthetic, "", isNum(r.synthetic) ? digits(r.synthetic) : 1)}</td>` +
        `<td class="num">${t(r.target, "", isNum(r.target) ? digits(r.target) : 1)}</td><td class="num">${st(r.rel_error_pct, "%", 2)}</td><td class="small">${esc(r.market_facts_section)}</td><td>${esc(r.status)}</td></tr>`).join("") +
      `</tbody></table></div><p class="cap-note">Source: ${esc([].concat(d.source).join(", "))}.</p>`;
  }

  /* ================= wiring ================= */
  $("run-select").addEventListener("change", (e) => { S.runId = e.target.value; S.programId = null; S.pinned = false; loadRun(); });
  $("program-select").addEventListener("change", (e) => { S.pinned = true; loadDiff(e.target.value); });
  $("holdout-mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b) return;
    S.holdoutMode = b.dataset.mode;
    $("holdout-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    holdout();
  });
  $("cost-seg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b || b.dataset.v === S.costV) return;
    S.costV = b.dataset.v;
    $("cost-seg").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    costStack();
  });
  $("cal-filter").textContent = "Largest error first";
  $("cal-filter").addEventListener("click", (e) => { S.calSorted = !S.calSorted; e.currentTarget.setAttribute("aria-pressed", String(S.calSorted)); calibration(); });

  /** While any run is in flight, refresh every POLL_MS; stop once nothing is running. */
  async function poll() {
    let runs;
    try { runs = (await Shell.api("/api/runs")).runs || []; } catch (e) { $("poll-status").textContent = `Refresh failed: ${e.message}.`; return; }
    const running = runs.filter((r) => r.status === "running");
    const stamp = new Date().toISOString().slice(11, 19);
    $("poll-status").textContent = running.length ? `${plural(running.length, "run", "runs")} in progress. Refreshed ${stamp} UTC; the list refreshes itself until it finishes.` : `No run in progress. Last checked ${stamp} UTC.`;
    if (running.length) {
      await loadRuns();
      clearTimeout(S.poll);
      S.poll = setTimeout(poll, POLL_MS);
    }
  }

  const { ov, runs } = await header();
  try { S.ledger = await Shell.api("/api/ledger"); } catch (e) { S.ledger = null; }
  const problems = [...new Set(runs.map((r) => r.problem))].sort((a, b) => (a === "tariff_pricing" ? -1 : b === "tariff_pricing" ? 1 : a.localeCompare(b)));
  if (problems.length) tabs(problems);
  else $("run-header").innerHTML = `<p class="muted">No runs recorded yet.</p>`;
  queue();
  const fys = ((ov && ov.tokyo_mean_by_fy) || []).map((r) => r.fiscal_year);
  S.fy = fys[fys.length - 1] || null;
  fySeg(fys);
  if (S.fy) loadFY();
  Shell.api("/api/market/duration").then(duration).catch((e) => errInto($("chart-duration"), "/api/market/duration", e));
  Shell.api("/api/portfolio").then(portfolio).catch((e) => errInto($("portfolio-table"), "/api/portfolio", e));
  costStack();
  Shell.api("/api/calibration").then((d) => { S.cal = d; calibration(); }).catch((e) => errInto($("cal-table"), "/api/calibration", e));
  poll();

  $("prov").innerHTML =
    Shell.technicalDrawer(
      `<p class="small">Run evidence is read from the run files as the controller writes them, including runs still in flight. ` +
        `Status words for finished runs come from /api/v2/proof; the v1 run list does not carry them.</p>`,
      "where each panel reads from"
    ) +
    footer([
      ["Runs", `<span class="mono">/api/runs, /api/runs/{id}, /catches, /holdout, /gate, /diff, /api/ledger</span>`],
      ["Status labels", `<span class="mono">/api/v2/proof</span>`],
      ["Market", `<span class="mono">/api/market/heatmap, /duration, /rm_scatter, /api/portfolio, /api/cost_stack, /api/calibration</span>`],
      ["Provenance", provTag(S.provenance)],
    ]);
  Motion.reveal();
})();
