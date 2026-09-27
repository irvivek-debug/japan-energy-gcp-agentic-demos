/* The front door. One argument, made before any door is offered: the gap comes first because it is the reason to
 * keep reading; the evidence second, so a reader who has just been given a number sees where it was taken from; the
 * doors last. No navigation bar: this page is a fork, and each family owns its own chrome.
 * Every figure below comes from /api. */
(async function () {
  const { esc, el, num, money, f, sparkline } = window.Desk;
  let facts, gap, ev, prize, proof, agents;
  try {
    [facts, gap, ev, prize, proof, agents] = await Promise.all([
      Shell.api("/api/story/facts"), Shell.api("/api/story/gap"), Shell.api("/api/story/evidence"),
      Shell.api("/api/story/prize"), Shell.api("/api/story/proof"), Shell.api("/api/agents"),
    ]);
  } catch (e) {
    window.Desk.fail(el("lede-1"), e);
    return;
  }

  /* ---------------- hero: the business gap in this data ---------------- */
  const slots = Object.keys(facts.short_by_slot).map(Number);
  el("lede-1").textContent =
    `At ${facts.clock.now.slice(11)} on Wednesday 19 August, in a Tokyo heatwave, this balancing group is ` +
    `${f(facts.short_mwh, "MWh")} short across the four evening half hours from slot ${Math.min(...slots)} to ${Math.max(...slots)}. ` +
    `The first of those gates closes at ${facts.clock.gate_closure.slice(11)}, in ${facts.clock.minutes_left} minutes, while the ` +
    `wide-area reserve margin is forecast to fall to ${f(facts.reserve_margin_min_pct, "%")} at ${facts.reserve_margin_min_time.slice(0, 5)}.`;
  el("lede-2").textContent =
    `Left alone, that short settles at the imbalance price: an expected ${money(facts.do_nothing_p50_jpy)} at the p50 forecast. ` +
    `Covered now with batteries the desk can trust and a few intraday purchases, it costs ${money(facts.plan_cost_jpy)}. ` +
    `The ${money(facts.avoided_p50_jpy)} between the two is the gap, and it comes back on every scarcity evening.`;

  /* ---------------- the gap, measured ---------------- */
  el("gap-lede").textContent =
    "Each row compares what happens if nobody acts, or what the screens report, with what the desk can actually do before " +
    "the gate. Beside each is what published research says about the market it sits in, set in a different register: a " +
    "third party's claim is not this data's measurement.";
  const cell = (c) => c.value === null || c.value === undefined
    ? `<span class="nodata">NOT IN THE DATA</span><span class="l">${esc(c.label)}</span>`
    : `<span class="v">${c.unit === "JPY" ? esc(money(c.value)) : `${esc(num(c.value, 1))}<span class="u">${esc(c.unit)}</span>`}</span><span class="l">${esc(c.label)}</span>`;
  el("gap").innerHTML =
    "<thead><tr><th>Quantity</th><th>Ordinary</th><th>Best / target</th><th>The gap</th><th>What the research says is available</th></tr></thead><tbody>" +
    gap.rows.map((r) => `<tr><td><b>${esc(r.quantity)}</b><span class="who-sub">${esc(r.sub)}</span></td>` +
      `<td>${cell(r.ordinary)}</td><td>${cell(r.best)}</td><td class="gapc">${esc(r.gap.text)}</td>` +
      `<td class="bench"><span class="claim">${esc(r.research.claim)}</span><span class="cite">${esc(r.research.cite)} · ${esc(r.research.ref)}</span></td></tr>`).join("") +
    "</tbody>";
  el("gap-note").innerHTML = `<div class="note"><strong>What this gap is, and is not</strong><br>${esc(gap.note)}</div>`;

  /* ---------------- the evidence: a scrubber over the recorded window ---------------- */
  const W = ev.window, N = W.points;
  el("strip-lede").textContent =
    `The figures above came off these ${ev.cards.length} series. The window runs ${W.labels[0]} to ${W.labels[N - 1]} in ${N} ` +
    `half-hour points. Up to ${W.now.slice(11)} on ${W.now.slice(0, 10)} the lines are recorded or settled; after it they are ` +
    `forecasts, drawn dashed. Drag the scrubber and every card moves to that half hour.`;
  el("scrub").innerHTML =
    `<span>Window</span><span class="mono">${esc(W.labels[0])}</span>` +
    `<input type="range" id="play" min="0" max="${N - 1}" value="0" aria-label="Scrub the data window">` +
    `<span class="mono">${esc(W.labels[N - 1])}</span><span>At <span class="at" id="at"></span></span>`;
  const fcFrom = { spot: null, imbalance: W.now_index, reserve: W.now_index, position: W.now_index, soc: null, frozen: null };
  el("strip").innerHTML = ev.cards.map((c) => `<div class="card asset reveal">
      <div style="display:flex;gap:8px;align-items:center;justify-content:space-between"><span class="who">${esc(c.label)}</span><span id="b-${c.id}" class="badge b-idle">-</span></div>
      <div class="val"><span id="v-${c.id}">-</span><span class="u">${esc(c.unit)}</span></div>
      <div class="what">${esc(c.kind)}</div>
      <div class="plot"><div id="p-${c.id}" class="playhead" style="left:0"></div>${sparkline(c.values, { height: 46, forecastFrom: fcFrom[c.id], label: c.label })}</div>
      <div class="what" style="margin-top:8px">${esc(c.source.map(window.Desk.srcShort).join(", "))}</div></div>`).join("");

  const runEqual = (vals, i) => { let k = 0; while (i - k - 1 >= 0 && vals[i - k] !== null && vals[i - k] === vals[i - k - 1]) k++; return k; };
  function badge(c, i) {
    const v = c.values[i];
    if (v === null || v === undefined) return ["b-idle", "no reading"];
    if (c.id === "spot") return ev.scarcity[i] ? ["b-crit", "scarcity block"] : ["b-idle", "normal"];
    if (c.id === "imbalance") return v >= 100 ? ["b-crit", ev.forecast[i] ? "scarcity, forecast" : "scarcity, settled"] : ["b-info", ev.forecast[i] ? "forecast" : "settled"];
    if (c.id === "reserve") return v < 5 ? ["b-crit", "critical"] : v < 8 ? ["b-warn", "tight"] : ["b-ok", "normal"];
    if (c.id === "position") return v < -0.5 ? ["b-crit", "short"] : v > 0.5 ? ["b-info", "long"] : ["b-ok", "flat"];
    if (c.id === "frozen") return runEqual(c.values, i) >= 11 ? ["b-crit", "frozen"] : ["b-ok", "recorded"];
    return ["b-ok", "recorded"];
  }
  const dp = { spot: 1, imbalance: 1, reserve: 1, position: 1, soc: 0, frozen: 0 };
  function show(i) {
    el("at").textContent = W.labels[i];
    const left = `${(i / (N - 1)) * 100}%`;
    ev.cards.forEach((c) => {
      const v = c.values[i];
      el(`v-${c.id}`).textContent = v === null || v === undefined ? "none" : num(v, dp[c.id]);
      el(`p-${c.id}`).style.left = left;
      const [cls, txt] = badge(c, i);
      const b = el(`b-${c.id}`);
      b.className = `badge ${cls}`;
      b.textContent = txt;
    });
  }
  // Plays once up to "now", then the reader owns it. setInterval, not rAF (see kit/motion.js).
  const play = el("play");
  let frame = 0, sweep = null;
  if (Motion.REDUCED) { play.value = String(W.now_index); show(W.now_index); }
  else {
    show(0);
    sweep = setInterval(() => {
      frame += 1;
      if (frame > W.now_index) { clearInterval(sweep); sweep = null; return; }
      play.value = String(frame); show(frame);
    }, 45);
  }
  play.addEventListener("input", () => { if (sweep) { clearInterval(sweep); sweep = null; } show(Number(play.value)); });

  /* ---------------- where to start: two doors ---------------- */
  const A = prize.branches.find((b) => b.code === "A");
  const grounding = proof.suites.find((s) => s.id === "grounding");
  const doors = [
    { href: "/case/", eyebrow: "Read first · five chapters", title: "The case for change",
      lede: "Why the 30-minute balancing rule becomes a board question this autumn, what the gap is worth as ranges, how the agents close it, and how that was tested.",
      facts: [[money(facts.avoided_p50_jpy), "avoided on one evening, expected", "p50 imbalance forecast minus the least-cost plan"],
              [window.Desk.moneyRange(A.low, A.high), "a year from balancing alone", A.assumption],
              [String(prize.branches.length), "value branches", "mutually exclusive, so nothing is counted twice"]],
      cta: "Read the case" },
    { href: "/workspace/value.html", eyebrow: "Then this · five screens", title: "The workspace",
      lede: "What the desk looks like once someone has to run it: the metrics the agents move, the cockpit, the agent teams at work, your role, and the handover brief for the next trader.",
      facts: [[String(agents.agents.length), "agents on the desk team", `${agents.agents.filter((a) => a.step === 1).length} lead, ${agents.agents.filter((a) => a.step === 2).length} specialists, ${agents.agents.filter((a) => a.step === 3).length} reviewer`],
              [String(facts.sign_off_kinds.length), "kinds of action held for a person", `trades, dispatch, tariffs and offers wait for a ${SignOff.HOLD_MS / 1000}-second hold`],
              [grounding ? `${grounding.first} of ${grounding.total}` : "NOT IN THE DATA", "answers grounded at the first attempt", "figures checked against the tables at test time"]],
      cta: "Open the workspace" },
  ];
  el("doors").innerHTML = doors.map((d) => `<div class="card lift door c6 reveal">
      <div class="eyebrow">${esc(d.eyebrow)}</div><h3>${esc(d.title)}</h3><p>${esc(d.lede)}</p>
      <div class="facts">${d.facts.map(([b, s, sm]) => `<div><b>${esc(b)}</b><span>${esc(s)}</span><small>${esc(sm)}</small></div>`).join("")}</div>
      <a class="btn primary" href="${d.href}">${esc(d.cta)}</a></div>`).join("");

  el("prov").innerHTML = await window.Desk.provenance([["This page", "gap, evidence and doors from /api/story/facts, /gap, /evidence, /prize, /proof and /api/agents"]]);
  Motion.reveal();
})();
