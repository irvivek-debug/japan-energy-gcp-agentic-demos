/* Retail Energy Desk v2: Value. The metrics the agents move, each as a range: this site from the data, the outside
 * band only where a verified one is held (cited), otherwise the honest "NO VERIFIED BENCHMARK HELD".
 * Every figure comes from /api/story/value; the scale ends are computed from those figures. */
(function () {
  "use strict";
  const esc = (v) => Shell.esc(v);
  const $ = (id) => document.getElementById(id);
  const isNum = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

  /** Decimal places by unit: money per kWh to the sen, percentages and energy to one place. */
  const dpFor = (unit) => (/JPY/.test(unit || "") ? 2 : 1);
  /** Smallest "nice" number (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8 times a power of ten) at or above v: a scale end, not a figure. */
  function niceCeil(v) {
    if (!(v > 0)) return 1;
    const e = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * e >= v - 1e-9) return m * e;
    return 10 * e;
  }
  function code(id) { return String(id || "?").replace(/[^a-z0-9]/gi, "").slice(0, 3).toUpperCase(); }
  function rangeText(lo, hi, unit, dp) {
    if (!isNum(lo) && !isNum(hi)) return null;
    if (!isNum(hi) || Desk.num(lo, dp) === Desk.num(hi, dp)) return { fig: Desk.num(isNum(lo) ? lo : hi, dp), unit };
    return { fig: `${Desk.num(lo, dp)} to ${Desk.num(hi, dp)}`, unit };
  }
  /** Where the site's range sits relative to the band, in words (colour is never the only signal). */
  function where(site, band) {
    if (!band || !isNum(band.low) || !isNum(band.high)) return "";
    const lo = Number(site.low), hi = Number(site.high);
    if (lo >= band.low && hi <= band.high) return "This site sits inside the outside band";
    if (lo > band.high) return "This site sits above the whole outside band";
    if (hi < band.low) return "This site sits below the whole outside band";
    if (lo < band.low && hi > band.high) return "This site's range spans the whole outside band";
    return hi > band.high ? "This site's range runs above the outside band" : "This site's range runs below the outside band";
  }

  function row(m) {
    const unit = m.unit || "";
    const dp = dpFor(unit);
    const site = m.site || {};
    const band = m.band && isNum(m.band.low) && isNum(m.band.high) ? m.band : null;
    const hasSite = isNum(site.low) || isNum(site.high);
    const sLo = Number(isNum(site.low) ? site.low : site.high), sHi = Number(isNum(site.high) ? site.high : site.low);
    const rt = rangeText(site.low, site.high, unit, dp);

    let bar = "", scale = "", aria = "";
    if (hasSite) {
      const all = [sLo, sHi].concat(band ? [Number(band.low), Number(band.high)] : []);
      const lo = Math.min(0, ...all) < 0 ? -niceCeil(-Math.min(...all)) : 0;
      const hi = niceCeil(Math.max(...all));
      const pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
      const w = Math.max(pct(sHi) - pct(sLo), 1);
      const left = Math.min(pct(sLo), 100 - w);
      bar = `${band ? `<i class="band" style="left:${pct(band.low).toFixed(2)}%;width:${(pct(band.high) - pct(band.low)).toFixed(2)}%"></i>` : ""}` +
        `<i class="site" style="left:${left.toFixed(2)}%;width:${w.toFixed(2)}%"></i>` +
        (sLo === sHi ? `<b class="site" style="left:calc(${pct(sLo).toFixed(2)}% - 1px)"></b>` : "");
      scale = `<div class="vbar-scale"><span>${esc(Desk.f(lo, unit, lo % 1 ? dp : 0))}</span><span>${esc(Desk.f(hi, unit, hi % 1 ? dp : 0))}</span></div>`;
      aria = `This site ${rt.fig} ${unit}` + (band ? `; outside band ${Desk.num(band.low, dp)} to ${Desk.num(band.high, dp)} ${unit}` : "; no outside band held") +
        `; scale ${Desk.num(lo, 0)} to ${Desk.num(hi, hi % 1 ? dp : 0)} ${unit}`;
    }
    const noBand = !band;
    return `<div class="vrow">
      <span class="vcode" style="color:var(--fg-muted)" aria-hidden="true">${esc(code(m.id))}</span>
      <div>
        <h3>${esc(m.name || "Unnamed metric")}</h3>
        <div class="mech">Moved by <span class="mono">${esc(m.moved_by || "NOT IN THE DATA")}</span></div>
        <div class="rng">${rt ? `${esc(rt.fig)}<small>${esc(unit)}</small>` : '<span class="metric gap">NOT IN THE DATA</span>'}</div>
        ${site.label ? `<div class="mech">${esc(site.label)}</div>` : ""}
        ${hasSite ? `<div class="vbar" role="img" aria-label="${esc(aria)}">${bar}</div>${scale}` : ""}
        ${(() => { const w = hasSite ? where({ low: sLo, high: sHi }, band) : "No site figure in the data"; return w ? `<div class="where">${esc(w)}</div>` : ""; })()}
        <div class="basis">${noBand
          ? `<span class="nodata">${esc(m.band_label || "NO VERIFIED BENCHMARK HELD")}</span>`
          : `Outside band ${esc(Desk.num(band.low, dp))} to ${esc(Desk.f(band.high, unit, dp))}: ${esc(m.band_label || "")}`}${m.cite ? `<br>Source: ${esc(m.cite)}` : ""}</div>
      </div>
    </div>`;
  }

  async function main() {
    Shell.mountNav("workspace", "value");
    try {
      const v = await Shell.api("/api/story/value");
      const metrics = Array.isArray(v.metrics) ? v.metrics : [];
      const banded = metrics.filter((m) => m.band && isNum(m.band.low)).length;
      $("asof").textContent = `Snapshot ${String(v.as_of || "NOT IN THE DATA").replace("T", " ")} JST · ${metrics.length} figures · ${banded} with a verified outside band`;
      $("metrics").innerHTML = metrics.length ? metrics.map(row).join("") : '<p class="metric gap">NOT IN THE DATA</p>';
    } catch (e) {
      Desk.fail($("metrics"), e);
    }
    $("prov").innerHTML = await Desk.provenance();
    Motion.reveal();
  }
  main();
})();
