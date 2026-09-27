/* Workspace · Value. The measures the runs move, each as the champions' range with the seed marked on the same
 * scale and the industry band beside it (or the honest statement that none is held). All from /api/v2/value.
 */
(async function () {
  const { $, esc, t, txt, isNum, badge, footer, provTag, rangeBar, scale, counts } = window.LAB;
  LAB.nav("workspace", "value");

  let V;
  try {
    V = await Shell.api("/api/v2/value");
  } catch (e) {
    $("lede-data").innerHTML = LAB.errorNote("/api/v2/value", e);
    return;
  }
  const metrics = V.metrics || [];
  const held = metrics.filter((m) => m.fold === "holdout").length;
  $("lede-data").innerHTML =
    `${t(metrics.length, "", 0)} measures. ${t(held, "", 0)} are read on the held-out fold, the rest on training data only and marked so. ` +
    `Every champion came from the ${provTag(V.provenance_label)}.`;

  /** Where the seed sits against the champions' range, in words, and whether that direction is the better one. */
  function sits(m) {
    const r = m.site_range || {};
    if (!isNum(m.site_seed) || !isNum(r.low) || !isNum(r.high)) return "Where this site sits is NOT IN THE DATA.";
    const lo = Math.min(r.low, r.high), hi = Math.max(r.low, r.high);
    const where = m.site_seed < lo ? "below" : m.site_seed > hi ? "above" : "inside";
    if (where === "inside") return "The seed sits inside the champions' range.";
    const champs = where === "above" ? "lower" : "higher";
    const good = m.better === "lower" ? champs === "lower" : m.better === "higher" ? champs === "higher" : null;
    return `The seed sits ${where} the champions' range: every champion is ${champs}` +
      (good === null ? (m.better === "context" ? ". Neither direction is better on its own; read it against the band." : `. Better here means ${m.better}, so read it against the band.`) : good ? ", which is better here." : ", which is worse here.");
  }
  const hue = (m) => (/^tariff/.test(m.id) ? "var(--b3)" : "var(--b1)"); // same hues as the prize branches they feed

  $("metrics").innerHTML = metrics
    .map((m) => {
      const r = m.site_range || {};
      const sc = scale([r.low, r.high, m.site_seed]);
      const band = m.band && m.band.source
        ? `<div class="cap-note" style="text-transform:uppercase">${esc(m.band.text)} · ${esc(m.band.source)}</div>`
        : `<div class="cap-note">NO VERIFIED BENCHMARK HELD</div>`;
      return (
        `<div class="card c6 reveal"><div class="card-cap">${esc(m.label)}<span class="spacer"></span>` +
        badge(m.fold === "holdout" ? "HELD-OUT FOLD" : "TRAIN ONLY", m.fold === "holdout" ? "b-ok" : "b-warn") +
        `</div><div class="row" style="justify-content:space-between;align-items:baseline">` +
        `<span class="metric" style="font-size:24px">${isNum(r.low) ? `${esc(txt(r.low))} to ${esc(txt(r.high))}` : LAB.NITD}<span class="u">${esc(m.unit)}</span></span>` +
        `<span class="mono small">Seed ${t(m.site_seed, m.unit)}</span></div>` +
        `<div class="metric-sub">Champions, every run of this problem · better: ${esc(m.better)}</div>` +
        rangeBar({ low: r.low, high: r.high, marker: m.site_seed, min: sc.min, max: sc.max, colour: hue(m), label: m.label, unit: m.unit, markerLabel: "seed" }) +
        `<div class="rbar-legend"><span class="k"><i style="--c:${hue(m)}"></i>champions' range</span><span class="k"><b></b>seed</span></div>` +
        `<p class="small" style="margin:12px 0 0">${esc(sits(m))}</p>` +
        `<div class="card-cap" style="margin:14px 0 0;border:0;padding:0">Industry band</div>${band}</div>`
      );
    })
    .join("");

  $("prov").innerHTML =
    Shell.technicalDrawer(
      `<div class="table-scroll"><table class="data"><thead><tr><th>Measure</th><th>Fold</th><th class="num">Seed</th><th class="num">Low</th><th class="num">High</th><th>Unit</th></tr></thead><tbody>` +
        metrics.map((m) => `<tr><td class="mono">${esc(m.id)}</td><td class="mono">${esc(m.fold)}</td><td class="num">${t(m.site_seed, "", 4)}</td><td class="num">${t((m.site_range || {}).low, "", 4)}</td><td class="num">${t((m.site_range || {}).high, "", 4)}</td><td>${esc(m.unit)}</td></tr>`).join("") +
        "</tbody></table></div>",
      "raw values at four places"
    ) +
    footer([
      ["Measures", `<span class="mono">${esc((V.source || []).join(", "))}</span>`],
      ["Runs", provTag(V.provenance_label)],
    ]);
  Motion.reveal();
  counts();
})();
