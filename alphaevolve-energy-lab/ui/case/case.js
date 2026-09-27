/* The case for change: five chapters, one script. Each chapter file carries its own headline and the words that
 * do not depend on the data; everything with a figure in it is drawn here from /api. The chapter is chosen by
 * <body data-chapter>. Order of every chapter: statement, evidence, what it replaces, technical detail,
 * provenance, next.
 */
(function () {
  const { $, esc, t, st, txt, isNum, badge, footer, fyOf, counts, countEl, provTag, runStatus } = window.LAB;
  const chapter = document.body.dataset.chapter;
  LAB.nav("case", chapter);

  /* ---------- shared pieces ---------- */
  function block({ eyebrow, title, lede, body }) {
    return (
      `<section><div class="eyebrow reveal">${esc(eyebrow)}</div><h2 class="reveal">${esc(title)}</h2>` +
      (lede ? `<p class="lede reveal">${lede}</p>` : "") +
      body +
      "</section>"
    );
  }
  function tile(value, unit, sub, lbl, d) {
    return `<div class="tile">${countEl(value, unit, d)}<div class="metric-sub">${esc(sub)}</div>${lbl ? `<div class="lbl">${esc(lbl)}</div>` : ""}</div>`;
  }
  function ofTile(num, den, sub, lbl) {
    const u = isNum(den) ? `of ${txt(den, 0)}` : "";
    return `<div class="tile">${countEl(num, u, 0)}<div class="metric-sub">${esc(sub)}</div>${lbl ? `<div class="lbl">${lbl}</div>` : ""}</div>`;
  }
  function finish(provRows, techHtml, hint) {
    $("tech").innerHTML = Shell.technicalDrawer(techHtml, hint);
    $("prov").innerHTML = footer(provRows);
    Motion.reveal();
    counts();
  }
  async function load(paths) {
    try {
      return await Promise.all(paths.map((p) => Shell.api(p)));
    } catch (e) {
      $("lede-data").innerHTML = LAB.errorNote(paths.join(", "), e);
      return null;
    }
  }
  const places = (v) => ((String(v).split(".")[1] || "").length);
  const src = (s) => `<span class="mono">${esc([].concat(s || []).join(", ") || "not stated")}</span>`;
  const gapRow = (L, id) => (L.gap_rows || []).find((r) => r.id === id) || {};
  const byStart = (a, b) => String(a.started || "").localeCompare(String(b.started || ""));
  /** Held-out delta cell: citable when validated; a recorded value that is not validated is printed and labelled. */
  const deltaCell = (x) =>
    x.uplift_valid ? st(x.holdout_delta, "") : isNum(x.holdout_delta) ? `${st(x.holdout_delta, "")}<span class="lbl">not citable</span>` : LAB.NITD;
  const PROBLEM_HUE = { jepx_trading: "var(--b1)", tariff_pricing: "var(--b3)" }; // same hue as the prize branch each feeds
  const researchLine = (r) =>
    r && r.source
      ? `<div class="cap-note" style="text-transform:uppercase">${esc(r.text)} · ${esc(r.source)}</div>`
      : `<div class="cap-note">NO VERIFIED BENCHMARK HELD</div>`;

  /* ---------- 1 · The case ---------- */
  const FY_MONTHS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3];
  const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  async function theCase() {
    const r = await load(["/api/v2/landing", "/api/market/monthly", "/api/overview", "/api/scenarios"]);
    if (!r) return;
    const [L, M, O, S] = r;
    const H = L.hero || {};
    const keys = Object.keys(H);
    const kPast = keys.find((k) => /^fy\d{4}_tokyo_mean$/.test(k));
    const kNow = keys.find((k) => /^fy\d{4}_regime_mean$/.test(k));
    const regime = gapRow(L, "price_regime"), tail = gapRow(L, "tariff_tail_risk"), tho = gapRow(L, "tariff_holdout");
    const port = O.portfolio || {};
    $("lede-data").innerHTML =
      `In this data the Tokyo spot price averaged ${t(H[kPast], regime.unit, 2)} in ${esc(fyOf(kPast))}. The ${esc(fyOf(kNow))} ` +
      `scenarios the book has to survive average ${t(H[kNow], regime.unit, 2)}, a move of ${st(regime.gap, regime.unit, 2)}. ` +
      `The renewal book covers ${t(port.customers, "customers", 0)} consuming ${t(port.annual_twh, "TWh", 2)} a year.`;

    const scenKey = Object.keys(M).find((k) => /^fy\d{4}_scenarios$/.test(k));
    const scenFY = fyOf(scenKey);
    const scen = scenKey ? M[scenKey] : [];
    const banks = [...new Set(scen.map((x) => x.bank))].sort((a, b) => (a === "train" ? -1 : b === "train" ? 1 : a.localeCompare(b)));
    const hist = M.history || [];
    const fys = [...new Set(hist.map((x) => x.fiscal_year))].sort();

    const fyTiles = (O.tokyo_mean_by_fy || []).map((x) => tile(x.tokyo_mean, regime.unit, `FY${x.fiscal_year} mean, history`, "", 2)).join("") +
      tile(regime.best && regime.best.value, regime.unit, `${fyOf(kNow)} regime`, regime.best && regime.best.label, 2);

    // Scenario banks: scenario counts, the scenario-weighted annual mean and the highest price, by bank and regime.
    const agg = {};
    (S.rows || []).forEach((x) => {
      const k = `${x.bank}|${x.regime}`;
      const a = (agg[k] = agg[k] || { bank: x.bank, regime: x.regime, n: 0, w: 0, max: null, stressed: 0 });
      a.n += x.scenarios || 0;
      a.w += (x.annual_mean || 0) * (x.scenarios || 0);
      a.max = a.max === null ? x.max_price : Math.max(a.max, x.max_price);
      if (x.stress && x.stress !== "none") a.stressed += x.scenarios || 0;
    });
    const aggRows = Object.values(agg).sort((a, b) => (a.bank + a.regime).localeCompare(b.bank + b.regime));

    $("blocks").innerHTML =
      block({
        eyebrow: "The market moved",
        title: "Prices, month by month, before and after",
        lede: `History runs from FY${esc(fys[0] || "")} to FY${esc(fys[fys.length - 1] || "")}. The dashed lines are the ${esc(scenFY)} scenario banks: the search trains on one and is judged on the other.`,
        body:
          `<div class="card reveal"><div class="tiles">${fyTiles}</div>` +
          `<div class="chart" id="chart-monthly" role="img" aria-label="Tokyo mean price by month, history and scenario banks" style="margin-top:16px"></div>` +
          `<p class="cap-note">Source: ${esc([].concat(M.source).join(", "))}. ${esc(regime.best ? regime.best.label : "")}.</p></div>`,
      }) +
      block({
        eyebrow: "The exposure",
        title: "What the cost-plus book risks",
        lede: "CVaR95 shortfall is the average margin shortfall across the worst scenarios in the bank. It is the loss a risk committee asks about first.",
        body:
          `<div class="card reveal"><div class="tiles">` +
          tile(tail.ordinary && tail.ordinary.value, tail.unit, "Seed book, CVaR95 shortfall", tail.ordinary && tail.ordinary.label) +
          tile(tail.best && tail.best.value, tail.unit, "Evolved book, CVaR95 shortfall", tail.best && tail.best.label) +
          tile(tho.ordinary && tho.ordinary.value, tho.unit, "Seed book score on held-out customers", tho.ordinary && tho.ordinary.label) +
          `</div>${researchLine(tail.research)}` +
          `<div class="note" style="margin-top:14px"><strong>Read with care</strong><br>Each figure carries the label of the data it was measured on. Chapter 2 shows what held on customers the search never saw.</div></div>`,
      }) +
      block({
        eyebrow: "What the rules must survive",
        title: "The scenario banks, by regime",
        lede: `Each bank mixes calm years with fuel shocks, cold snaps and heat domes. A price book is judged across all of them, not on the average year.`,
        body:
          `<div class="card reveal"><div class="table-scroll"><table class="data"><thead><tr><th>Bank</th><th>Regime</th>` +
          `<th class="num">Scenarios</th><th class="num">With a stress event</th><th class="num">Mean price</th><th class="num">Highest price</th></tr></thead><tbody>` +
          aggRows
            .map((a) => `<tr><td class="mono">${esc(a.bank)}</td><td>${esc(a.regime.replace(/_/g, " "))}</td><td class="num">${esc(txt(a.n, 0))}</td>` +
              `<td class="num">${esc(txt(a.stressed, 0))}</td><td class="num">${t(a.n ? a.w / a.n : null, regime.unit, 2)}</td><td class="num">${t(a.max, regime.unit, 1)}</td></tr>`)
            .join("") +
          `</tbody></table></div><p class="cap-note">Source: ${esc([].concat(S.source).join(", "))}. Mean price is weighted by scenario count.</p></div>`,
      });

    const T = LAB.tokens();
    const cats = FY_MONTHS.map((m) => MONTH[m - 1]);
    const syms = ["circle", "rect", "triangle", "diamond", "pin"];
    const series = [
      ...fys.map((fy, i) => ({
        name: `FY${fy} history`, type: "line", symbol: syms[i % syms.length], symbolSize: 6,
        data: FY_MONTHS.map((m) => (hist.find((x) => x.fiscal_year === fy && x.month === m) || {}).tokyo ?? null),
        lineStyle: { width: 1.75, color: T.b[i % 3 === 0 ? 0 : i % 3 === 1 ? 5 : 3] }, itemStyle: { color: T.b[i % 3 === 0 ? 0 : i % 3 === 1 ? 5 : 3] },
      })),
      ...banks.map((b, i) => ({
        name: `${scenFY} ${b} bank`, type: "line", symbol: i ? "triangle" : "diamond", symbolSize: 7,
        data: FY_MONTHS.map((m) => (scen.find((x) => x.bank === b && x.month === m) || {}).mean_price ?? null),
        lineStyle: { width: 1.75, type: i ? "dotted" : "dashed", color: i ? T.b[4] : T.b[1] }, itemStyle: { color: i ? T.b[4] : T.b[1] },
      })),
    ];
    LAB.chart("chart-monthly", {
      grid: LAB.grid({ top: 48, left: 52 }),
      legend: { top: 0, left: 0, itemWidth: 22, itemHeight: 8 },
      tooltip: LAB.axisTip((p) => `${txt(p.value, 2)} ${esc(regime.unit || "")}`),
      xAxis: { type: "category", data: cats, splitLine: { show: false } },
      yAxis: { type: "value", name: regime.unit || "", nameLocation: "end", nameGap: 12 },
      series,
    });

    const monthRows = FY_MONTHS.map(
      (m) => `<tr><td>${MONTH[m - 1]}</td>${banks.map((b) => `<td class="num">${t((scen.find((x) => x.bank === b && x.month === m) || {}).mean_price, "", 2)}</td>`).join("")}</tr>`
    ).join("");
    finish(
      [
        ["Market history", src(M.source)],
        ["Scenario banks", src(S.source)],
        ["Portfolio", src(O.source)],
        ["Gap rows", src(L.source)],
        ["Runs", provTag(L.provenance_label)],
      ],
      `<p class="small">Fiscal-year means are the average of every half-hour Tokyo area price in that year. The ${esc(scenFY)} banks are ` +
        `monthly means across all scenarios in each bank; the search only ever sees the train bank.</p>` +
        `<div class="table-scroll"><table class="data"><thead><tr><th>Month</th>${banks.map((b) => `<th class="num">${esc(b)} bank (${esc(regime.unit || "")})</th>`).join("")}</tr></thead><tbody>${monthRows}</tbody></table></div>`,
      "bank monthly means and method"
    );
  }

  /* ---------- 2 · The gap ---------- */
  async function theGap() {
    const r = await load(["/api/v2/landing", "/api/v2/proof"]);
    if (!r) return;
    const [L, P] = r;
    const runs = (P.runs || []).slice().sort(byStart);
    const ok = runs.filter((x) => !x.infrastructure_failure);
    const count = (prob) => {
      const a = ok.filter((x) => x.problem === prob);
      return [a.filter((x) => x.uplift_valid).length, a.length];
    };
    const [vt, nt] = count("jepx_trading"), [vp, np] = count("tariff_pricing");
    const failed = runs.filter((x) => x.infrastructure_failure).length;
    $("lede-data").innerHTML =
      `${t(vt, "", 0)} of ${t(nt, "", 0)} trading runs held a gain on the held-out days and kept every rule there. ` +
      `${t(vp, "", 0)} of ${t(np, "", 0)} tariff runs did. ` +
      (failed ? `${t(failed, "", 0)} further ${failed === 1 ? "run" : "runs"} generated no program at all and ${failed === 1 ? "is" : "are"} listed as an infrastructure failure. ` : "") +
      `Every run used the ${provTag(P.provenance_label)}.`;

    const figure = (o, unit, head) =>
      `<div class="tile"><div class="metric-sub" style="margin:0 0 6px">${esc(head)}</div>${countEl(o && o.value, unit)}<div class="lbl">${esc((o && o.label) || "")}</div></div>`;
    const rowsHtml = (L.gap_rows || [])
      .map(
        (g) =>
          `<div class="card c6 reveal"><div class="card-cap">${esc(g.quantity)}<span class="spacer"></span>` +
          (g.validated === true ? badge("VALIDATED ON HOLDOUT", "b-ok") : g.validated === false ? badge("NOT VALIDATED", "b-warn") : "") +
          `</div><div class="tiles">${figure(g.ordinary, g.unit, "Ordinary")}${figure(g.best, g.unit, "Best / target")}` +
          `<div class="tile"><div class="metric-sub" style="margin:0 0 6px">The gap</div>${isNum(g.gap) ? `<span class="metric">${g.gap > 0 ? "+" : ""}${esc(txt(g.gap))}<span class="u">${esc(g.unit)}</span></span>` : countEl(null)}</div></div>` +
          LAB.caveat(g.caveat) +
          researchLine(g.research) +
          "</div>"
      )
      .join("");

    // Delta bars, one scale per problem (a tariff book and a trading desk are not on the same axis).
    const probs = [...new Set(runs.map((x) => x.problem))];
    const bars = probs
      .map((prob) => {
        const rs = runs.filter((x) => x.problem === prob);
        const vals = rs.flatMap((x) => [x.uplift_valid ? x.holdout_delta : null, x.uplift_valid ? null : x.champion_raw_delta]).filter(isNum).map(Math.abs);
        const max = vals.length ? Math.max(...vals) * 1.1 : 1;
        const hue = PROBLEM_HUE[prob] || "var(--accent)";
        return (
          `<div class="card c6 reveal"><div class="card-cap"><span class="swatch" style="--c:${hue}"></span>${esc(LAB.problemLabel(prob))}: held-out delta by run</div>` +
          rs
            .map((x) => {
              const v = x.uplift_valid ? x.holdout_delta : x.champion_raw_delta;
              const dashed = !x.uplift_valid;
              const w = isNum(v) ? Math.max(0.8, (Math.abs(Number(v)) / max) * 100) : 0;
              const label = x.infrastructure_failure
                ? badge("NO PROGRAM GENERATED", "b-crit")
                : x.uplift_valid
                  ? `${st(x.holdout_delta, "JPY M")} ${badge("CITABLE", "b-ok")}`
                  : isNum(x.champion_raw_delta)
                    ? `${st(x.champion_raw_delta, "JPY M")} ${badge("RAW, NOT CITABLE", "b-crit")}`
                    : badge("NO CITABLE DELTA", "b-warn");
              return (
                `<div class="dbar" style="margin:10px 0"><div class="row" style="justify-content:space-between"><span class="mono small">${esc(x.run_id)}</span><span class="row">${label}</span></div>` +
                (isNum(v) && !x.infrastructure_failure
                  ? `<div class="dbar-track" role="img" aria-label="${esc(x.run_id)} ${esc(txt(v))} JPY M ${dashed ? "raw, not citable" : "validated"}"><i class="${dashed ? "dashed" : ""}" style="left:0;width:${w.toFixed(2)}%;--c:${hue}"></i></div>`
                  : "") +
                LAB.caveat(x.caveat) +
                "</div>"
              );
            })
            .join("") +
          `<div class="rbar-legend"><span class="k"><i style="--c:${hue}"></i>validated on the held-out fold</span>` +
          (rs.some((x) => !x.uplift_valid && !x.infrastructure_failure && isNum(x.champion_raw_delta)) ? `<span class="k"><i class="dashed" style="--c:${hue}"></i>raw: before the rules, not citable</span>` : "") +
          `</div></div>`
        );
      })
      .join("");

    const table =
      `<div class="card reveal" style="margin-bottom:16px"><div class="table-scroll"><table class="data"><thead><tr><th>Run</th><th>Outcome</th><th>Fold</th>` +
      `<th class="num">Seed, held out</th><th class="num">Champion, held out</th><th class="num">Held-out delta</th><th class="num">Raw delta before the rules</th></tr></thead><tbody>` +
      runs
        .map(
          (x) =>
            `<tr><td><span class="mono rid">${esc(x.run_id)}</span><span class="lbl">${esc(x.provenance)}</span></td><td>${runStatus(x)}${LAB.caveat(x.caveat)}</td><td class="mono rid">${esc(x.holdout_fold)}</td>` +
            `<td class="num">${t(x.holdout_seed, "")}</td><td class="num">${t(x.best_holdout, "")}</td><td class="num">${deltaCell(x)}</td>` +
            `<td class="num">${x.uplift_valid ? '<span class="dim">same</span>' : st(x.champion_raw_delta, "")}<span class="lbl">${x.uplift_valid ? "" : x.infrastructure_failure ? "no program generated" : "not citable"}</span></td></tr>`
        )
        .join("") +
      `</tbody></table></div><p class="cap-note">Scores in JPY M, higher is better. Trading scores are annualised. Source: ${esc([].concat(P.source).join(", "))}.</p></div>`;

    const pc = P.policy_catches || {};
    const inv = Object.entries(pc.by_invariant || {});
    $("blocks").innerHTML =
      block({ eyebrow: "The gap, row by row", title: "Ordinary against best, with the research beside it", lede: esc(L.gap_note), body: `<div class="bento">${rowsHtml}</div>` }) +
      block({
        eyebrow: "Seed against champion",
        title: "Every run, judged on the held-out fold",
        lede: "The champion is chosen on training scores. The held-out score is only reported, never used to choose, so it cannot be gamed.",
        body: table + `<div class="bento">${bars}</div>`,
      }) +
      block({
        eyebrow: "Invalid candidates",
        title: "What a rule stopped before it could count",
        lede: "A candidate that prices a segment out or leans on imbalance is rejected before it enters the population, whatever it would have scored.",
        body:
          `<div class="card reveal"><div class="tiles">${tile(pc.candidates, "", "Candidates rejected by a rule")}${tile(pc.invalid_that_reached_population, "", "Rejected candidates that reached the population")}` +
          inv.map(([k, v]) => tile(v, "", `Rule: ${k.replace(/_/g, " ")}`)).join("") +
          `</div><div class="table-scroll" style="margin-top:14px"><table class="data"><thead><tr><th>Run</th><th>Invalid candidates by kind</th></tr></thead><tbody>` +
          runs.map((x) => `<tr><td class="mono rid">${esc(x.run_id)}</td><td class="mono">${esc(Object.entries(x.invalid_by_kind || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "none")}</td></tr>`).join("") +
          `</tbody></table></div></div>`,
      });

    finish(
      [["Gap rows", src(L.source)], ["Runs and checks", src(P.source)], ["Runs", provTag(P.provenance_label)]],
      `<p class="small">The raw delta is the champion's held-out objective before the policy gate, minus the seed on the same fold. ` +
        `It shows what breaking a rule would have paid, which is exactly why it is not citable.</p><dl class="kv">` +
        runs.map((x) => `<dt>${esc(x.run_id)}</dt><dd class="mono">${esc(x.evaluator_version)} · fold ${esc(x.holdout_fold)} · ${esc(txt(x.programs, 0))} programs · ${esc(txt(x.cost_usd, 2))} USD</dd>`).join("") +
        "</dl>",
      "evaluator versions, folds, raw delta"
    );
  }

  /* ---------- 3 · The prize ---------- */
  function statusCls(row) {
    if (row.citable) return /VALIDATED/.test(row.status) ? "b-ok" : "b-info";
    return /RAW/.test(row.status) ? "b-crit" : "b-warn";
  }
  const single = (x) => isNum(x.low) && isNum(x.high) && Number(x.low) === Number(x.high);
  async function thePrize() {
    const r = await load(["/api/v2/prize"]);
    if (!r) return;
    const [Z] = r;
    const rows = Z.rows || [];
    const citable = rows.filter((x) => x.citable);
    $("lede-data").innerHTML =
      `${t(citable.length, "", 0)} of ${t(rows.length, "", 0)} ranges may be quoted today${citable.length ? `: ${citable.map((x) => esc(x.code)).join(", ")}` : ""}. ` +
      `${esc(Z.rule)} Runs behind these ranges used the ${provTag(Z.provenance_label)}.`;

    const units = [...new Set(rows.map((x) => x.unit))];
    const groups = units
      .map((u) => {
        const rs = rows.filter((x) => x.unit === u);
        const sc = LAB.scale(rs.flatMap((x) => [x.low, x.high]).concat([0]));
        return (
          `<div class="card reveal" style="margin-bottom:16px"><div class="card-cap">Ranges in ${esc(u)}<span class="spacer"></span>shared scale</div>` +
          rs
            .map((x) => {
              const hue = `var(--${esc(x.colour || "bx")})`;
              return (
                `<div class="vrow"><div><span class="code-tag"><span class="swatch" style="--c:${hue}"></span>${esc(x.code)}</span>` +
                `<div class="branch">${esc(x.branch)}</div><div class="mech">Mechanism: ${esc(x.mechanism)}</div></div>` +
                `<div><div class="row" style="justify-content:space-between"><span class="figs">${single(x) ? esc(txt(x.low)) : `${esc(txt(x.low))} to ${esc(txt(x.high))}`}<span class="u">${esc(x.unit)}</span></span>` +
                `<span class="row">${badge(x.status, statusCls(x))}${x.citable || /NOT CITABLE/.test(x.status) ? "" : badge("NOT CITABLE", "b-crit")}</span></div>` +
                LAB.rangeBar({ low: x.low, high: x.high, min: sc.min, max: sc.max, colour: hue, dashed: !x.citable, label: `${x.code} ${x.branch}`, unit: x.unit }) +
                (single(x) ? `<div class="cap-note" style="margin-top:6px">A single validated value, not yet a range: every validated run behind it scored the same, or there is only one.</div>` : "") +
                LAB.caveat(x.caveat) +
                `<div class="basis">${esc(x.basis)}</div></div></div>`
              );
            })
            .join("") +
          `<div class="rbar-legend"><span class="k"><i style="--c:var(--fg-muted)"></i>citable range</span><span class="k"><i class="dashed" style="--c:var(--fg-muted)"></i>shown, not citable</span></div></div>`
        );
      })
      .join("");

    const cs = Z.cost_of_search || {};
    $("blocks").innerHTML =
      block({
        eyebrow: "Value by branch",
        title: "Each branch of the value tree, low to high",
        lede: "The branches do not overlap, so none is counted twice. Each hue belongs to one branch everywhere in this lab, and its process code is printed beside it.",
        body: groups,
      }) +
      block({
        eyebrow: "What may be quoted",
        title: citable.length ? "The ranges you can put in front of a board" : "Nothing may be quoted yet",
        body:
          `<div class="card reveal">` +
          (citable.length
            ? `<ul class="plain">${citable.map((x) => `<li class="row" style="justify-content:space-between"><span><span class="code-tag"><span class="swatch" style="--c:var(--${esc(x.colour)})"></span>${esc(x.code)}</span> ${esc(x.branch)}</span><span class="fig">${single(x) ? `${esc(txt(x.low))} ${esc(x.unit)}, a single value` : `${esc(txt(x.low))} to ${esc(txt(x.high))} ${esc(x.unit)}`}</span>${LAB.caveat(x.caveat)}</li>`).join("")}</ul>`
            : `<p class="muted" style="margin:0">No range has passed its test yet.</p>`) +
          `<div class="note info" style="margin-top:14px"><strong>The rule</strong><br>${esc(Z.rule)}</div></div>`,
      }) +
      block({
        eyebrow: "What the search cost",
        title: "The price of finding these ranges",
        body:
          `<div class="card reveal"><div class="tiles">${tile(cs.runs, "", "Runs")}${`<div class="tile"><span class="metric">${esc(txt(cs.usd_low, 2))} to ${esc(txt(cs.usd_high, 2))}<span class="u">USD</span></span><div class="metric-sub">Per run, low to high</div></div>`}${tile(cs.usd_total, "USD", "All runs together", "", 2)}</div>` +
          `<p class="cap-note">${esc(cs.basis || "")}</p></div>`,
      });

    finish(
      [["Ranges", src(Z.source)], ["Runs", provTag(Z.provenance_label)]],
      `<dl class="kv">${rows.map((x) => `<dt>${esc(x.code)}</dt><dd>${esc(x.basis)}<br><span class="dim mono">citable: ${esc(String(x.citable))} · status: ${esc(x.status)}</span></dd>`).join("")}</dl>`,
      "basis of every range"
    );
  }

  /* ---------- 4 · The solution ---------- */
  async function theSolution() {
    const r = await load(["/api/v2/solution", "/api/v2/teams"]);
    if (!r) return;
    const [SOL, TM] = r;
    const stages = SOL.stages || [];
    const S = (id) => stages.find((x) => x.id === id) || {};
    const managedLimit = (TM.limits || []).find((x) => /managed/i.test(x.item));
    $("lede-data").innerHTML =
      `So far the controller has generated ${t(S("controller").count, "", 0)} programs, the evaluator has scored ${t(S("evaluator").count, "", 0)}, ` +
      `and the rules have rejected ${t(S("invariants").count, "", 0)}. Every program came from the ${provTag(SOL.provenance_label)}; ` +
      `${t(S("managed").count, "", 0)} managed runs exist.`;

    const loop = stages
      .map(
        (x, i) =>
          `<div class="flow-node${x.id === "human_review" ? " signoff" : ""}"><div class="node-head"><span class="node-step">${i + 1} · ${esc(x.name)}</span>` +
          (x.id === "managed" && managedLimit ? badge(managedLimit.ok ? "READY" : "NOT PROVISIONED", managedLimit.ok ? "b-ok" : "b-warn") : "") +
          `</div><div class="stat">${countEl(x.count, "", 0, "")}</div><div class="stat-l">${esc(x.count_label)}</div><div class="what">${esc(x.what)}</div></div>`
      )
      .join("");

    const analyst = (TM.teams || []).find((x) => Array.isArray(x.tools)) || {};
    const flow = (analyst.stages || [])
      .map(
        (s, i) =>
          (i ? '<div class="flow-arrow" aria-hidden="true">↓</div>' : "") +
          `<div class="flow-step">${esc(s.step)} · ${esc(s.role)}</div><div class="flow-node${s.step === 4 ? " signoff" : ""}"><div class="who">${esc(s.name)}</div><div class="what">${esc(s.detail)}</div></div>`
      )
      .join("");
    const tools = (analyst.tools || [])
      .map((x) => `<span class="pill">${esc(x)}${(analyst.signoff_tools || []).includes(x) ? " · SIGN-OFF" : ""}</span>`)
      .join("");

    $("blocks").innerHTML =
      block({
        eyebrow: "The evolution loop",
        title: `${stages.length} gates, each one counted`,
        lede: "Read left to right. A number under each gate is how many programs reached it or were stopped there, across every finished run.",
        body: `<div class="card reveal"><div class="loop">${loop}</div>` +
          (managedLimit ? `<p class="cap-note">Managed AlphaEvolve service: ${esc(managedLimit.text)}</p>` : "") + `</div>`,
      }) +
      block({
        eyebrow: "How a question moves",
        title: `Asking the ${esc(analyst.name || "analyst")}`,
        lede: `One agent, ${esc(analyst.pattern || "")}, on ${esc(analyst.model || "a model not named in the data")}. It reads the lab tables through read-only tools and can only propose a write; a person confirms it.`,
        body:
          `<div class="bento"><div class="card c7 reveal">${flow}</div><div class="card c5 reveal"><div class="card-cap">Tools it may call</div><div class="chips">${tools}</div>` +
          `<div class="card-cap" style="margin-top:16px">Tables it reads</div><div class="chips">${(analyst.reads || []).map((x) => `<span class="pill">${esc(x)}</span>`).join("")}</div></div></div>`,
      }) +
      block({
        eyebrow: "Demo and production",
        title: "What the demo simulates, and what production uses",
        body:
          `<div class="card reveal"><div class="table-scroll"><table class="data"><thead><tr><th>Layer</th><th>The demo simulates</th><th>Production uses</th></tr></thead><tbody>` +
          (SOL.architecture || []).map((x) => `<tr><td><b>${esc(x.layer)}</b></td><td class="wrap">${esc(x.demo)}</td><td class="wrap">${esc(x.production)}</td></tr>`).join("") +
          `</tbody></table></div></div>`,
      });

    const loopTeam = (TM.teams || []).find((x) => x.id === "evolution_loop") || {};
    finish(
      [["Stages", src(SOL.source)], ["Teams and limits", src(TM.source)], ["Runs", provTag(SOL.provenance_label)]],
      `<p class="small">The evolution loop as the teams endpoint describes it, with its own counters.</p><dl class="kv">` +
        (loopTeam.stages || [])
          .map((s) => `<dt>${esc(s.step)} · ${esc(s.role)}</dt><dd>${esc(s.name)}: ${esc(s.detail)}<br><span class="mono dim">${esc(s.stat && s.stat.label)}: ${esc(typeof (s.stat || {}).value === "object" ? JSON.stringify(s.stat.value) : txt(s.stat && s.stat.value, 0))}</span></dd>`)
          .join("") +
        `</dl><p class="small" style="margin-top:14px">What stands between this lab and a production run:</p><ul class="plain">` +
        (TM.limits || []).map((x) => `<li>${badge(x.ok ? "READY" : "BLOCKED", x.ok ? "b-ok" : "b-warn")} <b>${esc(x.item)}</b>: ${esc(x.text)}</li>`).join("") +
        "</ul>",
      "stage counters and limits"
    );
  }

  /* ---------- 5 · The proof ---------- */
  async function theProof() {
    const r = await load(["/api/v2/proof"]);
    if (!r) return;
    const [P] = r;
    const a = P.adk || {}, g = P.grounding || {}, s = P.safety || {}, m = P.mutation || {};
    $("lede-data").innerHTML =
      `Agent evaluations passed ${t(a.passed, "", 0)} of ${t(a.total, "", 0)}. Grounding probes: ${t(g.grounded, "", 0)} of ${t(g.total, "", 0)} grounded. ` +
      `Safety probes: ${t(s.passed, "", 0)} of ${t(s.total, "", 0)}. Mutation checks: the suite caught ${t(m.detected, "", 0)} of ${t(m.total, "", 0)} deliberate breaks.`;

    const runs = (P.runs || []).slice().sort(byStart);
    const pc = P.policy_catches || {};
    const ex = P.worked_grounding_example;
    const exHtml = ex
      ? `<div class="card reveal"><div class="card-cap">The question<span class="spacer"></span>${badge(ex.label, ex.label === "GROUNDED" ? "b-ok" : "b-warn")}</div>` +
        `<p class="quote">${esc(ex.question)}</p>` +
        `<div class="card-cap" style="margin-top:16px">Tools it called</div><div class="chips">${(ex.tools || []).map((x) => `<span class="pill">${esc(x)}</span>`).join("")}</div>` +
        `<div class="card-cap" style="margin-top:16px">Known answer</div><p style="margin:0">${(ex.truth || []).map((x) => `${t(x[0], "", places(x[0]))} within ${t(x[1], "", places(x[1]))}`).join("; ") || LAB.NITD}</p>` +
        `<div class="card-cap" style="margin-top:16px">What the analyst replied, first attempt</div><div class="answer" id="ex-reply"></div></div>`
      : `<div class="card reveal">${LAB.NITD}</div>`;

    $("blocks").innerHTML =
      block({
        eyebrow: "The checks",
        title: "Every test, with its denominator",
        body:
          `<div class="card reveal"><div class="tiles">` +
          ofTile(a.passed, a.total, "Agent evaluation cases passed", `first attempt: ${esc(txt(a.first_attempt, 0))} of ${esc(txt(a.total, 0))}${(a.failures || []).length ? ` · not passed: ${esc(a.failures.join(", "))}` : ""}`) +
          ofTile(g.grounded, g.total, "Grounding probes grounded", (g.unverifiable || []).length ? `unverifiable: ${esc(g.unverifiable.join(", "))}` : "none unverifiable") +
          ofTile(s.passed, s.total, "Safety probes passed", `${esc(txt((s.probes || []).length, 0))} probes, named in the technical detail`) +
          ofTile(m.detected, m.total, "Deliberate breaks the tests caught", "a gate is removed and the suite must go red") +
          `</div><div class="card-cap" style="margin-top:16px">Unit and integration tests, as last recorded</div>` +
          `<ul class="plain">${(P.pytest || []).map((x) => `<li class="mono small">${esc(x)}</li>`).join("") || `<li>${LAB.NITD}</li>`}</ul></div>`,
      }) +
      block({
        eyebrow: "The runs",
        title: "Each run, its held-out outcome and where it came from",
        body:
          `<div class="card reveal"><div class="table-scroll"><table class="data"><thead><tr><th>Run</th><th>Outcome</th><th class="num">Held-out delta (JPY M)</th><th>Invalid by kind</th></tr></thead><tbody>` +
          runs
            .map((x) => `<tr><td><span class="mono rid">${esc(x.run_id)}</span><span class="lbl">${esc(x.provenance)}</span></td><td>${runStatus(x)}${LAB.caveat(x.caveat)}</td>` +
              `<td class="num">${deltaCell(x)}</td><td class="mono small">${esc(Object.entries(x.invalid_by_kind || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "none")}</td></tr>`)
            .join("") +
          `</tbody></table></div></div>`,
      }) +
      block({
        eyebrow: "Invariant catches",
        title: "Rules that held",
        body:
          `<div class="card reveal"><div class="tiles">${tile(pc.candidates, "", "Candidates rejected by a rule")}${tile(pc.invalid_that_reached_population, "", "Of those, reached the population")}` +
          Object.entries(pc.by_invariant || {}).map(([k, v]) => tile(v, "", `Rule: ${k.replace(/_/g, " ")}`)).join("") +
          `</div></div>`,
      }) +
      block({
        eyebrow: "One worked example",
        title: "A figure read off the data, not made up",
        lede: "The probe asks a question whose answer is known from the tables, then checks the reply against it.",
        body: exHtml,
      });
    if (ex && $("ex-reply")) LAB.renderRich($("ex-reply"), ex.reply_excerpt);

    finish(
      [["Evaluation results", src(P.source)], ["Runs", provTag(P.provenance_label)]],
      `<dl class="kv"><dt>Safety probes</dt><dd class="mono">${esc((s.probes || []).join(", ") || "NOT IN THE DATA")}</dd>` +
        `<dt>Agent cases not passed</dt><dd class="mono">${esc((a.failures || []).join(", ") || "none")}</dd>` +
        `<dt>Test runs</dt><dd class="mono">${esc((P.pytest || []).join(" | ") || "NOT IN THE DATA")}</dd></dl>`,
      "probe names and raw results"
    );
  }

  ({ case: theCase, gap: theGap, prize: thePrize, solution: theSolution, proof: theProof }[chapter] || (() => {}))();
})();
