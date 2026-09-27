/* Retail Energy Desk v2 helpers shared by every screen (loaded after kit/shell.js, kit/motion.js, kit/signoff.js).
 *
 * Nothing here holds a figure. Formatting, a safe markdown renderer for agent text (agent text is untrusted: one
 * customer bill carries a prompt injection), the SSE client for /api/chat, the ECharts look of the kit, a sparkline,
 * and the one road to an approval: Desk.openAction -> SignOff.open. */
(function () {
  const esc = (v) => window.Shell.esc(v);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const HUES = ["--b1", "--b2", "--b3", "--b4", "--b5", "--b6"];

  function num(v, dp = 1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  /** Money: 21.1M JPY, 0.59B JPY. Missing renders as text, never as zero. */
  function money(v, { dp } = {}) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "NOT IN THE DATA";
    const a = Math.abs(v), s = v < 0 ? "-" : "";
    if (a >= 1e9) return `${s}${num(a / 1e9, dp ?? 2)}B JPY`;
    if (a >= 1e6) return `${s}${num(a / 1e6, dp ?? 1)}M JPY`;
    if (a >= 1e3) return `${s}${num(a / 1e3, dp ?? 0)}k JPY`;
    return `${s}${num(a, 0)} JPY`;
  }
  /** A money range on one scale: "0.21B to 0.59B JPY". */
  function moneyRange(lo, hi) {
    if ([lo, hi].some((v) => v === null || v === undefined || Number.isNaN(Number(v)))) return "NOT IN THE DATA";
    const m = Math.max(Math.abs(lo), Math.abs(hi));
    const [d, s] = m >= 1e8 ? [1e9, "B"] : m >= 1e5 ? [1e6, "M"] : [1e3, "k"];
    const dp = d === 1e9 ? 2 : 1;
    return `${num(lo / d, dp)}${s} to ${num(hi / d, dp)}${s} JPY`;
  }
  /** Money split for counting: {value, unit, dp} such that value + unit prints like money(v). */
  function moneyParts(v) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
    const a = Math.abs(v);
    if (a >= 1e9) return { value: v / 1e9, unit: "B JPY", dp: 2 };
    if (a >= 1e6) return { value: v / 1e6, unit: "M JPY", dp: 1 };
    if (a >= 1e3) return { value: v / 1e3, unit: "k JPY", dp: 0 };
    return { value: v, unit: "JPY", dp: 0 };
  }
  /** A figure with its unit for use inside text (no HTML). */
  function f(v, unit, dp = 1) {
    const n = num(v, dp);
    return n === null ? "NOT IN THE DATA" : unit ? (unit === "%" ? `${n}%` : `${n} ${unit}`) : n;
  }
  function el(id) { return document.getElementById(id); }
  function srcShort(s) { return String(s).replace(/^[a-z0-9_]+_demo\./, ""); }
  function cites(list) { return (list || []).map((s) => `<span class="pill">${esc(srcShort(s))}</span>`).join(" "); }

  /* ---------------------------------------------------------------- safe markdown (escape first, then format) */
  /** Citations stay in the text but read compactly: "[dataset.table, ...]" shows as a small mono "[table, ...]". */
  function cites2(s) {
    return s.replace(/\[([^\[\]]*?(?:_demo\.|\.md|\.txt)[^\[\]]*?)\]/g, (m, inner) => `<span class="src">[${inner.replace(/[a-z0-9_]+_demo\./g, "")}]</span>`);
  }
  function inline(s) {
    return cites2(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
  }
  function md(text) {
    const lines = esc(text || "").split("\n");
    const out = [];
    let list = null, table = null, para = [];
    const flush = () => {
      if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
      if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; }
      if (table) {
        const rows = table.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
        const cells = (r) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => inline(c.trim()));
        const [head, ...body] = rows;
        out.push(`<div class="table-scroll"><table class="data"><thead><tr>${cells(head).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${
          body.map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        table = null;
      }
    };
    for (const raw of lines) {
      const l = raw.trimEnd();
      let m;
      if (!l.trim()) { flush(); continue; }
      if (/^\s*\|.*\|\s*$/.test(l)) { if (!table) { flush(); table = []; } table.push(l); continue; }
      if ((m = l.match(/^(#{1,4})\s+(.*)$/))) { flush(); const n = Math.min(4, m[1].length + 2); out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
      if ((m = l.match(/^\s*[-*]\s+(.*)$/))) { if (para.length || table) flush(); if (!list || list.tag !== "ul") { flush(); list = { tag: "ul", items: [] }; } list.items.push(m[1]); continue; }
      if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) { if (para.length || table) flush(); if (!list || list.tag !== "ol") { flush(); list = { tag: "ol", items: [] }; } list.items.push(m[1]); continue; }
      if (list && /^\s{2,}\S/.test(raw)) { list.items[list.items.length - 1] += " " + l.trim(); continue; }
      if (list) flush();
      para.push(l.trim());
    }
    flush();
    return `<div class="md">${out.join("")}</div>`;
  }

  /* ---------------------------------------------------------------- SSE chat client (POST, so fetch + stream) */
  async function chat(message, { sessionId = null, onEvent = () => {}, signal } = {}) {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }), signal });
    if (!r.ok || !r.body) throw new Error(`chat: HTTP ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "", sid = sessionId;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((x) => x.startsWith("data: "));
        if (!line) continue;
        let e; try { e = JSON.parse(line.slice(6)); } catch (_) { continue; }
        if (e.type === "session") sid = e.session_id;
        onEvent(e);
      }
    }
    return sid;
  }
  /** One console line per trace event, for every screen that shows the swarm working. */
  function traceLine(e) {
    const who = esc(e.author || "");
    if (e.type === "tool_call") {
      const args = Object.entries(e.args || {}).map(([k, v]) => `${k}=${String(v).slice(0, 80)}`).join(", ");
      return `<span class="dim">${who}</span> → ${esc(e.tool)}(${esc(args)})`;
    }
    if (e.type === "tool_result") {
      const st = e.status ? ` <span class="${e.status === "error" ? "crit" : e.status === "pending_approval" ? "warn" : "ok"}">${esc(e.status)}</span>` : "";
      return `<span class="dim">${who} ← ${esc(e.tool)}</span>${st}${e.source ? ` <span class="dim">[${esc([].concat(e.source).map(srcShort).join(", "))}]</span>` : ""}`;
    }
    if (e.type === "pending_action") return `<span class="warn">${who}: pending ${esc(e.action.kind)} ${esc(e.action.id)} needs your sign-off</span>`;
    if (e.type === "audit") return `<span class="${e.verdict === "pass" ? "ok" : "crit"}">risk_auditor: ${esc(e.action_id)} ${esc(String(e.verdict).toUpperCase())}</span>`;
    if (e.type === "error") return `<span class="crit">error: ${esc(e.error)}</span>`;
    if (e.type === "final") return `<span class="dim">answer complete</span>`;
    return null;
  }

  /* ---------------------------------------------------------------- approvals: always through SignOff.open */
  const KIND = { intraday_orders: "JEPX intraday orders", vpp_dispatch: "VPP dispatch", tariff_adjustment: "Tariff change", ppa_offer: "24/7 PPA offer" };
  function openAction(a, after) {
    const audit = a.audit ? ` The reviewer (risk_auditor) returned ${String(a.audit.verdict).toUpperCase()} on ${(a.audit.checks || []).length} checks.` : "";
    window.SignOff.open({
      id: a.id, kind: KIND[a.kind] || a.kind, summary: a.summary, details: a.details, risk: a.risk,
      unverified: a.unsettled || [], reasoning: (a.reasoning || []).join(". ").replace(/\.\./g, ".") + "." + audit,
      sources: (a.sources || []).map(srcShort), author: a.created_by,
    }, {
      onConfirm: async (x) => { const r = await fetch(`/api/actions/${encodeURIComponent(x.id)}/confirm`, { method: "POST" }); const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.status); if (after) after(j); return j; },
      onReject: async (x) => { const r = await fetch(`/api/actions/${encodeURIComponent(x.id)}/reject`, { method: "POST" }); const j = await r.json(); if (after) after(j); return j; },
    });
  }
  /** A compact queue of pending actions; every row opens the sign-off sheet. */
  function actionRows(actions, after) {
    if (!actions.length) return `<p class="lede">Nothing is waiting for a sign-off. Ask the desk a question that needs an action (for example the gate-closure hedge) and it will appear here.</p>`;
    return `<div class="queue">${actions.map((a) => `<${a.status === "pending" ? "button" : "div"} class="card ${a.status === "pending" ? "lift" : "decided"} qrow" data-id="${esc(a.id)}"${a.status === "pending" ? "" : ' aria-disabled="true"'}>
      <span class="badge ${a.status === "pending" ? "b-warn" : a.status === "rejected" ? "b-idle" : "b-ok"}">${esc(a.status === "pending" ? "needs sign-off" : a.status.replace("_", " "))}</span>
      <span class="badge ${a.audit ? (a.audit.verdict === "pass" ? "b-ok" : "b-crit") : "b-idle"}">${a.audit ? "review " + esc(a.audit.verdict) : "not reviewed"}</span>
      <span class="qk mono">${esc(KIND[a.kind] || a.kind)}</span><span class="qs">${esc(a.summary)}${a.execution ? ` <span class="dim">(${esc(a.execution)})</span>` : ""}</span></${a.status === "pending" ? "button" : "div"}>`).join("")}</div>`;
  }
  function bindQueue(root, actions, after) {
    root.querySelectorAll("button.qrow").forEach((b) => b.addEventListener("click", () => {
      const a = actions.find((x) => x.id === b.dataset.id);
      if (a) openAction(a, after);
    }));
  }

  /* ---------------------------------------------------------------- charts: ECharts restyled to the kit */
  function hue(i) { return css(HUES[i % HUES.length]) || "#a7caed"; }
  function chartBase() {
    const muted = css("--fg-muted"), soft = "rgba(255,255,255,0.08)", mono = "JetBrains Mono, monospace";
    const axis = { axisLine: { lineStyle: { color: soft } }, axisTick: { show: false }, splitLine: { lineStyle: { color: soft, width: 1 } },
      axisLabel: { color: muted, fontFamily: mono, fontSize: 10.5 }, nameTextStyle: { color: muted, fontFamily: mono, fontSize: 10.5 } };
    return { backgroundColor: "transparent", color: HUES.map((_, i) => hue(i)), textStyle: { color: muted, fontFamily: "Work Sans, sans-serif" },
      animationDuration: 560, grid: { left: 52, right: 20, top: 30, bottom: 36, containLabel: false },
      tooltip: { trigger: "axis", backgroundColor: "#1f2020", borderColor: "#374151", borderWidth: 1, textStyle: { color: "#e4e2e1", fontSize: 12 },
        extraCssText: "border-radius:0;box-shadow:none" },
      legend: { textStyle: { color: muted, fontFamily: mono, fontSize: 10.5 }, icon: "rect", itemWidth: 10, itemHeight: 4, top: 0 },
      xAxis: axis, yAxis: axis };
  }
  function chart(node, option) {
    if (!window.echarts) { node.innerHTML = '<p class="foot">The chart library did not load. The figures are in the table beside it.</p>'; return null; }
    const base = chartBase();
    const c = window.echarts.getInstanceByDom(node) || window.echarts.init(node, null, { renderer: "svg" });
    const merge = (ax, o) => [].concat(o || {}).map((x) => ({ ...ax, ...x, axisLabel: { ...ax.axisLabel, ...(x.axisLabel || {}) } }));
    c.setOption({ ...base, ...option, xAxis: merge(base.xAxis, option.xAxis), yAxis: merge(base.yAxis, option.yAxis),
      tooltip: { ...base.tooltip, ...(option.tooltip || {}) }, legend: option.legend === false ? { show: false } : { ...base.legend, ...(option.legend || {}) } }, true);
    if (!node._ro && window.ResizeObserver) { node._ro = new ResizeObserver(() => c.resize()); node._ro.observe(node); }
    return c;
  }

  /** Inline SVG sparkline. Nulls break the line; points from `forecastFrom` on are dashed. */
  function sparkline(values, { height = 46, color = "var(--accent)", forecastFrom = null, label = "" } = {}) {
    const vs = values.map((v) => (v === null || v === undefined ? null : Number(v)));
    const ok = vs.filter((v) => v !== null);
    if (!ok.length) return `<svg class="spark" viewBox="0 0 100 ${height}" role="img" aria-label="${esc(label)}: no readings"></svg>`;
    let lo = Math.min(...ok), hi = Math.max(...ok);
    if (hi === lo) { hi += 1; lo -= 1; }
    const w = 100, n = vs.length;
    const x = (i) => ((i / (n - 1)) * w).toFixed(2), y = (v) => (height - 3 - ((v - lo) / (hi - lo)) * (height - 6)).toFixed(2);
    const seg = (from, to) => {
      let d = "", pen = false;
      for (let i = from; i < to; i++) {
        if (vs[i] === null) { pen = false; continue; }
        d += `${pen ? "L" : "M"}${x(i)},${y(vs[i])} `; pen = true;
      }
      return d.trim();
    };
    const cut = forecastFrom === null ? n : Math.max(1, forecastFrom);
    const a = seg(0, Math.min(n, cut + 1)), b = forecastFrom === null ? "" : seg(cut, n);
    return `<svg class="spark" viewBox="0 0 ${w} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}">` +
      (a ? `<path d="${a}" fill="none" stroke="${color}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>` : "") +
      (b ? `<path d="${b}" fill="none" stroke="${color}" stroke-width="1.4" stroke-dasharray="3 3" opacity=".7" vector-effect="non-scaling-stroke"/>` : "") + `</svg>`;
  }

  /* ---------------------------------------------------------------- page furniture */
  async function provenance(extra = []) {
    try {
      const p = await window.Shell.api("/api/story/provenance");
      const n = p.tables ? Object.keys(p.tables).length : null;
      return window.Shell.provenance([
        ["Data", `BigQuery dataset <code>${esc(p.dataset)}</code> (${esc(p.backend)} backend), ${n ?? "NOT IN THE DATA"} tables, ${p.rows ? num(p.rows, 0) : "NOT IN THE DATA"} rows`],
        ["Generator", `<code>${esc(p.generator || "not recorded")}</code>, seed ${esc(p.seed ?? "not recorded")}`],
        ["Window", `Market ${esc(p.calendar?.spot_start)} to ${esc(p.calendar?.spot_end)}; meters ${esc(p.calendar?.load_start)} to the ${esc(p.scenario_now?.replace("T", " "))} JST snapshot`],
        ["Research", `Every third-party figure is cited from <code>${esc(p.research)}</code>`],
        ...extra,
        ["Earlier version", `<a href="/v1/">The version 1 dashboard</a> stays available for comparison`],
      ]);
    } catch (e) {
      return window.Shell.provenance([["Provenance", `unavailable (${esc(e.message)})`]]);
    }
  }
  function next(href, label) {
    return `<div class="next reveal"><span class="eyebrow">Next</span><a class="btn primary" href="${esc(href)}">${esc(label)}</a></div>`;
  }
  function fail(node, e) {
    node.innerHTML = `<div class="note crit"><strong>Could not load</strong><br>${esc(e && e.message ? e.message : e)}</div>`;
  }

  window.Desk = { esc, num, money, moneyParts, moneyRange, f, el, css, hue, srcShort, cites, md, chat, traceLine, openAction, actionRows, bindQueue, chart, sparkline,
    provenance, next, fail, KIND };
})();
