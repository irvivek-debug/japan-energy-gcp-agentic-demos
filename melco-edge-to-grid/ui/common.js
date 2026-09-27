/* Shared helpers for UI v2: formatting, research citations, ECharts on the kit tokens, sparklines, a safe markdown
 * subset, the SSE agent client, and the sign-off wiring. Holds no figures of its own. */
(function () {
  const esc = (v) => window.Shell.esc(v);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  const num = (v, dp = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "NOT IN THE DATA"
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }));
  const jpy = (v) => (v === null || v === undefined ? "NOT IN THE DATA" : `${num(v)} JPY`);
  const mjpy = (v, dp = 2) => (v === null || v === undefined ? "NOT IN THE DATA" : `${num(v / 1e6, dp)} M JPY`);

  // ---------- research facts (cited) ----------
  let research = null;
  async function facts() { research = research || (await window.Shell.api("/api/research")); return research; }
  function fact(r, key, dp) {
    const f = r.facts[key];
    return f ? `${num(f.value, dp === undefined ? (Number.isInteger(f.value) ? 0 : 2) : dp)} ${f.unit}` : "NO VERIFIED BENCHMARK HELD";
  }
  const citeOf = (r, key) => (r.facts[key] ? r.facts[key].cite : (r.statements[key] || {}).cite || "");

  // ---------- charts ----------
  function palette() { return ["--b1", "--b2", "--b3", "--b4", "--b5", "--b6"].map(css); }
  function axis(extra = {}) {
    return {
      axisLine: { lineStyle: { color: css("--border") } }, axisTick: { show: false },
      axisLabel: { color: css("--fg-muted"), fontFamily: "JetBrains Mono", fontSize: 10.5 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)", width: 1 } }, ...extra,
    };
  }
  function tooltip(fmtv) {
    return { trigger: "axis", backgroundColor: css("--surface-high"), borderColor: css("--border"), textStyle: { color: css("--fg"), fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: css("--fg-dim") } }, valueFormatter: fmtv };
  }
  const legend = (data) => ({ data, top: 0, type: "scroll", textStyle: { color: css("--fg-muted"), fontSize: 11, fontFamily: "JetBrains Mono" },
    itemWidth: 12, itemHeight: 8, icon: "roundRect", pageIconColor: css("--fg-muted"), pageTextStyle: { color: css("--fg-muted") } });
  const charts = [];
  function chart(el) {
    if (!window.echarts) { el.innerHTML = '<p class="muted">Chart library unavailable.</p>'; return null; }
    const c = window.echarts.init(el, null, { renderer: "canvas" });
    charts.push(c);
    return c;
  }
  window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

  // ---------- sparkline (inline SVG) ----------
  function spark(values, { w = 300, h = 54, color = css("--accent"), upto = null } = {}) {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
    if (pts.length < 2) return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="no data"></svg>`;
    const vs = pts.map((p) => p[1]);
    const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
    const X = (i) => (i / (values.length - 1)) * (w - 4) + 2, Y = (v) => h - 4 - ((v - lo) / span) * (h - 8);
    const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const cur = upto !== null && values[upto] !== null && values[upto] !== undefined
      ? `<line x1="${X(upto)}" x2="${X(upto)}" y1="0" y2="${h}" stroke="${css("--fg-dim")}" stroke-width="1"/><circle cx="${X(upto)}" cy="${Y(values[upto])}" r="3" fill="${color}"/>` : "";
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="trend"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>${cur}</svg>`;
  }

  // ---------- markdown subset (escaped first) ----------
  function md(text) {
    const lines = esc(text || "").split("\n");
    let html = "", list = null, table = [];
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    const flush = () => {
      if (!table.length) return;
      const rows = table.filter((r) => !/^\|\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
      html += `<table>${rows.map((r, i) => `<tr>${r.map((c) => (i ? `<td>${c}</td>` : `<th>${c}</th>`)).join("")}</tr>`).join("")}</table>`;
      table = [];
    };
    const close = () => { if (list) { html += `</${list}>`; list = null; } };
    for (const raw of lines) {
      const l = raw.trimEnd();
      if (/^\s*\|/.test(l)) { close(); table.push(l.trim()); continue; }
      flush();
      const h = l.match(/^#{1,4}\s+(.*)/), b = l.match(/^\s*[*-]\s+(.*)/), n = l.match(/^\s*\d+\.\s+(.*)/);
      if (h) { close(); html += `<h4>${inline(h[1])}</h4>`; }
      else if (b || n) { const t = b ? "ul" : "ol"; if (list !== t) { close(); html += `<${t}>`; list = t; } html += `<li>${inline((b || n)[1])}</li>`; }
      else if (!l.trim()) close();
      else { close(); html += `<p>${inline(l)}</p>`; }
    }
    flush(); close();
    return html;
  }

  // ---------- agent SSE client ----------
  const AGENT_LABEL = {
    optimization_orchestrator: "Optimization Orchestrator", market_intelligence_agent: "Market Intelligence", factory_interlock_agent: "Factory Interlock",
    bess_strategy_agent: "BESS Strategy", asset_health_agent: "Asset Health", gain_share_agent: "Gain Share", safety_auditor: "Safety Auditor",
  };
  let sessionId = null;
  async function ask(message, onEvent) {
    const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id: sessionId }) });
    if (!res.ok || !res.body) throw new Error(`chat: HTTP ${res.status}`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "", final = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!chunk.startsWith("data: ")) continue;
        const e = JSON.parse(chunk.slice(6));
        if (e.type === "session") sessionId = e.session_id;
        if (e.type === "text" && e.author === "optimization_orchestrator") final += e.text;
        onEvent && onEvent(e, final);
      }
    }
    return final;
  }

  // ---------- sign-off ----------
  async function openAction(a, after) {
    window.SignOff.open(a, {
      onConfirm: async (x) => { const r = await fetch(`/api/actions/${x.id}/confirm`, { method: "POST" }); if (!r.ok) throw new Error(`HTTP ${r.status}`); const j = await r.json(); after && after(); return j; },
      onReject: async (x) => { const r = await fetch(`/api/actions/${x.id}/reject`, { method: "POST" }); const j = await r.json(); after && after(); return j; },
    });
  }
  function actionItem(a) {
    const st = a.status === "pending" ? "b-warn" : a.status === "executed_sandbox" ? "b-ok" : "b-crit";
    return `<div class="queue-item"><div class="row"><span class="badge ${st}">${esc(a.status.replaceAll("_", " "))}</span>
      <span class="badge b-idle">${esc((a.kind || "").replaceAll("_", " "))}</span>${a.audit ? `<span class="badge ${a.audit === "APPROVED" ? "b-ok" : "b-warn"}">audit ${esc(a.audit)}</span>` : ""}
      <span class="mono dim">${esc(a.id)}</span></div><p>${esc(a.summary)}</p>
      <button class="btn primary" data-open="${esc(a.id)}">${a.status === "pending" ? "Review and sign off" : "View record"}</button></div>`;
  }
  async function renderQueue(el, countEl) {
    const list = await window.Shell.api("/api/actions");
    const pending = list.filter((a) => a.status === "pending");
    if (countEl) countEl.textContent = String(pending.length);
    el.innerHTML = list.length ? list.map(actionItem).join("")
      : `<p class="muted">Nothing is waiting. Agents can only propose; every change waits here for a ${window.SignOff.HOLD_MS / 1000}-second hold.</p>`;
    el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => {
      const a = list.find((x) => x.id === b.dataset.open);
      openAction(a, () => renderQueue(el, countEl));
    }));
    return list;
  }

  function provRows(meta, tables, extra = []) {
    const t = (tables || []).map((x) => `<code>${esc(x)}</code>`).join(" ");
    return [
      ["Tables", t || "none"],
      ["Dataset", `<code>${esc(meta.dataset)}</code> (${esc(meta.backend)})`],
      ["Generator", `<code>${esc(meta.generator)}</code>, seed ${esc(meta.seed)}`],
      ["Data window", `telemetry ${esc(meta.windows.telemetry[0])} to ${esc(meta.windows.telemetry[1])}; site history from ${esc(meta.windows.site_history[0])}`],
      ["Demo clock", esc(meta.demo_now.replace("T", " ")) + " JST"],
      ["Research", `<code>${esc(meta.research)}</code>`],
      ...extra,
    ];
  }

  window.UI = { esc, css, num, jpy, mjpy, facts, fact, citeOf, palette, axis, tooltip, legend, chart, spark, md, ask, AGENT_LABEL,
    openAction, renderQueue, provRows };
})();
