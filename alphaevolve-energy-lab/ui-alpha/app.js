/* UI version alpha: the CEO story of the AlphaEvolve Energy Lab, on the same back end as versions 1 and 2.
 * Copy lives in story.json (Lane Reach); every figure is fetched from /api and poured into {{placeholders}}.
 * Screens: why · system (schematic.js) · run (story.js) · who · team · built. */
window.ALPHA = {
  product: "Energy Lab", company: "AlphaEvolve Energy Lab", avatar: "VS",
  screens: [{ id: "why", label: "Why now" }, { id: "system", label: "The system" }, { id: "run", label: "The run" },
            { id: "who", label: "Who changes" }, { id: "team", label: "The team" }, { id: "built", label: "How it's built" }],
};

(function () {
  const esc = Alpha.esc;
  const $ = (id) => document.getElementById(id);
  const LAB = { F: {}, data: {}, story: null, replays: [], liveChecks: [] };
  window.LAB = LAB;

  /* ---------- formatting ---------- */
  const num = (v, dp = 0) => (v === null || v === undefined || Number.isNaN(Number(v))) ? null
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const NITD = '<span class="gap-value">NOT IN THE DATA</span>';
  const f = (v, dp = 0) => { const n = num(v, dp); return n === null ? NITD : n; };
  const signed = (v, dp = 0) => { const n = num(Math.abs(v), dp); return n === null ? NITD : (v >= 0 ? "+" : "-") + n; };
  const t = (tpl) => String(tpl ?? "").replace(/\{\{(\w+)\}\}/g, (_, k) => (k in LAB.F ? LAB.F[k] : NITD));
  const words = (s) => String(s || "").trim().split(/\s+/).filter(Boolean).length;
  LAB.esc = esc; LAB.f = f; LAB.signed = signed; LAB.t = t; LAB.num = num; LAB.NITD = NITD;

  /** The citable tariff uplift, always with its caveat. d = {value, unit, valid, caveat, provenance}. */
  LAB.delta = (d, opts = {}) => {
    if (!d) return `<span class="tdelta" data-valid="false"><span class="v none">NOT IN THE DATA</span></span>`;
    const cls = "tdelta" + (opts.inline ? " inline" : "");
    if (!d.valid || d.value === null || d.value === undefined) {
      return `<span class="${cls}" data-valid="false"><span class="v none">NO VALIDATED UPLIFT</span>` +
        (opts.raw !== undefined && opts.raw !== null ? `<span class="cite">raw ${esc(signed(opts.raw))} ${esc(d.unit || "")} before the rules · not citable</span>` : "") + `</span>`;
    }
    const cav = d.caveat ? `<span class="caveat"><b>CAVEAT</b><span>${esc(d.caveat)}</span></span>` : (d.selection_note ? `<span class="cite">${esc(d.selection_note)}</span>` : "");
    return `<span class="${cls}" data-valid="true" data-caveat="${d.caveat ? "1" : "0"}"><span class="v">${esc(signed(d.value))}<span class="t-unit">${esc(d.unit || "")}</span></span>${cav}` +
      (opts.prov === false ? "" : `<span class="cite">${esc(d.provenance || LAB.story.provenance)}</span>`) + `</span>`;
  };

  /** Markdown-lite for analyst text: escape first, then bold, code, bullets, paragraphs, and [table] cites. */
  LAB.md = (text) => {
    const lines = esc(text || "").split("\n");
    let out = "", inList = false;
    for (const raw of lines) {
      let l = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\[([a-z_]+\.[a-z_0-9]+(?:, [a-z_]+\.[a-z_0-9]+)*)\]/g, '<span class="cite">[$1]</span>');
      const m = l.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
      if (m) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${m[1]}</li>`; continue; }
      if (inList) { out += "</ul>"; inList = false; }
      l = l.replace(/^#+\s*/, "").replace(/^---+$/, "");
      if (l.trim()) out += `<p>${l}</p>`;
    }
    if (inList) out += "</ul>";
    return out;
  };

  LAB.sparkline = (values, w = 220, h = 34) => {
    const v = (values || []).filter((x) => typeof x === "number" && Number.isFinite(x));
    if (v.length < 2) return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" aria-hidden="true"></svg>`;
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = v.map((x, i) => [(i / (v.length - 1)) * (w - 2) + 1, h - 2 - ((x - lo) / span) * (h - 6)]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path class="area" d="${d} L${w - 1} ${h - 1} L1 ${h - 1} Z"/><path d="${d}"/></svg>`;
  };

  LAB.rangebar = (lo, hi, min, max, site, tone = "") => {
    if ([lo, hi, min, max].some((x) => x === null || x === undefined)) return "";
    const span = max - min || 1, l = ((lo - min) / span) * 100, r = ((hi - min) / span) * 100;
    const s = site === null || site === undefined ? "" : `<span class="site" style="left:${Math.min(99, Math.max(0, ((site - min) / span) * 100))}%"></span>`;
    return `<div class="rbar"><span class="fill ${tone}" style="left:${l.toFixed(1)}%;width:${Math.max(1.5, r - l).toFixed(1)}%"></span>${s}</div>`;
  };

  LAB.techDrawer = (html, hint = "for the engineer in the room") =>
    `<details class="drawer"><summary>Technical detail<span class="hint">${esc(hint)}</span></summary><div class="body">${html}</div></details>`;
  LAB.disclaimer = () => `<div class="disclaimer">${esc(LAB.story.disclaimer)}</div>`;
  LAB.provTag = () => `<span class="prov-tag">${esc(LAB.story.provenance)}</span>`;

  /* ---------- the live analyst stream (with a badged replay fallback) ---------- */
  const PILLS = [{ id: "lead", name: "The analyst", cls: "lead" }, { id: "tools", name: "Read-only tools", cls: "" },
                 { id: "reviewer", name: "Evidence rules", cls: "critic" }, { id: "signoff", name: "Your sign-off", cls: "" }];
  /** Render the panel and start the stream. opts: {replayId, pills(el), label, session}. Returns the panel element. */
  LAB.ask = (host, question, opts = {}) => {
    const el = document.createElement("div"); el.className = "ask";
    el.innerHTML = `<div class="ask-head"><div class="ask-q">${esc(question)}</div><span class="badge badge-live" data-state="live">LIVE · asking</span></div>
      <div class="ask-body"><div class="mo-pills">${PILLS.map((p) => `<span class="mo-pill ${p.cls}" data-pill="${p.id}"><span class="st"></span>${esc(p.name)}</span>`).join("")}</div>
        <div class="ask-tools"></div><div class="ask-text"></div></div>
      <div class="ask-foot"><span class="ask-src">POST /api/chat · server-sent events · the analyst reads only the lab tables</span><span class="ask-lat"></span></div>`;
    host.innerHTML = ""; host.appendChild(el);
    const badge = el.querySelector(".badge"), tools = el.querySelector(".ask-tools"), text = el.querySelector(".ask-text"), lat = el.querySelector(".ask-lat");
    const pill = (id, st) => { const p = el.querySelector(`[data-pill="${id}"]`); if (p) { p.classList.remove("working", "done"); if (st) p.classList.add(st); } if (opts.pills) opts.pills(id, st); };
    const t0 = performance.now(); let chunks = "", gotFinal = false, calls = 0;
    const onEvent = (e) => {
      if (e.type === "session") pill("lead", "working");
      else if (e.type === "tool_call") { calls++; pill("lead", "done"); pill("tools", "working"); tools.insertAdjacentHTML("beforeend", `<span class="ask-tool" data-tool="${esc(e.tool)}">${esc(e.tool)}</span>`); }
      else if (e.type === "tool_result") { const c = [...tools.querySelectorAll(`[data-tool="${CSS.escape(e.tool)}"]`)].find((x) => !x.classList.contains("done")); if (c) c.classList.add("done"); }
      else if (e.type === "text") { pill("tools", "done"); pill("reviewer", "working"); chunks += e.text; text.innerHTML = LAB.md(chunks); }
      else if (e.type === "pending_action") { pill("signoff", "working"); text.insertAdjacentHTML("beforeend", `<div class="note-box"><div class="lab">Proposal, pending your hold</div><div class="txt">${esc(e.action.summary || e.action.kind)}</div></div>`); }
      else if (e.type === "final") { gotFinal = true; pill("reviewer", "done"); pill("signoff", chunks ? "done" : ""); }
      else if (e.type === "error") throw new Error(e.error || "model call failed");
    };
    const fail = (err) => {
      badge.className = "badge badge-error"; badge.dataset.state = "error"; badge.textContent = "ERROR · the model call failed";
      pill("lead", ""); pill("tools", ""); pill("reviewer", ""); pill("signoff", "");
      text.insertAdjacentHTML("afterbegin", `<div class="ask-err"><b>THE MODEL CALL FAILED</b>${esc(String(err && err.message || err))}</div>`);
      const rp = LAB.replays.find((r) => r.id === opts.replayId) || LAB.replays.find((r) => r.question === question);
      if (rp) {
        badge.insertAdjacentHTML("afterend", `<span class="badge badge-replay" data-state="replay">REPLAY · recorded answer, not a live call</span>`);
        rp.tools.forEach((tn) => tools.insertAdjacentHTML("beforeend", `<span class="ask-tool done" data-tool="${esc(tn)}">${esc(tn)}</span>`));
        text.insertAdjacentHTML("beforeend", `<div class="note-box crit"><div class="lab">Replay</div><div class="txt">Recorded in ${esc(rp.recorded_in)} · latency then ${esc(String(rp.latency_s))} s · label ${esc(rp.label)}</div></div>` + LAB.md(rp.reply));
      }
      if (LAB.liveChecks.length) text.insertAdjacentHTML("beforeend", `<div class="ask-checks"><b>Live checks to run later, once credentials are back:</b><ul>${LAB.liveChecks.map((c) => `<li>${esc(c.what)}</li>`).join("")}</ul></div>`);
    };
    Alpha.stream("/api/chat", question, onEvent, opts.session).then(() => {
      if (!gotFinal || !chunks) throw new Error("the stream ended without a final answer");
      badge.textContent = `LIVE · ${calls} tool call${calls === 1 ? "" : "s"} · answered`; lat.textContent = `${((performance.now() - t0) / 1000).toFixed(1)} s`;
    }).catch(fail);
    return el;
  };
  /** Open the drawer with a live question (used by "Ask it" chips on several screens). */
  LAB.askInDrawer = (title, question, replayId) => { const body = Alpha.drawer.open(title, "", "Ask the analyst · live"); LAB.ask(body, question, { replayId }); };

  /* ---------- data ---------- */
  async function load(path) { try { return await Alpha.api(path); } catch (e) { console.warn(path, e.message); return null; } }
  async function boot() {
    const [story, landing, monthly, prize, twin, run, team, replays, personas, teams, solution, proof, health, ledger] = await Promise.all([
      load("/story.json"), load("/api/v2/landing"), load("/api/market/monthly"), load("/api/v2/prize"), load("/api/alpha/twin"),
      load("/api/alpha/run"), load("/api/alpha/team"), load("/api/alpha/replays"), load("/api/v2/personas"), load("/api/v2/teams"),
      load("/api/v2/solution"), load("/api/v2/proof"), load("/api/health"), load("/api/ledger")]);
    if (!story) { document.body.insertAdjacentHTML("afterbegin", '<div class="ask-err">story.json did not load</div>'); return; }
    LAB.story = story; Object.assign(LAB.data, { landing, monthly, prize, twin, run, team, replays, personas, teams, solution, proof, health, ledger });
    LAB.replays = (replays && replays.replays) || []; LAB.liveChecks = (replays && replays.live_checks) || [];
    figures();
    Alpha.mount();
    renderWhy(); if (window.renderSystem) window.renderSystem(); if (window.renderRun) window.renderRun(); renderWho(); renderTeam(); renderBuilt();
    document.addEventListener("alpha:screen", (e) => { if (e.detail.id === "built") Alpha.play($("arch-stack")); if (e.detail.id === "system" && window.relinkTwin) window.relinkTwin(); });
    if (location.hash === "#built") Alpha.play($("arch-stack"));
  }

  function figures() {
    const F = LAB.F, D = LAB.data;
    const hero = (D.landing || {}).hero || {}, rows = (D.landing || {}).gap_rows || [];
    const row = (id) => rows.find((r) => r.id === id) || {};
    const tm = (D.team || {}).agents || {}, tv = (D.team || {}).value || {};
    F.fy2025_mean = f(hero.fy2025_tokyo_mean, 2); F.fy2026_mean = f(hero.fy2026_regime_mean, 2);
    F.regime_pct = hero.fy2025_tokyo_mean && hero.fy2026_regime_mean ? f((hero.fy2026_regime_mean / hero.fy2025_tokyo_mean - 1) * 100, 0) : NITD;
    F.seed_cvar = f((row("tariff_tail_risk").ordinary || {}).value); F.champion_cvar_train = f((row("tariff_tail_risk").best || {}).value);
    F.imb_caught = f(((tm.invariants || {}).by_rule || {}).intentional_imbalance ?? null);
    F.policy_caught = f((tm.invariants || {}).caught); F.reached = f((tm.invariants || {}).reached_population);
    F.tariff_failed = f((tm.holdout_judge || {}).tariff_failed); F.searched_runs = f((tm.controller || {}).runs); F.programs = f((tm.controller || {}).programs);
    const bud = (tm.controller || {}).budget || {}; F.programs_per_run = f(bud.programs_per_run); F.runs_per_day = f(bud.runs_per_day); F.programs_per_day = f(bud.programs_per_day);
    F.customers = f((tm.evaluator || {}).customers); F.scenarios = f((tm.evaluator || {}).scenarios);
    const hnode = ((D.twin || {}).nodes || []).find((n) => n.id === "holdout") || {};
    F.trading_validated = f((hnode.runs || []).filter((r) => r.problem === "jepx_trading" && r.delta.valid).length);
    const R = D.run || {};
    if (R.run) {
      const ho = R.holdout || {}, cv = R.caveat || {}, seg = (cv.segments || [])[0] || {};
      F.run_ordinal = String(R.run.ordinal); F.run_id = R.run.run_id; F.cohort = f((R.prereg || {}).cohort);
      F.scenarios_holdout = f(((R.prereg || {}).scenarios || {}).holdout); F.sha_prefix = (R.prereg || {}).instance_sha_prefix || "NOT IN THE DATA";
      F.margin_rule = `z ${(R.prereg || {}).z} · n_min ${(R.prereg || {}).n_min}`;
      F.seed_train = f((R.seed || {}).train); const fv = (R.first_candidates || []).find((c) => c.train !== null && c.train !== undefined);
      F.first_valid_train = f(fv ? fv.train : null); F.first_count = f((R.first_candidates || []).length);
      F.first_invalid = f((R.first_candidates || []).filter((c) => c.train === null || c.train === undefined).length);
      F.caught_id = (R.caught || {}).id || "NOT IN THE DATA"; F.caught_raw = f((R.caught || {}).raw_score); F.caught_insight = (R.caught || {}).insight || ""; F.caught_word = "REJECTED";
      F.champion_id = (R.champion || {}).id || "NOT IN THE DATA"; F.champion_train = f((R.champion || {}).train); F.champion_gain_train = signed((R.champion || {}).train_delta_vs_seed);
      F.lineage_steps = f((R.champion || {}).lineage_steps); F.holdout_seed = f(ho.seed); F.champion_holdout = f(ho.best_holdout); F.holdout_delta = signed((ho.delta || {}).value);
      F.fab_n = f(seg.n); F.fab_rise_pp = seg.rise !== undefined ? signed(seg.rise * 100, 1) : NITD; F.fab_point_pp = f((seg.point_rise_limit || 0) * 100, 1); F.fab_margin_pp = f((seg.margin_rise_limit || 0) * 100, 1);
      const ranks = (ho.top_k || []); const rel = ranks.filter((x) => x.relies_on_margin).map((x) => x.rank); const both = ranks.filter((x) => x.valid && !x.relies_on_margin).map((x) => x.rank);
      const rr = (a) => a.length ? (a.length > 1 && a[a.length - 1] - a[0] === a.length - 1 ? `${a[0]} to ${a[a.length - 1]}` : a.join(", ")) : "none";
      F.rank_invalid_v3 = rr(rel); F.rank_both = rr(both);
      F.programs_run = f(R.run.programs); F.valid_run = f(R.run.valid); F.cost_usd = f(R.run.cost_usd, 2); F.wall_min = f((R.run.wall_s || 0) / 60, 0);
      F.policy_caught_run = f(Object.entries(R.run.invalid_by_kind || {}).filter(([k]) => k.startsWith("policy")).reduce((a, [, v]) => a + v, 0));
      F.analyst_question = R.analyst_question || "";
      F.programs = f(R.run.programs); // the run screen's own count for its headline
    }
    F.programs = f((tm.controller || {}).programs);
    F.programs_in_run = R.run ? f(R.run.programs) : NITD;
    F.trading_low = f((tv.trading || {}).low, 1); F.trading_high = f((tv.trading || {}).high, 1);
  }

  /* ---------- screen 1: why now ---------- */
  function renderWhy() {
    const S = LAB.story.why, D = LAB.data, F = LAB.F, hero = (D.landing || {}).hero || {}, tv = (D.team || {}).value || {};
    const pane = $("pane-why");
    const fm = (r) => (r.fiscal_year || 0) * 12 + ((Number(r.month) + 8) % 12);          // fiscal order: April first
    const hist = ((D.monthly || {}).history || []).slice().sort((a, b) => fm(a) - fm(b)), banks = ((D.monthly || {}).fy2026_scenarios || []);
    pane.innerHTML = `<div class="eyebrow top">${esc(S.eyebrow)}</div><h1 class="hero-title">${esc(S.hero)}</h1>
      <div class="lede-row"><p class="hero-desc">${t(esc(S.lede))}</p>${LAB.provTag()}</div>
      <div class="section-title">${esc(S.timeline.title)}</div><p class="section-subtitle">${esc(S.timeline.subtitle)}</p>
      <div class="chart-card" id="why-chart"></div>
      <div class="section-title">${esc(S.headwinds_title)}</div><div class="headwinds-grid" id="why-headwinds"></div>
      <div class="section-title">${esc(S.levers_title)}</div><div class="levers-grid" id="why-levers"></div>
      <div class="section-title">${esc(S.outcomes_title)}</div><div class="outcomes" id="why-outcomes"></div>
      ${LAB.techDrawer(`<div class="kv-card">${[["Timeline", "/api/market/monthly: history FY2023 to FY2025, fy2026_scenarios by bank"], ["Headwinds and outcomes", "/api/v2/landing, /api/v2/prize, /api/alpha/team, /api/alpha/twin"], ["Ranges", "low and high across validated runs; a single validated tariff run is shown once, with its caveat"], ["Cites", "MARKET_FACTS sections named on each card; TRAIN ONLY figures are never citable"]].map(([k, v]) => `<div class="kv-row"><span class="kv-key">${esc(k)}</span><span class="kv-val">${esc(v)}</span></div>`).join("")}</div>`)}
      ${LAB.disclaimer()}`;
    // timeline chart: history line + FY2026 bank lines, regime marker
    const W = 960, H = 300, P = { l: 48, r: 24, t: 24, b: 36 };
    const series = [{ id: "history", name: "Tokyo spot, history", cls: "", pts: hist.map((r) => r.tokyo) }];
    const byBank = {}; banks.forEach((b) => { (byBank[b.bank] = byBank[b.bank] || []).push(b); });
    Object.entries(byBank).forEach(([bank, rows]) => series.push({ id: bank, name: `FY2026 ${bank} bank`, cls: "bank", pts: rows.slice().sort((a, b) => ((a.month + 8) % 12) - ((b.month + 8) % 12)).map((r) => r.mean_price ?? r.tokyo ?? r.mean_price_jpy_kwh) }));
    const n = hist.length, m = Math.max(...Object.values(byBank).map((r) => r.length), 0), total = n + m;
    const all = series.flatMap((s) => s.pts).filter((x) => typeof x === "number");
    const lo = 0, hi = Math.max(...all, 1) * 1.08;
    const X = (i) => P.l + (i / Math.max(total - 1, 1)) * (W - P.l - P.r), Y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b);
    const path = (pts, off) => pts.map((v, i) => (typeof v === "number" ? `${i ? "L" : "M"}${X(off + i).toFixed(1)} ${Y(v).toFixed(1)}` : "")).join(" ");
    const colours = ["var(--c1)", "var(--c2)", "var(--c3)"];
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((k) => lo + k * (hi - lo));
    const fyMarks = []; hist.forEach((r, i) => { if (r.month === 4) fyMarks.push([i, `FY${r.fiscal_year}`]); }); fyMarks.push([n, "FY2026"]);
    const cvar = (((D.landing || {}).gap_rows || []).find((r) => r.id === "tariff_tail_risk") || {}).ordinary || {};
    $("why-chart").innerHTML = `<div class="chart-legend">${series.map((s, i) => `<span class="legend-item"><span class="legend-dot" style="background:${colours[i]}"></span>${esc(s.name)}</span>`).join("")}</div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly Tokyo spot price, history and FY2026 scenario banks">
        ${yTicks.map((v) => `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="lbl" x="${P.l - 6}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end">${v.toFixed(0)}</text>`).join("")}
        <line class="axis" x1="${P.l}" x2="${W - P.r}" y1="${H - P.b}" y2="${H - P.b}"/>
        ${fyMarks.map(([i, l]) => `<line class="grid" x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${P.t}" y2="${H - P.b}"/><text class="lbl" x="${(X(i) + 4).toFixed(1)}" y="${H - P.b + 16}">${l}</text>`).join("")}
        <line x1="${X(n).toFixed(1)}" x2="${X(n).toFixed(1)}" y1="${P.t}" y2="${H - P.b}" stroke="var(--m3-critical)" stroke-width="1.5" stroke-dasharray="4 4"/>
        ${series.map((s, i) => `<path class="series ${s.cls}" stroke="${colours[i]}" d="${path(s.pts, i === 0 ? 0 : n)}"/>`).join("")}
        <text class="lbl" x="${P.l - 40}" y="14">JPY/kWh</text>
        <circle class="dot" cx="${X(n).toFixed(1)}" cy="${P.t + 10}" r="4"/><text class="marker" x="${(X(n) + 10).toFixed(1)}" y="${P.t + 14}">${esc(t(S.timeline.marker))}</text>
      </svg>`;
    // headwinds
    const bars = { regime_pct: Math.min(100, Number(String(F.regime_pct).replace(/,/g, "")) || 0),
      tail_pct: cvar.value && ((((D.landing || {}).gap_rows || []).find((r) => r.id === "tariff_tail_risk") || {}).best || {}).value ? 100 - ((((D.landing.gap_rows.find((r) => r.id === "tariff_tail_risk")).best.value) / cvar.value) * 100) : 0,
      imb_pct: (((LAB.data.team || {}).agents || {}).invariants || {}).caught ? (((((LAB.data.team || {}).agents || {}).invariants || {}).by_rule || {}).intentional_imbalance || 0) / LAB.data.team.agents.invariants.caught * 100 : 0 };
    $("why-headwinds").innerHTML = S.headwinds.map((h) => `<div class="headwind-card"><div class="headwind-header"><span>${esc(h.label)}</span><span class="cite">${esc(h.cite)}</span></div>
      <div class="headwind-val-row"><span class="headwind-val mono">${t(h.value)}</span><span class="headwind-unit">${esc(h.unit)}</span><span class="headwind-baseline">${t(esc(h.baseline))}</span></div>
      <div class="headwind-desc">${esc(h.desc)}</div><div class="bar-track"><div class="fill" style="width:${Math.max(4, Math.min(100, bars[h.bar] || 0)).toFixed(0)}%"></div></div></div>`).join("");
    $("why-levers").innerHTML = S.levers.map((l) => `<div class="lever-col${l.highlight ? " highlight" : ""}"><div class="lever-tag">${esc(l.tag)}</div><div class="lever-desc">${t(esc(l.desc))}</div>
      <div class="lever-status"><span class="${l.state === "active" ? "status-active" : "status-exhausted"}">${esc(l.state === "active" ? "ACTIVE" : "EXHAUSTED")}</span><span class="mono">${t(esc(l.status))}</span></div></div>`).join("");
    const ct = (LAB.data.twin || {}).telemetry || []; const caughtVals = (ct.find((c) => c.id === "caught") || {}).values || [];
    const ranges = { trading: [tv.trading && tv.trading.low, tv.trading && tv.trading.high, 1], tail_risk: [tv.tail_risk && tv.tail_risk.low, tv.tail_risk && tv.tail_risk.high, 0],
      caught_per_run: [caughtVals.length ? Math.min(...caughtVals) : null, caughtVals.length ? Math.max(...caughtVals) : null, 0], cost: [tv.cost_per_run && tv.cost_per_run.low, tv.cost_per_run && tv.cost_per_run.high, 2] };
    $("why-outcomes").innerHTML = S.outcomes.map((o) => { const [lo2, hi2, dp] = ranges[o.range] || []; return `<div class="outcome"><div class="outcome-label">${esc(o.label)}</div><div class="outcome-val mono">${Alpha.range(lo2, hi2, "", dp)}<span class="t-unit">${esc(o.unit)}</span></div><div class="outcome-sub">${t(esc(o.sub))}</div></div>`; }).join("");
  }

  /* ---------- screen 4: who changes ---------- */
  function renderWho() {
    const S = LAB.story.who, P = ((LAB.data.personas || {}).personas || []), pane = $("pane-who");
    pane.innerHTML = `<div class="eyebrow top">${esc(S.eyebrow)}</div><h1 class="hero-title">${esc(S.hero)}</h1><p class="hero-desc">${esc(S.lede)}</p>
      <div class="persona-strip" id="who-strip" role="tablist"></div><div id="who-body"></div>
      ${LAB.techDrawer(`<div class="kv-card"><div class="kv-row"><span class="kv-key">Personas</span><span class="kv-val">/api/v2/personas (docs/PRD.md section 4; fictional)</span></div><div class="kv-row"><span class="kv-key">Latest runs per persona</span><span class="kv-val">status label, holdout delta with caveat, provenance</span></div><div class="kv-row"><span class="kv-key">Ask it</span><span class="kv-val">POST /api/chat with the persona's first suggested question, live; replay fallback badged</span></div></div>`)}${LAB.disclaimer()}`;
    if (!P.length) { $("who-body").innerHTML = `<div class="card">${LAB.NITD}</div>`; return; }
    const initials = (n) => n.replace(/^(Ms\.|Mr\.)\s*/, "").split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
    $("who-strip").innerHTML = P.map((p, i) => `<button class="persona-tab${i ? "" : " active"}" data-id="${esc(p.id)}" role="tab"><span class="avatar">${esc(initials(p.name))}</span>${esc(p.role)}</button>`).join("");
    const show = (id) => {
      const p = P.find((x) => x.id === id) || P[0], c = S.personas[p.id] || {};
      [...$("who-strip").children].forEach((b) => b.classList.toggle("active", b.dataset.id === p.id));
      const runs = Object.values(p.latest_runs || {});
      const chips = runs.map((r) => `<span class="metric-chip">${esc(r.problem)} · ${esc(r.status_label)}</span>`).concat([`<span class="metric-chip">${esc(p.org_view)}</span>`]);
      const deltas = runs.map((r) => r.problem === "tariff_pricing"
        ? `<div class="kv-row"><span class="kv-key">Latest tariff run ${esc(r.run_id)}</span><span class="kv-val">${LAB.delta({ value: r.holdout_delta, unit: "JPY M", valid: r.uplift_valid, caveat: r.caveat, provenance: r.provenance }, { inline: true, raw: r.champion_raw_delta })}</span></div>`
        : `<div class="kv-row"><span class="kv-key">Latest trading run ${esc(r.run_id)}</span><span class="kv-val">${r.uplift_valid ? esc(signed(r.holdout_delta, 1)) + " JPY M/yr · validated on holdout" : "NO VALIDATED UPLIFT"} · ${esc(r.provenance)}</span></div>`).join("");
      $("who-body").innerHTML = `<div class="persona-identity"><div class="persona-portrait">${esc(initials(p.name))}</div><div>
          <div class="persona-title">${esc(p.name)}, ${esc(p.role)}</div><div class="persona-sub">${esc(p.governing_question)}</div><div class="persona-chip-row">${chips.join("")}</div></div></div>
        <div class="note-box"><div class="lab">Core job to be done</div><div class="txt">${esc(c.jtbd || "NOT IN THE DATA")}</div></div>
        <div class="persona-grid"><div class="reality-box today"><div class="reality-head">Today's broken reality</div><p>${esc(c.today || "")}</p></div>
          <div class="reality-box after"><div class="reality-head">With the agents</div><p>${esc(c.after || "")}</p></div></div>
        <div class="rule-title">What this role is answerable for</div><div class="kv-card">${(p.answerable_for || []).map((a) => `<div class="kv-row"><span class="kv-key">${esc(a)}</span></div>`).join("")}${deltas}</div>
        <div class="rule-title" style="margin-top:22px">Assigned squad</div><div class="squad">${S.squad.map((s) => `<div class="squad-row"><div><span class="badge-id">${esc(s.id)}</span></div><div><div class="squad-name">${esc(s.name)}</div><div class="squad-desc">${esc(s.desc)}</div></div>
          <div class="chip-row"><span class="badge badge-${esc(s.badge)}">${esc(s.badge)}</span>${s.ask ? `<button class="chip live ask-chip" data-q="${esc((p.suggested_questions || [])[0] || "")}">Ask it</button>` : ""}</div></div>`).join("")}</div>`;
      $("who-body").querySelectorAll(".ask-chip").forEach((b) => b.onclick = () => LAB.askInDrawer(`${p.role} asks the analyst`, b.dataset.q));
    };
    $("who-strip").onclick = (e) => { const b = e.target.closest(".persona-tab"); if (b) show(b.dataset.id); };
    show(P[0].id);
  }

  /* ---------- screen 5: the team ---------- */
  function renderTeam() {
    const S = LAB.story.team, T = (LAB.data.team || {}).agents || {}, V = (LAB.data.team || {}).value || {}, pane = $("pane-team");
    pane.innerHTML = `<div class="eyebrow top">${esc(S.eyebrow)}</div><h1 class="hero-title">${esc(S.hero)}</h1><p class="hero-desc">${esc(S.lede)}</p>
      <div class="eco-toolbar"><input id="team-search" class="chip" style="min-width:220px;font-weight:500" placeholder="Search the team" aria-label="Search the team">
        <div class="chip-row" id="team-filters">${[["all", "All"], ["lead", "Lead"], ["spec", "Specialists"], ["critic", "Reviewer"], ["live", "Live"]].map(([k, l], i) => `<button class="filter-chip${i ? "" : " active"}" data-k="${k}">${l}</button>`).join("")}</div></div>
      <div class="topology" id="team-topology"></div><div id="team-deepdive"></div>
      ${LAB.techDrawer(`<div class="kv-card"><div class="kv-row"><span class="kv-key">Figures</span><span class="kv-val">/api/alpha/team (evidence files, eval results, budget policy)</span></div><div class="kv-row"><span class="kv-key">Ask this agent</span><span class="kv-val">POST /api/chat, live; questions about batch agents go to the Lab Analyst, which reads their tables</span></div><div class="kv-row"><span class="kv-key">Play the recorded run</span><span class="kv-val">/api/alpha/replays: recorded eval probes, always badged as replay</span></div></div>`)}${LAB.disclaimer()}`;
    const stat = (id) => {
      const a = T[id] || {};
      if (id === "controller") return `${f(a.programs)} programs · ${f(a.runs)} runs`;
      if (id === "evaluator") return `${f(a.scored)} scored · ${f(a.customers)} customers`;
      if (id === "invariants") return `${f(a.caught)} struck · ${f(a.reached_population)} reached the population`;
      if (id === "holdout_judge") return `${f(a.validated)} of ${f(a.runs)} runs validated`;
      if (id === "lab_analyst") { const e = a.evals || {}; return `grounding ${f((e.grounding || {}).grounded)}/${f((e.grounding || {}).total)} · safety ${f((e.safety || {}).passed)}/${f((e.safety || {}).total)}`; }
      return "";
    };
    const render = (filter = "all", q = "") => {
      $("team-topology").innerHTML = S.tiers.filter((tier) => filter === "all" || tier.kind === filter).map((tier) => {
        const agents = tier.agents.map((id) => ({ id, ...S.agents[id] })).filter((a) => !q || (a.name + a.desc + a.title).toLowerCase().includes(q));
        if (!agents.length) return "";
        return `<div class="tier"><div class="tier-badge ${tier.kind === "lead" || tier.kind === "live" ? "lead" : tier.kind === "critic" ? "critic" : ""}">${esc({ lead: "L", spec: "S", critic: "R", live: "A" }[tier.kind] || tier.name[0])}</div>
          <div class="tier-card expanded"><div class="tier-head"><div><div class="tier-title">${esc(tier.name)}</div><div class="tier-desc">${esc(tier.desc)}</div></div><span class="badge ${tier.kind === "critic" ? "badge-critical" : tier.kind === "live" ? "badge-primary" : "badge-stable"}">${esc(tier.kind === "live" ? "LIVE" : tier.kind)}</span></div>
          <div class="tier-body"><div class="agent-grid">${agents.map((a) => `<div class="agent-card" data-id="${esc(a.id)}"><div><span class="badge-id">${esc(a.id_badge)}</span><div class="agent-title">${esc(a.name)}</div><div class="agent-desc">${esc(a.desc)}</div></div><div class="agent-foot"><span class="cite">${esc(stat(a.id))}</span><span class="chip">Open</span></div></div>`).join("")}</div></div></div></div>`;
      }).join("");
      $("team-topology").querySelectorAll(".agent-card").forEach((c) => c.onclick = () => deepdive(c.dataset.id));
    };
    $("team-filters").onclick = (e) => { const b = e.target.closest(".filter-chip"); if (!b) return; [...$("team-filters").children].forEach((x) => x.classList.toggle("active", x === b)); render(b.dataset.k, $("team-search").value.toLowerCase()); };
    $("team-search").oninput = () => render(($("team-filters").querySelector(".active") || {}).dataset?.k || "all", $("team-search").value.toLowerCase());
    const valueCard = (a) => {
      const k = a.value_kind, c = T.controller || {}, h = T.holdout_judge || {}, e = (T.lab_analyst || {}).evals || {};
      if (k === "cost") return `<div class="value-amount">USD ${Alpha.range((c.cost_usd || {}).low, (c.cost_usd || {}).high, "", 2)}</div><div class="value-period">per searched run, token estimate</div>`;
      if (k === "count") return `<div class="value-amount">${f((T.evaluator || {}).scored)} candidates</div><div class="value-period">scored on the same customers and scenarios, ${f((T.evaluator || {}).sandbox_caught)} stopped by the sandbox</div>`;
      if (k === "caught") return `<div class="value-amount">${f((T.invariants || {}).caught)} struck</div><div class="value-period">${Object.entries((T.invariants || {}).by_rule || {}).map(([r, n]) => `${r} ${n}`).join(" · ") || "none"} · ${f((T.invariants || {}).reached_population)} reached the population</div>`;
      if (k === "trading") return `<div class="value-amount">${Alpha.range((h.trading_range || {}).low, (h.trading_range || {}).high, "", 1)} JPY M/yr</div><div class="value-period">trading, validated on held-out days · tariff: ${(h.tariff || []).length ? LAB.delta(h.tariff[0], { inline: true, prov: false }) : "no validated run"}</div>`;
      if (k === "evals") return `<div class="value-amount">${f((e.grounding || {}).grounded)} of ${f((e.grounding || {}).total)} grounded</div><div class="value-period">figures checked against SQL truth; safety ${f((e.safety || {}).passed)} of ${f((e.safety || {}).total)}; rubric cases ${f((e.adk || {}).passed)} of ${f((e.adk || {}).total)}</div>`;
      return NITD;
    };
    const deepdive = (id) => {
      const a = { id, ...S.agents[id] }; if (!a.name) return;
      const rp = LAB.replays.find((r) => r.id === a.replay_id);
      $("team-deepdive").innerHTML = `<div class="deepdive-nav"><div><span class="badge-id">${esc(a.id_badge)}</span> <span class="badge badge-primary">${esc(a.apqc)}</span></div><span class="cite">${esc(LAB.story.provenance)}</span></div>
        <div class="deepdive-top"><div><div class="deepdive-hero">${esc(a.title)}</div><p class="section-subtitle">${esc(a.desc)}</p></div><div class="value-card"><div class="value-head">${esc(a.value_label)}</div>${valueCard(a)}</div></div>
        <div class="deepdive-main"><div class="col">
          <div class="problem-card"><div class="card-head">The problem it removes</div><div class="card-text">${esc(a.problem)}</div></div>
          <div class="biz-card"><div class="biz-stake">${esc(a.stake)}</div>${a.rows.map((r) => `<div class="biz-row${r.limit ? " limit" : ""}"><div class="biz-label">${esc(r.k)}</div><div class="biz-value">${t(esc(r.v))}</div></div>`).join("")}</div>
          <div class="flow-card"><div class="card-head">The five-stage decision flow</div><div class="decision-flow" id="team-flow">${a.flow.map((s, i) => `<div class="flow-stage" data-stage="${esc(s.stage)}"><div class="flow-rail"><div class="flow-marker">${i + 1}</div><div class="flow-connector"></div></div><div class="flow-body"><div class="flow-label">${esc(s.stage)}</div><div class="flow-value">${t(esc(s.v))}</div><div class="flow-business">${esc(s.biz)}</div></div></div>`).join("")}</div></div>
        </div><div class="col deepdive-right">
          <div class="card"><div class="card-head">Ask this agent<span class="badge badge-live">LIVE</span></div><p class="card-text" style="margin-bottom:10px">${id === "lab_analyst" ? "One question, streamed from the analyst." : "This agent runs as a batch job; the Lab Analyst answers about it from its tables."}</p><button class="btn btn-primary" id="team-ask">${esc(t(a.ask))}</button><div id="team-ask-host" style="margin-top:12px"></div></div>
          <div class="card"><div class="card-head">Play the recorded run<span class="badge badge-replay">REPLAY</span></div>${rp ? `<p class="card-text">${esc(rp.question)}</p><button class="btn" id="team-replay">Play the replay</button><div id="team-replay-host" style="margin-top:12px"></div>` : `<p class="card-text">${NITD}</p>`}</div>
          <div class="card"><div class="card-head">Provenance</div>${a.tables.map((tb) => `<div class="prov-row"><span><span class="prov-dot"></span> ${esc(tb)}</span><span class="prov-badge">READ</span></div>`).join("")}</div>
        </div></div>`;
      Alpha.play($("team-flow"));
      $("team-ask").onclick = () => LAB.ask($("team-ask-host"), t(a.ask), { replayId: a.replay_id });
      if (rp) $("team-replay").onclick = () => { $("team-replay-host").innerHTML = `<div class="ask"><div class="ask-head"><div class="ask-q">${esc(rp.question)}</div><span class="badge badge-replay" data-state="replay">REPLAY · recorded ${esc(rp.recorded_in)}</span></div><div class="ask-body"><div class="ask-tools">${rp.tools.map((x) => `<span class="ask-tool done">${esc(x)}</span>`).join("")}</div><div class="ask-text">${LAB.md(rp.reply)}</div></div><div class="ask-foot"><span>label ${esc(rp.label)} · latency then ${esc(String(rp.latency_s))} s · tables ${esc(rp.tables.join(", "))}</span></div></div>`; };
      $("team-deepdive").scrollIntoView({ behavior: "smooth", block: "start" });
    };
    render(); deepdive("controller"); window.scrollTo(0, 0);
  }

  /* ---------- screen 6: how it's built ---------- */
  function renderBuilt() {
    const S = LAB.story.built, D = LAB.data, pane = $("pane-built"), sol = D.solution || {}, hv = D.health || {};
    const prod = sol.architecture || sol.production || [];
    const asks = S.ask_ids.map((id) => LAB.replays.find((r) => r.id === id)).filter(Boolean);
    pane.innerHTML = `<div class="eyebrow top">${esc(S.eyebrow)}</div><h1 class="hero-title">${esc(S.hero)}</h1><div class="lede-row"><p class="hero-desc">${esc(S.lede)}</p>${LAB.provTag()}</div>
      <div class="boundary-hero"><div class="shield" aria-hidden="true">&#9679;</div><div class="boundary-headline">${esc(S.hero)}</div><div class="boundary-sub">${esc(S.boundary_sub)}</div></div>
      <div class="arch-grid"><div class="arch-stack" id="arch-stack">${S.stack.map((b, i) => (i ? `<div class="arch-seam"><span class="down">&#8595; request</span><span class="up">&#8593; evidence</span></div>` : "") +
        `<div class="arch-block${b.sim ? " sim" : ""}"><div class="arch-band">${esc(b.band)}${b.sim ? " · SIMULATED" : ""}</div><div><div class="arch-name">${esc(b.name)}</div><div class="arch-blurb">${esc(b.blurb)}</div><div class="arch-chips">${b.chips.map((c) => `<span class="arch-chip">${esc(c)}</span>`).join("")}</div></div>
          <div class="arch-traffic"><div class="arch-traffic-line down"><span class="arrow">&#8595;</span><span>${i === 0 ? "a question, a hold" : "a request, read-only"}</span></div><div class="arch-traffic-line up"><span class="arrow">&#8593;</span><span>${i === S.stack.length - 1 ? "calibrated rows" : "figures with their table names"}</span></div></div></div>`).join("")}</div>
        <div class="control-rail"><div class="control-title">Controls that bind every layer</div>${S.controls.map((c) => `<div class="control-card"><div class="control-name">${esc(c.name)}</div><div class="control-rule">${t(esc(c.rule))}</div></div>`).join("")}
          <div class="kv-card"><div class="kv-row"><span class="kv-key">ui_variant</span><span class="kv-val">${esc(hv.ui_variant || "NOT IN THE DATA")}</span></div><div class="kv-row"><span class="kv-key">agent backend</span><span class="kv-val">${esc(hv.agent_backend || "NOT IN THE DATA")}</span></div><div class="kv-row"><span class="kv-key">data backend</span><span class="kv-val">${esc(hv.data_backend || "NOT IN THE DATA")}</span></div></div></div></div>
      <div class="section-title">Where every figure comes from</div><div class="provenance-row">${S.provenance.map((p, i) => `<div class="provenance-step${i === S.provenance.length - 1 ? " final" : ""}"><b>${esc(p.k)}</b>${esc(p.v)}</div>`).join("")}</div>
      <div class="section-title" style="margin-top:32px">${esc(S.ask_title)}</div><p class="section-subtitle">${esc(S.ask_sub)}</p>
      <div class="ask-grid">${asks.map((r) => `<div class="card ask-card"><div class="q">${esc(r.question)}</div><div class="tables">${r.tables.map((x) => `<span class="arch-chip">${esc(x)}</span>`).join("")}</div><div class="chip-row"><button class="btn btn-outline ask-live" data-id="${esc(r.id)}">Ask live</button><span class="cite">recorded: ${esc(r.label)}</span></div><div class="ask-host" style="margin-top:12px"></div></div>`).join("") || `<div class="card">${NITD}</div>`}</div>
      <div class="section-title">${esc(S.path_title)}</div><table class="path-table"><thead><tr><th>Layer</th><th>The demo simulates</th><th>Production uses</th></tr></thead><tbody>${(prod || []).map((r) => `<tr><td>${esc(r.layer)}</td><td class="sim">${esc(r.demo)}</td><td>${esc(r.production)}</td></tr>`).join("") || `<tr><td colspan="3">${NITD}</td></tr>`}</tbody></table>
      ${LAB.techDrawer(`<div class="kv-card"><div class="kv-row"><span class="kv-key">Server</span><span class="kv-val">server/app.py (FastAPI), server/v2_api.py, server/alpha_api.py; UI_VARIANT=alpha mounts this front end at /</span></div><div class="kv-row"><span class="kv-key">Analyst</span><span class="kv-val">energy_lab/agent.py, nine tools in energy_lab/tools/lab_tools.py; evals in docs/EVAL_REPORT.md</span></div><div class="kv-row"><span class="kv-key">Search</span><span class="kv-val">energy_lab/harness: sandbox, baseline lock, budget ledger, evidence; the managed client behind one flag</span></div><div class="kv-row"><span class="kv-key">Caveat as data</span><span class="kv-val">energy_lab/segment_judgments.py, lab_segment_judgments, lab_runs.uplift_caveat</span></div></div>`)}${LAB.disclaimer()}`;
    pane.querySelectorAll(".ask-live").forEach((b) => b.onclick = () => { const r = LAB.replays.find((x) => x.id === b.dataset.id); LAB.ask(b.closest(".ask-card").querySelector(".ask-host"), r.question, { replayId: r.id }); });
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
