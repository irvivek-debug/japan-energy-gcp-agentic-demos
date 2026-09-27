/* The front door. It argues one thing before it offers a door: the rules that price the book and trade the
 * position were fitted to a market that has moved, and the distance is measured here, on data the search never
 * saw. Every figure below is read from /api/v2/landing and /api/v2/evidence; none is typed into this file.
 */
(async function () {
  const { $, esc, t, st, txt, isNum, badge, footer, fyOf, counts, sparkline, moveCursor } = window.LAB;
  LAB.nav("landing", "");

  let L, E;
  try {
    [L, E] = await Promise.all([Shell.api("/api/v2/landing"), Shell.api("/api/v2/evidence")]);
  } catch (e) {
    $("hero-ledes").innerHTML = LAB.errorNote("/api/v2/landing, /api/v2/evidence", e);
    return;
  }
  const rows = L.gap_rows || [];
  const row = (id) => rows.find((r) => r.id === id) || {};

  /* ---------- hero: two ledes with the business gap in figures ---------- */
  const H = L.hero || {};
  const keys = Object.keys(H);
  const kPast = keys.find((k) => /^fy\d{4}_tokyo_mean$/.test(k));
  const kNow = keys.find((k) => /^fy\d{4}_regime_mean$/.test(k));
  const kPub = keys.find((k) => /^fy\d{4}_research$/.test(k));
  const regime = row("price_regime");
  const trade = row("trading_holdout");
  $("hero-ledes").innerHTML =
    `<p class="lede">Tokyo spot power averaged ${t(H[kPast], regime.unit, 2)} across ${esc(fyOf(kPast))} in this data. ` +
    `The ${esc(fyOf(kNow))} scenarios the search is judged on run at ${t(H[kNow], regime.unit, 2)}, and the published ` +
    `${esc(fyOf(kPub))} figure for the months so far is ${t(H[kPub], regime.unit, 2)} ` +
    `(${esc((regime.research || {}).source || "source not in the data")}). A renewal book priced on last year's costs ` +
    `carries that difference as risk, and a bidding rule tuned on last year's prices misreads this one.</p>` +
    `<p class="lede">${t(H.runs, "", 0)} search runs have written and scored ${t(H.programs, "", 0)} candidate programs against ` +
    `this balance group's own data` +
    (H.zero_program_attempts > 0
      ? ` (${t(H.zero_program_attempts, "", 0)} further attempts generated no program because every model call failed; they are kept as evidence and counted nowhere else)`
      : "") +
    `. On trading days the search never saw, the best strategy beat the rule-based seed by ` +
    `${st(H.trading_best_delta, trade.unit)} on cost to serve and risk. ` +
    (H.tariff_validated === true
      ? `A tariff book has also kept every customer rule on customers it never saw${row("tariff_holdout").caveat ? `, with a caveat: ${esc(row("tariff_holdout").caveat)}` : ""}. `
      : H.tariff_validated === false
        ? "No tariff book has yet kept every customer rule on customers it never saw, so no tariff gain is quoted. "
        : "Whether a tariff book has held on unseen customers is NOT IN THE DATA. ") +
    `${t(H.policy_catches, "", 0)} candidates broke a rule and were stopped before they could count. ` +
    `Every run used the ${LAB.provTag(L.provenance_label)}.</p>`;

  /* ---------- the gap, measured ---------- */
  $("gap-lede").textContent =
    "Each row compares what the ordinary rule delivers with the best the search found or the market now asks for, " +
    "and sets it beside what published research says is available. Where no study backs a figure, the row says so.";

  const cell = (o, unit) =>
    `${isNum(o && o.value) ? t(o.value, "") : LAB.NITD}<span class="lbl">${esc((o && o.label) || "")}</span>`;
  const gapCell = (r) => {
    const v = isNum(r.gap) ? st(r.gap, "") : LAB.NITD;
    const b = r.validated === true ? badge("VALIDATED ON HOLDOUT", "b-ok") : r.validated === false ? badge("NOT VALIDATED", "b-warn") : "";
    return `${v}${b ? `<span class="lbl">${b}</span>` : ""}${LAB.caveat(r.caveat)}`;
  };
  const research = (x) =>
    x && x.source
      ? `<td class="research">${esc(x.text)}<span class="cite">${esc(x.source)}</span></td>`
      : `<td class="research none">NO VERIFIED BENCHMARK HELD</td>`;
  $("gap-table").innerHTML =
    "<thead><tr><th scope=\"col\">Quantity</th><th scope=\"col\" class=\"num\">Ordinary</th><th scope=\"col\" class=\"num\">Best / target</th>" +
    "<th scope=\"col\" class=\"num\">The gap</th><th scope=\"col\">What the research says is available</th></tr></thead><tbody>" +
    rows
      .map(
        (r) =>
          `<tr><th scope="row" class="q">${esc(r.quantity)}<span class="lbl">${esc(r.unit)}</span></th>` +
          `<td class="num">${cell(r.ordinary)}</td><td class="num">${cell(r.best)}</td><td class="num gapc">${gapCell(r)}</td>` +
          research(r.research) +
          "</tr>"
      )
      .join("") +
    "</tbody>";
  $("gap-note").innerHTML = `<div class="note"><strong>What this gap is, and is not</strong><br>${esc(L.gap_note)}</div>`;

  /* ---------- the evidence: a scrubber over the recorded window ---------- */
  const dates = E.dates || [];
  const N = dates.length;
  const series = E.series || [];
  $("strip-lede").innerHTML =
    `The rows above were measured on these ${t(series.length, "", 0)} daily series, recorded from ${esc(E.window.from)} to ` +
    `${esc(E.window.to)} (${t(E.window.days, "days", 0)}). Drag the scrubber and every card moves to that day. ` +
    `A status word is worked out from the thresholds the server sends with each series: ${esc(E.status_rule || "")}.`;

  $("scrub").innerHTML =
    `<label for="scrub-range">Recorded day</label><span>${esc(dates[0] || "")}</span>` +
    `<input type="range" id="scrub-range" min="0" max="${Math.max(0, N - 1)}" value="0" step="1">` +
    `<span>${esc(dates[N - 1] || "")}</span><span>Showing <span class="at" id="scrub-at"></span></span>`;

  /** First threshold that matches wins. The last rung is the baseline; the most severe of three or more is critical. */
  function statusOf(s, v) {
    if (!isNum(v)) return null;
    const list = s.status || [];
    for (let i = 0; i < list.length; i++) {
      const th = list[i];
      const hit = "min" in th ? v >= th.min : "max" in th ? v < th.max : false;
      if (hit) return { i, label: th.label, cls: i === list.length - 1 ? "b-idle" : i === 0 && list.length >= 3 ? "b-crit" : "b-warn" };
    }
    return null;
  }
  const severeDays = (s) => {
    const list = s.status || [];
    if (list.length < 2) return "";
    const k = (s.values || []).filter((v) => { const x = statusOf(s, v); return x && x.i === 0; }).length;
    return `${esc(list[0].label)} on ${txt(k, 0)} of ${txt(N, 0)} days`;
  };
  $("strip").innerHTML = series
    .map(
      (s, i) =>
        `<div class="card spark-card reveal" id="sc-${i}">` +
        `<div class="head"><span class="who">${esc(s.label)}</span><span id="sb-${i}"></span></div>` +
        `<div class="val"><span id="sv-${i}"></span><span class="u">${esc(s.unit)}</span></div>` +
        sparkline(s.values, { height: 48, label: `${s.label}, ${s.unit}, ${dates[0] || ""} to ${dates[N - 1] || ""}` }) +
        `<div class="what">${severeDays(s)}</div></div>`
    )
    .join("");

  const svgs = series.map((_, i) => document.querySelector(`#sc-${i} svg.spark`));
  function show(idx) {
    $("scrub-at").textContent = dates[idx] || "";
    $("scrub-range").setAttribute("aria-valuetext", dates[idx] || "");
    series.forEach((s, i) => {
      const v = (s.values || [])[idx];
      $(`sv-${i}`).innerHTML = isNum(v) ? esc(txt(v)) : LAB.NITD;
      const st_ = statusOf(s, v);
      $(`sb-${i}`).innerHTML = st_ ? badge(st_.label, st_.cls) : badge("NO READING", "b-idle");
      moveCursor(svgs[i], idx, N);
    });
  }
  const range = $("scrub-range");
  let frame = 0;
  let sweep = null;
  if (window.Motion.REDUCED || N < 2) {
    frame = Math.max(0, N - 1);
    range.value = String(frame);
    show(frame);
  } else {
    show(0);
    const step = Math.max(1, Math.ceil(N / 70));
    sweep = setInterval(() => {
      frame = Math.min(N - 1, frame + step);
      range.value = String(frame);
      show(frame);
      if (frame >= N - 1) { clearInterval(sweep); sweep = null; }
    }, 60);
  }
  range.addEventListener("input", () => {
    if (sweep) { clearInterval(sweep); sweep = null; }
    show(Number(range.value));
  });

  /* ---------- where to start: two doors with counted facts ---------- */
  const NAV = window.APP_SHELL.nav;
  const DOORS = [
    {
      key: "case", eyebrow: `Read first · ${NAV.case.length} chapters`, title: "The case for change", href: NAV.case[0].href, cta: "Read the case",
      lede: "Why the price book and the trading rules have to change, how big the gap is on data the search never saw, what closing it is worth as a range, and how each claim was tested.",
    },
    {
      key: "workspace", eyebrow: `Then this · ${NAV.workspace.length} screens`, title: "The workspace", href: NAV.workspace[0].href, cta: "Open the workspace",
      lede: "Where the work happens: the measures each run moves, the cockpit, the agent teams you can question, your role, and the handover dossier a reviewer signs.",
    },
  ];
  $("doors").innerHTML = DOORS.map(
    (d) =>
      `<div class="card c6 door lift reveal"><div class="card-cap">${esc(d.eyebrow)}</div><h3>${esc(d.title)}</h3>` +
      `<p class="small muted" style="margin:0">${esc(d.lede)}</p><div class="facts">` +
      ((L.doors || {})[d.key] || [])
        .map((f) => `<div><b${isNum(f.value) ? ` data-count="${Number(f.value)}" data-dp="0"` : ""}>${isNum(f.value) ? esc(txt(f.value, 0)) : LAB.NITD}</b><span>${esc(f.label)}</span></div>`)
        .join("") +
      `</div><div class="btn-row"><a class="btn primary" href="${esc(d.href)}">${esc(d.cta)}</a></div></div>`
  ).join("");

  /* ---------- provenance ---------- */
  const sources = [...new Set([...(L.source || []), ...(E.source || [])])];
  const cited = [...new Set(rows.map((r) => (r.research || {}).source).filter(Boolean))];
  $("prov").innerHTML =
    Shell.technicalDrawer(
      `<p class="small">Gap rows, in the order the server returns them, with the identifier each is computed under. ` +
        `Evidence series thresholds are sent with the data; this page applies them and holds none of its own.</p>` +
        `<dl class="kv">${rows.map((r) => `<dt>${esc(r.id)}</dt><dd class="mono">${esc(r.quantity)} · ${esc(r.unit)}</dd>`).join("")}` +
        `${series.map((s) => `<dt>${esc(s.id)}</dt><dd class="mono">${esc(s.status.map((x) => `${x.label} ${"min" in x ? ">= " + x.min : "< " + x.max}`).join("; "))}</dd>`).join("")}</dl>`,
      "row identifiers and status thresholds"
    ) +
    footer([
      ["Tables and files", `<span class="mono">${esc(sources.join(", "))}</span>`],
      ["Data window", `${esc(E.window.from)} to ${esc(E.window.to)} · ${t(E.window.days, "days", 0)}`],
      ["Generator seed", L.generator && L.generator.history_seed != null
        ? `<span class="mono">${esc(String(L.generator.history_seed))}</span> <span class="dim small">(history; cohorts and scenario banks have their own seeds, ${esc(L.generator.source)})</span>`
        : `${LAB.NITD} <span class="dim small">(no /api field exposes it)</span>`],
      ["Research cited", esc(cited.join("; "))],
      ["Runs", LAB.provTag(L.provenance_label)],
    ]);

  Motion.reveal();
  counts();
})();
