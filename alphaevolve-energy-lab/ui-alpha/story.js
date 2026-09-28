/* Screen 3: the 09:00 run, told beat by beat. Words in story.json; figures from /api/alpha/run. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => LAB.esc(s), t = (s) => LAB.t(s);
  let S, R, cur = 0, opt = null, cues = false;

  const beatList = () => opt.beats.map((k) => ({ key: k, ...S.beats[k] }));

  function findings(b) {
    if (!b.findings) return "";
    return `<div class="mo-findings">${b.findings.map((x) => {
      if (x.delta) return `<div class="mo-finding">${LAB.delta((R.holdout || {}).delta)}<div class="fl">${esc(x.label)}</div></div>`;
      const v = LAB.F[x.fig];
      return `<div class="mo-finding"><div class="fv${x.tone ? " " + x.tone : ""}${x.mono ? " mono" : ""}">${v === undefined ? LAB.NITD : esc(v)}${x.unit ? `<span class="t-unit">${esc(x.unit)}</span>` : ""}</div><div class="fl">${t(esc(x.label))}</div></div>`;
    }).join("")}</div>`;
  }
  const pills = (b) => b.agents ? `<div class="mo-pills">${b.agents.map((a) => `<span class="mo-pill ${a.kind || ""}" data-agent="${esc(a.id)}"><span class="st"></span>${esc(a.name)}</span>`).join("")}</div>` : "";
  const produced = (b) => LAB.techDrawer(`<div class="kv-card"><div class="kv-row"><span class="kv-key">Run</span><span class="kv-val">${esc(R.run.run_id)} · ${esc(R.run.status_label)}</span></div><div class="kv-row"><span class="kv-key">Evaluator</span><span class="kv-val">${esc(R.run.evaluator_version)}</span></div><div class="kv-row"><span class="kv-key">Figures</span><span class="kv-val">/api/alpha/run (runs/*.json, lab_holdout, lab_segment_judgments)</span></div><div class="kv-row"><span class="kv-key">Provenance</span><span class="kv-val">${esc(R.run.provenance)}</span></div>${b.note ? `<div class="kv-row"><span class="kv-key">Note</span><span class="kv-val">${esc(b.note)}</span></div>` : ""}</div>`, "how this was produced");

  function stage(b) {
    const st = $("mo-stage"); st.className = "mo-stage " + b.key + (b.key === "holdout" ? " turn" : "");
    let body = "";
    if (b.key === "caught" && b.quote_fig) body += `<div class="quote"><b>the rule, in the evaluator's words:</b> ${esc(LAB.F[b.quote_fig] || "")}</div>`;
    if (b.key === "contrast") body += contrast(b);
    if (b.key === "options") body += options();
    if (b.key === "decide") body += decide(b);
    if (b.key === "map") body += map();
    if (b.key === "analyst") body += `<div id="mo-ask"></div>`;
    st.innerHTML = `<div class="mo-kicker">${esc(b.kicker)}${b.clock ? ` <span class="mo-clock">· ${esc(b.clock)}</span>` : ""}</div><h2>${t(esc(b.title))}</h2>
      ${cues && b.cue ? `<div class="cue">Presenter: ${esc(b.cue)}</div>` : ""}
      ${(b.lines || []).map((l, i) => `<p class="${i ? "" : "first"}">${t(esc(l))}</p>`).join("")}${pills(b)}${findings(b)}${body}
      ${b.note ? `<div class="mo-note">${esc(b.note)} · ${esc(R.run.provenance)}</div>` : ""}${produced(b)}
      <div class="mo-nav"><button class="btn" id="mo-prev" ${cur === 0 ? "disabled" : ""}>Previous</button><span class="cite">${cur + 1} of ${beatList().length}</span><button class="btn btn-primary" id="mo-next" ${cur === beatList().length - 1 ? "disabled" : ""}>Next</button></div>`;
    $("mo-prev").onclick = () => go(cur - 1); $("mo-next").onclick = () => go(cur + 1);
    st.querySelectorAll(".mo-pill").forEach((p, i) => setTimeout(() => { p.classList.add("done"); }, 350 + i * 250));
    if (b.key === "analyst") liveBeat(b);
    if (b.key === "decide") wireHold(b);
  }

  function contrast(b) {
    const today = (R.earlier_runs || []).map((e) => `<div class="mo-row hit"><span class="mo-clock">run ${esc(String(e.ordinal))}</span><span><b>${esc(e.status_label)}</b> · ${esc(e.why || "the champion broke a customer rule on unseen customers")}<span class="sub">${esc(e.run_id)} · raw delta before the rules ${esc(LAB.signed(e.raw_delta))} JPY M, not citable</span></span></div>`).join("");
    const after = b.after_rows.map((r) => `<div class="mo-row win"><span class="mo-clock">${esc(r.clock)}</span><span>${t(esc(r.text))}</span></div>`).join("");
    return `<div class="mo-contrast"><div class="mo-col today"><h4>${esc(b.today_head)}<span class="badge badge-critical">${LAB.f((R.earlier_runs || []).length)} runs</span></h4>${today || `<div class="mo-row">${LAB.NITD}</div>`}</div>
      <div class="mo-col"><h4>${esc(b.after_head)}<span class="badge badge-optimal">run ${esc(String(R.run.ordinal))}</span></h4>${after}<div class="mo-row win"><span class="mo-clock">result</span><span>${LAB.delta(R.holdout.delta)}</span></div></div></div>`;
  }

  function options() {
    const cards = (R.options || []).map((o) => {
      const cls = o.kind === "caught" ? "crit struck" : o.kind === "champion" ? "warn" : "ok";
      const dl = [["train", `${LAB.f(o.train)} JPY M`, o.train_label], ["unseen", o.holdout === null || o.holdout === undefined ? (o.kind === "caught" ? "never judged: struck before scoring" : LAB.NITD) : `${LAB.f(o.holdout)} JPY M`, "holdout score"]];
      return `<div class="mo-option ${cls}" ${o.struck ? `data-struck="${esc(o.struck)}"` : ""}><div class="mo-option-id">${esc(o.id)}</div><h4>${esc(o.name)}</h4><dl>${dl.map(([k, v, l]) => `<dt>${esc(k)}</dt><dd><span class="mono">${v}</span> <span class="cite">${esc(l || "")}</span></dd>`).join("")}</dl>
        ${o.delta ? `<div style="margin-top:8px">${LAB.delta(o.delta, { prov: false })}</div>` : ""}${o.reason ? `<div class="quote" style="margin:8px 0 0"><b>reason:</b> ${esc(o.reason)}</div>` : o.note ? `<div class="cite" style="display:block;margin-top:6px">${esc(o.note)}</div>` : ""}</div>`;
    }).join("");
    return `<div class="mo-opts">${cards || LAB.NITD}</div>`;
  }

  function decide(b) {
    const g = R.gate || {}, un = R.unsettled || [];
    return `<div class="mo-decide"><div class="mo-box unsettled"><div class="lab">What it could not settle</div>${un.length ? `<ul style="margin-left:16px;font-size:13px">${un.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>` : `<p>Nothing open.</p>`}<p class="cite" style="margin-top:8px">${esc(R.run.provenance)}</p></div>
      <div class="mo-box"><div class="lab">The analyst's case</div><p>Champion ${esc(R.champion.id)}: ${LAB.f(R.champion.train)} JPY M on train, ${LAB.f(R.holdout.best_holdout)} JPY M on unseen customers.</p><div style="margin-top:8px">${LAB.delta(R.holdout.delta)}</div></div></div>
      <div class="kv-card" style="margin-bottom:12px">${(g.checks || []).map((c) => `<div class="kv-row"><span class="kv-key">${esc(c.label)}</span><span class="kv-val"><span class="badge ${c.ok ? "badge-optimal" : "badge-critical"}">${c.ok ? "PASS" : "BLOCKED"}</span></span></div>`).join("")}</div>
      <div><button class="mo-hold" id="mo-hold" type="button"><span class="txt">${esc(b.hold.label)}</span></button><span class="mo-promote"><button class="btn" disabled>Promote to production</button><span class="why">${esc(g.promotion_control || "disabled")}</span></span></div>
      <div class="mo-released" id="mo-released"><div class="lab">${esc(b.hold.done)}</div><div class="mo-audit" id="mo-audit"></div></div>`;
  }

  function wireHold(b) {
    const btn = $("mo-hold"); if (!btn) return;
    Alpha.hold(btn, async () => {
      btn.querySelector(".txt").textContent = b.hold.done;
      const rel = $("mo-released"), out = $("mo-audit");
      try {
        const r = await fetch(`/api/runs/${encodeURIComponent(R.run.run_id)}/review`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ program_id: R.champion.id, reviewer: b.hold.reviewer, note: b.hold.note }) });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
        const gate = j.gate || {};
        out.innerHTML = `<div>Recorded: ${esc(j.review.reviewer)} read ${esc(j.review.program_id)} at ${esc(j.review.at || j.review.reviewed_at || "")}.</div><div style="margin-top:6px">Gate after the review: ${(gate.checks || []).map((c) => `<span class="badge ${c.ok ? "badge-optimal" : "badge-critical"}" style="margin:2px 4px 2px 0">${esc(c.id)} ${c.ok ? "PASS" : "BLOCKED"}</span>`).join("")}</div><div class="cite" style="margin-top:6px">promotion_allowed ${gate.promotion_allowed === undefined ? "not returned" : String(gate.promotion_allowed)} · ${esc(R.run.provenance)}</div><pre>${esc(JSON.stringify(j.review, null, 1))}</pre>`;
      } catch (e) {
        out.innerHTML = `<div class="ask-err"><b>THE REVIEW WAS NOT RECORDED</b>${esc(e.message)}</div>`;
        btn.classList.remove("done"); btn.querySelector(".txt").textContent = b.hold.label;
      }
      rel.classList.add("on");
    });
  }

  function map() {
    const m = (R.holdout || {}).metrics || {}, s = m.seed || {}, c = m.champion || {};
    const tile = (title, a, b2, unit, dp, tone) => `<div class="mo-node ${tone}"><div class="t">${esc(title)}</div><div class="v">${LAB.f(a, dp)} <span class="cite">→</span> ${LAB.f(b2, dp)}<span class="t-unit">${esc(unit)}</span></div><div class="cite">seed → champion, unseen customers</div></div>`;
    return `<div class="mo-map"><div class="mo-node ok"><div class="t">The citable uplift</div><div style="margin-top:6px">${LAB.delta(R.holdout.delta)}</div></div>
      ${tile("Tail loss, worst five percent (CVaR95)", s.cvar95_shortfall_jpy_m, c.cvar95_shortfall_jpy_m, "JPY M", 0, "ok")}
      ${tile("Expected margin", s.expected_margin_jpy_m, c.expected_margin_jpy_m, "JPY M", 0, "")}
      ${tile("Portfolio churn", (s.churn_count || 0) * 100, (c.churn_count || 0) * 100, "%", 1, "crit")}</div>
      <div class="cite">Cost of this search USD ${LAB.f(R.run.cost_usd, 2)} · ${LAB.f(R.run.programs)} programs in ${LAB.F.wall_min} minutes · ${esc(R.run.provenance)}</div>`;
  }

  function liveBeat(b) {
    const host = $("mo-ask"); if (!host) return;
    const pillEl = (id) => $("mo-stage").querySelector(`.mo-pill[data-agent="${id}"]`);
    const map2 = { lead: "analyst", tools: "tools", reviewer: "reviewer", signoff: "signoff" };
    $("mo-stage").querySelectorAll(".mo-pill").forEach((p) => p.classList.remove("done"));
    LAB.ask(host, t(b.question), { replayId: b.replay_id, pills: (id, st) => { const p = pillEl(map2[id]); if (p) { p.classList.remove("working", "done"); if (st) p.classList.add(st); } } });
  }

  function rail() {
    const list = beatList();
    $("mo-beats").innerHTML = list.map((b, i) => `<button class="mo-beat${i === cur ? " active" : ""}" data-i="${i}" aria-current="${i === cur ? "step" : "false"}"><span class="mo-beat-clock">${esc(b.clock || "·")}</span><span class="mo-beat-name">${t(esc(b.title))}</span></button>`).join("");
    $("mo-beats").querySelectorAll(".mo-beat").forEach((x) => x.onclick = () => go(Number(x.dataset.i)));
  }
  function go(i) { const list = beatList(); cur = Math.max(0, Math.min(list.length - 1, i)); rail(); stage(list[cur]); $("mo-count").textContent = `${cur + 1} of ${list.length} beats`; }

  window.renderRun = function () {
    S = LAB.story.run; R = LAB.data.run; const pane = $("pane-run");
    if (!R || !R.run) { pane.innerHTML = `<div class="eyebrow top">${esc(S.eyebrow)}</div><h1 class="hero-title">${esc(S.hero)}</h1><div class="card">${LAB.NITD}</div>${LAB.disclaimer()}`; return; }
    opt = S.options[0];
    pane.innerHTML = `<div class="eyebrow top">${esc(S.eyebrow)} · ${esc(R.run.run_id)}</div><h1 class="hero-title">${esc(S.hero)}</h1>
      <div class="lede-row"><p class="hero-desc">${t(esc(S.lede))}</p>${LAB.provTag()}</div>
      <div class="mo-options" id="mo-options" role="tablist"></div>
      <div class="mo-toolbar"><label class="mo-toggle"><input type="checkbox" id="mo-cues"> Presenter cues</label><span id="mo-count"></span></div>
      <div class="mo-layout"><nav class="mo-beats" id="mo-beats" aria-label="Beats"></nav><div class="mo-stage" id="mo-stage" aria-live="polite"></div></div>${LAB.disclaimer()}`;
    const drawOpts = () => { $("mo-options").innerHTML = S.options.map((o) => `<button class="mo-opt${o.id === opt.id ? " active" : ""}" data-id="${esc(o.id)}" role="tab">${esc(o.name)}<small>${esc(o.blurb)}</small></button>`).join(""); $("mo-options").querySelectorAll(".mo-opt").forEach((x) => x.onclick = () => { opt = S.options.find((o) => o.id === x.dataset.id); cur = 0; drawOpts(); go(0); }); };
    $("mo-cues").onchange = (e) => { cues = e.target.checked; go(cur); };
    drawOpts(); go(0);
  };
})();
