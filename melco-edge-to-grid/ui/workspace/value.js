/* Workspace · Value: the metrics the agents move, each as a range with the industry band and where this site sits. */
(async function () {
  const { esc, num } = UI;
  await Shell.mountNav("workspace", "/workspace/value.html");
  const root = document.getElementById("page");
  try {
    const [v, meta] = await Promise.all([Shell.api("/api/value"), Shell.api("/api/meta")]);
    const row = (m) => {
      const pts = [m.site_low, m.site_high, m.now, m.target, ...(m.band || [])].filter((x) => x !== null && x !== undefined);
      const lo0 = Math.min(...pts), hi0 = Math.max(...pts), pad = (hi0 - lo0) * 0.12 || Math.abs(hi0) * 0.1 || 1;
      const lo = lo0 - pad, hi = hi0 + pad, X = (x) => `${(100 * (x - lo) / (hi - lo)).toFixed(2)}%`;
      const band = m.band ? `<div class="band" style="left:${X(m.band[0])};width:calc(${X(m.band[1])} - ${X(m.band[0])})" title="${esc(m.band_text)}"></div>` : "";
      const s0 = m.site_low ?? m.site_high, s1 = m.site_high ?? m.site_low;
      const site = s0 !== null && s0 !== undefined ? `<div class="site" style="left:${X(Math.min(s0, s1))};width:max(4px, calc(${X(Math.max(s0, s1))} - ${X(Math.min(s0, s1))}))"></div>` : "";
      const now = m.now !== null && m.now !== undefined ? `<div class="mark" style="left:${X(m.now)}" title="now"></div>` : "";
      const tgt = m.target !== null && m.target !== undefined ? `<div class="tgt" style="left:${X(m.target)}" title="target"></div>` : "";
      const dp = Math.abs(hi0) < 20 ? 2 : m.unit === "%" ? 1 : 0;
      return `<div class="vrow reveal"><div><h4>${esc(m.metric)}</h4><div class="dim mono" style="font-size:11px">moved by ${esc(m.agent)}</div></div>
        <div><div class="vscale" role="img" aria-label="${esc(m.metric)}: site ${num(s0, dp)} to ${num(s1, dp)} ${esc(m.unit)}">${band}<div class="track"></div>${site}${now}${tgt}</div>
          <div class="vlabels"><span>${num(lo, dp)}</span><span>${esc(m.unit)}</span><span>${num(hi, dp)}</span></div></div>
        <div><div class="metric" style="font-size:20px">${num(s0, dp)}${s1 !== s0 ? ` to ${num(s1, dp)}` : ""}<span class="u">${esc(m.unit)}</span></div>
          <div class="dim" style="font-size:12px">${esc(m.reading)}</div>
          <div class="mono" style="font-size:10.5px;color:var(--fg-muted);margin-top:4px">${m.band_text === "NO VERIFIED BENCHMARK HELD" ? '<span class="badge b-idle">NO VERIFIED BENCHMARK HELD</span>' : esc(m.band_text)}${m.cite ? `<span class="cite">${esc(m.cite)}</span>` : ""}</div></div></div>`;
    };
    root.innerHTML = `<section class="hero read reveal"><div class="eyebrow">Workspace · Value</div><h1>What the agents move, and where this plant sits</h1>
      <p class="lede">Each line is a range measured in this plant's data. The accent bar is the site, the white tick is now, the dotted line is the target, and the dashed box is the published band where one exists.</p>
      <div class="legend"><span><span class="badge b-info">site range</span></span><span>| now</span><span>: target</span><span>[ ] industry band</span></div></section>
      <section><div class="card reveal">${v.metrics.map(row).join("")}</div></section>
      ${Shell.provenance(UI.provRows(meta, v.source))}`;
  } catch (e) {
    root.innerHTML = `<div class="note crit"><strong>Data unavailable</strong><br>${esc(e.message)}</div>`;
  }
  Motion.reveal();
})();
