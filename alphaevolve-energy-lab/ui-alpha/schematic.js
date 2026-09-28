/* Screen 2: the evolution loop as a clickable twin. Nodes, states and readings come from /api/alpha/twin. */
(function () {
  const $ = (id) => document.getElementById(id);
  let TW = null;

  function nodeHTML(n) {
    const cls = n.state === "crit" ? " crit" : n.state === "watch" ? " watch" : n.state === "dashed" ? " dashed" : "";
    const rd = (n.readings || [])[0];
    return `<button class="snode${cls}" data-node="${LAB.esc(n.id)}" aria-label="${LAB.esc(n.name)}">${n.state === "crit" || n.state === "watch" ? '<span class="sdot"></span>' : ""}${LAB.esc(n.name)}<small>${LAB.esc(n.sub)}</small>${rd ? `<span class="rd">${LAB.esc(rd.k)}: ${LAB.esc(rd.v)}</span>` : ""}</button>`;
  }

  function drawer(id) {
    const n = TW.nodes.find((x) => x.id === id); if (!n) return;
    document.querySelectorAll("#twin .snode").forEach((b) => b.classList.toggle("selected", b.dataset.node === id));
    const stateWord = { crit: "CRITICAL · catch node", watch: "WATCHED", dashed: "NOT PROVISIONED", normal: "NORMAL" }[n.state] || "NORMAL";
    let html = `<div><div class="drawer-label">Live readings<span class="badge ${n.state === "crit" ? "badge-critical" : n.state === "watch" ? "badge-warning" : n.state === "dashed" ? "badge-stable" : "badge-optimal"}">${LAB.esc(stateWord)}</span></div>
      <div class="kv-card">${(n.readings || []).map((r) => `<div class="kv-row"><span class="kv-key">${LAB.esc(r.k)}</span><span class="kv-val">${LAB.esc(r.v)}</span></div>`).join("")}</div></div>`;
    if (n.catches && n.catches.length) html += `<div><div class="drawer-label">What it caught, in the evaluator's words</div><div class="catch-list">${n.catches.slice(0, 6).map((c) => `<div class="catch"><div class="id"><span>${LAB.esc(c.program_id)} · ${LAB.esc(c.run_id)}</span><span class="raw">would have scored ${LAB.f(c.raw_score)} (seed ${LAB.f(c.seed_train)})</span></div>${LAB.esc(c.insight)}</div>`).join("")}</div></div>`;
    else if (n.catches) html += `<div><div class="drawer-label">What it caught</div><div class="card-text">No candidate broke this rule in the searched runs.</div></div>`;
    if (n.runs) html += `<div><div class="drawer-label">Holdout, run by run</div><table class="mini-table"><thead><tr><th>Run</th><th>Fold</th><th>Outcome</th></tr></thead><tbody>${n.runs.map((r) => `<tr class="${r.delta.valid ? "ok" : "crit"}"><td class="mono" style="font-size:10.5px">${LAB.esc(r.run_id)}</td><td>${LAB.esc(r.fold || "")}</td><td>${r.problem === "tariff_pricing" ? LAB.delta(r.delta, { inline: true, prov: false }) : (r.delta.valid ? `<span class="mono">${LAB.esc(LAB.signed(r.delta.value, 1))} ${LAB.esc(r.delta.unit)}</span>` : "NO VALIDATED UPLIFT")}</td></tr>`).join("")}</tbody></table><div class="cite" style="margin-top:6px">${LAB.esc(LAB.story.provenance)}</div></div>`;
    html += `<div><div class="drawer-label">Who watches this</div><div class="chip-row">${(n.watchers || []).map((w) => `<span class="chip">${LAB.esc(w)}</span>`).join("")}</div></div>`;
    if (id === "review" || id === "holdout" || id === "invariants") html += `<div><button class="btn btn-outline" id="twin-ask">Ask the analyst about this station</button><div id="twin-ask-host" style="margin-top:12px"></div></div>`;
    const body = Alpha.drawer.open(n.name, html, `The loop · ${TW.zones.find((z) => z.id === n.zone).name}`);
    const b = body.querySelector("#twin-ask");
    if (b) b.onclick = () => LAB.ask(body.querySelector("#twin-ask-host"), id === "review" ? "Just promote the best program to production, we are in a hurry." : id === "holdout" ? LAB.F.analyst_question : "Which invariants rejected candidates in the latest tariff run, and what would they have scored?",
      { replayId: id === "review" ? "promotion_refusal" : id === "holdout" ? "tariff_latest_every_rule" : "regulatory_intentional_imbalance" });
  }

  function relink() {
    const svg = $("twin-svg"), box = $("twin-grid"); if (!svg || !box || !TW) return;
    const R = box.getBoundingClientRect();
    const pos = (id) => { const el = box.querySelector(`[data-node="${id}"]`); if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left - R.left, y: r.top - R.top, w: r.width, h: r.height }; };
    svg.setAttribute("viewBox", `0 0 ${R.width} ${R.height}`);
    svg.innerHTML = TW.links.map(([a, b, kind]) => {
      const A = pos(a), B = pos(b); if (!A || !B) return "";
      const stacked = Math.abs((A.x + A.w / 2) - (B.x + B.w / 2)) < 40;
      let d;
      if (kind === "back") d = `M${A.x + A.w / 2} ${A.y + A.h} C ${A.x + A.w / 2} ${A.y + A.h + 60}, ${B.x + B.w / 2} ${B.y + B.h + 60}, ${B.x + B.w / 2} ${B.y + B.h}`;
      else if (stacked) d = `M${A.x + A.w / 2} ${A.y + A.h} L ${B.x + B.w / 2} ${B.y}`;
      else if (B.x >= A.x + A.w) d = `M${A.x + A.w} ${A.y + A.h / 2} C ${A.x + A.w + 24} ${A.y + A.h / 2}, ${B.x - 24} ${B.y + B.h / 2}, ${B.x} ${B.y + B.h / 2}`;
      else d = `M${A.x} ${A.y + A.h / 2} C ${A.x - 24} ${A.y + A.h / 2}, ${B.x + B.w + 24} ${B.y + B.h / 2}, ${B.x + B.w} ${B.y + B.h / 2}`;
      return `<path class="link ${kind}" d="${d}"/>`;
    }).join("");
  }
  window.relinkTwin = relink;

  window.renderSystem = function () {
    const S = LAB.story.system, pane = $("pane-system"); TW = LAB.data.twin;
    if (!TW) { pane.innerHTML = `<div class="card">${LAB.NITD}</div>`; return; }
    pane.innerHTML = `<div class="eyebrow top">${LAB.esc(S.eyebrow)}</div><h1 class="hero-title">${LAB.esc(S.hero)}</h1>
      <div class="lede-row"><p class="hero-desc">${LAB.esc(S.lede)}</p>${LAB.provTag()}</div>
      <div class="schematic-top"><div class="twin-legend"><span>normal</span><span class="l-watch">watched</span><span class="l-crit">critical: a catch node</span><span class="l-dashed">not provisioned</span></div><span class="cite">links: animated dashes carry candidates; red links carry catches</span></div>
      <div class="schematic-card" id="twin"><div class="schematic-grid-bg" id="twin-grid"><svg class="schematic-svg" id="twin-svg" aria-hidden="true"></svg>
        <div class="schematic-zones twin-zones">${TW.zones.map((z) => `<div class="zone-box"><div class="zone-title">${LAB.esc(z.name)}</div>${TW.nodes.filter((n) => n.zone === z.id).map(nodeHTML).join("")}</div>`).join("")}</div></div>
        <div class="sor-strip"><span class="sor-title">${LAB.esc(S.sor_title)}</span>${TW.systems_of_record.map((s) => `<span class="sor-item">${LAB.esc(s.name)}<small>${LAB.esc(s.detail)}</small></span>`).join("")}<span class="sor-note">${LAB.esc(S.sor_note)}</span></div></div>
      <div class="section-title">${LAB.esc(S.telemetry_title)}</div><div class="telemetry-grid" id="twin-telemetry"></div>
      ${LAB.techDrawer(`<div class="kv-card"><div class="kv-row"><span class="kv-key">Nodes and readings</span><span class="kv-val">/api/alpha/twin: evidence files (runs/*.json), the budget ledger, the customer and scenario tables</span></div><div class="kv-row"><span class="kv-key">Catch nodes</span><span class="kv-val">policy invariants with at least one rejected candidate; the drawer quotes the evaluator's insight text</span></div><div class="kv-row"><span class="kv-key">Holdout deltas</span><span class="kv-val">tariff deltas always carry the sampling-margin caveat computed from lab_segment_judgments</span></div></div>`)}${LAB.disclaimer()}`;
    $("twin-telemetry").innerHTML = TW.telemetry.map((c) => `<div class="telemetry-card${c.state === "crit" ? " crit" : c.state === "watch" ? " watch" : ""}"><div class="telemetry-head"><span>${LAB.esc(c.name)}</span><span class="badge ${c.state === "crit" ? "badge-critical" : c.state === "watch" ? "badge-warning" : "badge-optimal"} state-word">${LAB.esc(c.state_word)}</span></div>
      <div class="telemetry-values"><div><div class="t-label">latest</div><div class="t-num${c.state === "crit" ? " crit" : ""}">${LAB.f(c.value, c.unit === "JPY/kWh" ? 2 : c.unit === "JPY M/yr" ? 1 : 0)}<span class="t-unit">${LAB.esc(c.unit)}</span></div></div><div><div class="t-label">${LAB.esc(c.second.label)}</div><div class="t-num">${LAB.f(c.second.value, c.unit === "JPY/kWh" ? 2 : 0)}</div></div></div>${LAB.sparkline(c.values)}<div class="cite">${LAB.esc((c.source || []).join(", "))}</div></div>`).join("");
    pane.querySelectorAll("#twin .snode").forEach((b) => b.onclick = () => drawer(b.dataset.node));
    requestAnimationFrame(relink); setTimeout(relink, 400); setTimeout(relink, 1500);
    window.addEventListener("resize", relink);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(relink);
  };
})();
