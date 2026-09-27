/* AlphaEvolve Energy Lab, UI version 2: what every page shares.
 *
 * The shell configuration (product, nav, the factual pill), number formatting that never prints a missing value
 * as zero, the ECharts theme, sparklines and range bars, the SSE client for the Lab Analyst, the flow tracker that
 * lights "How the question moves" as the trace arrives, and the sign-off wiring. Nothing in this file holds a
 * figure: every number on every page is read from /api at run time.
 *
 * Load order on every page: shell.js, motion.js, signoff.js, lab.js, then the page script.
 */
(function () {
  const DISCLAIMER =
    "Concept demo. Synthetic, calibrated data. Not affiliated with or endorsed by TEPCO or Mitsubishi Electric.";

  window.APP_SHELL = {
    product: "AlphaEvolve Energy Lab",
    company: "TEPCO or Mitsubishi Electric",
    base: "/",
    nav: {
      landing: [
        { href: "/case/", label: "The case for change", key: "l-case" },
        { href: "/workspace/value.html", label: "The workspace", key: "l-ws" },
        { href: "/v1/", label: "Version 1", key: "l-v1" },
      ],
      case: [
        { href: "/case/", label: "1 · The case", key: "case" },
        { href: "/case/gap.html", label: "2 · The gap", key: "gap" },
        { href: "/case/prize.html", label: "3 · The prize", key: "prize" },
        { href: "/case/solution.html", label: "4 · The solution", key: "solution" },
        { href: "/case/proof.html", label: "5 · The proof", key: "proof" },
      ],
      workspace: [
        { href: "/workspace/value.html", label: "Value", key: "value" },
        { href: "/workspace/", label: "Cockpit", key: "cockpit" },
        { href: "/workspace/swarm.html", label: "Agent teams", key: "swarm" },
        { href: "/workspace/persona.html", label: "My role", key: "persona" },
        { href: "/workspace/handover.html", label: "Handover", key: "handover" },
      ],
    },
    pill: async () => window.Shell.api("/api/v2/pill"),
  };

  const esc = (v) => window.Shell.esc(v);
  const $ = (id) => document.getElementById(id);
  const isNum = (v) => v !== null && v !== undefined && v !== "" && typeof v !== "boolean" && Number.isFinite(Number(v));
  const NITD = '<span class="nitd">NOT IN THE DATA</span>';

  /* ---------- numbers ---------- */

  /** Decimal places by magnitude, so one figure is never printed at two precisions on the same page. */
  function dp(v) {
    if (Number.isInteger(Number(v))) return 0;
    const a = Math.abs(Number(v));
    return a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : 3;
  }
  function n(v, d) {
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  /** Plain text: a formatted number, or the honest string. */
  function txt(v, d) {
    return isNum(v) ? n(v, d ?? dp(v)) : "NOT IN THE DATA";
  }
  /** Inline HTML figure for sentences and table cells: value and unit together, or NOT IN THE DATA. */
  function t(v, unit, d) {
    if (!isNum(v)) return NITD;
    return `<span class="fig">${n(v, d ?? dp(v))}${unit ? " " + esc(unit) : ""}</span>`;
  }
  /** As t(), with an explicit sign, for deltas. */
  function st(v, unit, d) {
    if (!isNum(v)) return NITD;
    const x = Number(v);
    return `<span class="fig">${x > 0 ? "+" : ""}${n(x, d ?? dp(x))}${unit ? " " + esc(unit) : ""}</span>`;
  }
  /** Big metric (kit .metric): the kit's Shell.fig, which already renders a missing value as text. */
  function fig(v, unit, d) {
    return window.Shell.fig(isNum(v) ? Number(v) : null, unit, isNum(v) ? d ?? dp(v) : 1);
  }
  /** "FY2025" out of an API key such as fy2025_tokyo_mean, so fiscal years are read, not typed. */
  function fyOf(key) {
    const m = /fy(\d{4})/i.exec(String(key || ""));
    return m ? `FY${m[1]}` : "";
  }
  function plural(k, one, many) {
    return `${k} ${Number(k) === 1 ? one : many}`;
  }
  function when(v) {
    if (!v) return "NOT IN THE DATA";
    const d = new Date(typeof v === "number" ? (v < 1e12 ? v * 1000 : v) : v);
    return Number.isNaN(d.getTime()) ? String(v) : d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
  }

  /* ---------- small HTML pieces ---------- */

  function badge(text, cls) {
    return `<span class="badge ${cls || "b-idle"}">${esc(text)}</span>`;
  }
  /** The run's outcome in words. Prefers the server's status_label; a run still in flight says so. */
  function runStatus(b) {
    if (!b) return badge("NOT IN THE DATA", "b-idle");
    if (b.status === "running") return badge("RUNNING, PARTIAL EVIDENCE", "b-info");
    if (b.status_label)
      return badge(b.status_label, b.infrastructure_failure ? "b-crit" : b.uplift_valid ? "b-ok" : "b-warn") + (b.caveat ? " " + badge("WITH CAVEAT", "b-warn") : "");
    return badge(b.status ? String(b.status).toUpperCase() : "STATUS NOT IN THE DATA", "b-idle");
  }
  /** A caveat the server attaches to a result. Printed in words next to the figure; never dropped. */
  function caveat(text) {
    return text ? `<div class="caveat"><b>Caveat</b> ${esc(text)}</div>` : "";
  }
  /** The honesty string, exactly as the server returns it, never re-cased. */
  function provTag(p) {
    return p ? `<span class="prov-tag">${esc(p)}</span>` : NITD;
  }
  const PROBLEMS = {
    tariff_pricing: { label: "Tariff pricing", sub: "C&I renewal price book" },
    jepx_trading: { label: "JEPX trading", sub: "Day-ahead, intraday and battery" },
  };
  function problemLabel(id) {
    return (PROBLEMS[id] || { label: id }).label;
  }

  /** Provenance footer: the kit's block, with the Lab's exact disclaimer sentence in its foot line. */
  function footer(rows) {
    return window.Shell.provenance(rows).replace(/<div class="foot">[\s\S]*?<\/div>/, `<div class="foot">${esc(DISCLAIMER)}</div>`);
  }

  /** Top bar plus a skip link. The header is inserted synchronously; the pill fills in when /api answers. */
  function nav(app, key) {
    window.Shell.mountNav(app, key);
    const skip = document.createElement("a");
    skip.className = "skip";
    skip.href = "#main";
    skip.textContent = "Skip to content";
    document.body.prepend(skip);
  }

  /** Count up every [data-count] once (Motion.countUp). Units are escaped here because countUp writes HTML. */
  function counts(root) {
    (root || document).querySelectorAll("[data-count]:not([data-counted])").forEach((el) => {
      el.dataset.counted = "1";
      const v = Number(el.dataset.count);
      if (!Number.isFinite(v)) return;
      window.Motion.countUp(el, v, { dp: Number(el.dataset.dp || 0), unit: el.dataset.unit ? esc(el.dataset.unit) : "" });
    });
  }
  /** A counted figure, or NOT IN THE DATA. */
  function countEl(v, unit, d, cls) {
    if (!isNum(v)) return `<span class="${cls || "metric"}">${NITD}</span>`;
    const dd = d ?? (Number.isInteger(Number(v)) ? 0 : dp(v));
    return `<span class="${cls || "metric"}" data-count="${Number(v)}" data-dp="${dd}"${unit ? ` data-unit="${esc(unit)}"` : ""}>${n(v, dd)}${unit ? `<span class="u">${esc(unit)}</span>` : ""}</span>`;
  }

  function errorNote(where, e) {
    return `<div class="note crit" role="alert"><strong>Could not load</strong><br>${esc(where)}: ${esc(e && e.message ? e.message : e)}</div>`;
  }

  /** DOM builder for generated text (diffs, rationales, chat): text always goes in as text, never as HTML. */
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  /** Agent text, built as text nodes (never parsed as HTML). Honoured: "#" headings, "*" or "-" bullets,
   *  **bold** and `code`. Everything else is shown exactly as written. */
  function inline(el, line) {
    for (const part of line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
      if (!part) continue;
      if (/^\*\*[^*]+\*\*$/.test(part)) el.append(h("strong", {}, part.slice(2, -2)));
      else if (/^`[^`]+`$/.test(part)) el.append(h("code", {}, part.slice(1, -1)));
      else el.append(document.createTextNode(part));
    }
  }
  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const isRow = (line) => /^\s*\|.*\|\s*$/.test(line);
  const isSep = (line) => /^[\s|:-]+$/.test(line) && line.includes("-");
  /** A markdown table from the analyst, rebuilt as a real table of text cells. */
  function richTable(lines) {
    const [head, ...body] = lines.filter((l) => !isSep(l)).map(cells);
    const cell = (tag, c) => { const x = h(tag, {}); inline(x, c); return x; };
    return h("div", { class: "table-scroll", style: "margin:8px 0" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, (head || []).map((c) => cell("th", c)))),
      h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => cell("td", c)))))));
  }
  /** Agent text as text nodes (never parsed as HTML). Honoured: tables, "#" headings, "*" or "-" bullets, rules,
   *  **bold** and `code`. Everything else is shown exactly as written. */
  function renderRich(el, text) {
    el.replaceChildren();
    const lines = String(text || "").split("\n");
    let inlinePrev = false;
    const block = (node) => { el.append(node); inlinePrev = false; };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (isRow(line)) {
        const rows = [];
        while (i < lines.length && isRow(lines[i])) rows.push(lines[i++]);
        i--;
        block(richTable(rows));
        continue;
      }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { block(h("hr", { class: "rich-hr" })); continue; }
      const head = /^\s{0,3}#{1,4}\s+(.*)$/.exec(line);
      if (head) { block(h("strong", { class: "rich-h" }, head[1])); continue; }
      if (inlinePrev) el.append(document.createElement("br"));
      const bullet = /^\s*[*-]\s+(.*)$/.exec(line);
      if (bullet) { el.append(document.createTextNode("• ")); inline(el, bullet[1]); }
      else inline(el, line);
      inlinePrev = true;
    }
  }

  async function postJSON(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try {
        const j = await r.json();
        if (j && j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      } catch (e) {
        /* keep the status line */
      }
      throw new Error(msg);
    }
    return r.json();
  }

  /* ---------- charts: ECharts restyled to the tokens ---------- */

  function tokens() {
    const cs = getComputedStyle(document.documentElement);
    const v = (k) => cs.getPropertyValue(k).trim();
    return {
      fg: v("--fg"), muted: v("--fg-muted"), dim: v("--fg-dim"), border: v("--border"), soft: v("--border-soft"),
      bg: v("--bg"), surface: v("--surface"), high: v("--surface-high"), top: v("--surface-top"), accent: v("--accent"),
      ok: v("--success"), warn: v("--warning"), crit: v("--critical"), mono: v("--mono"), sans: v("--sans"),
      b: [1, 2, 3, 4, 5, 6].map((i) => v(`--b${i}`)), bx: v("--bx"),
    };
  }
  let themed = false;
  function registerTheme() {
    if (themed || !window.echarts) return;
    const T = tokens();
    const axis = {
      axisLine: { lineStyle: { color: T.border, width: 1 } },
      axisTick: { lineStyle: { color: T.border, width: 1 } },
      axisLabel: { color: T.muted, fontFamily: T.mono, fontSize: 10.5 },
      splitLine: { lineStyle: { color: T.soft, width: 1 } },
      nameTextStyle: { color: T.muted, fontFamily: T.mono, fontSize: 10.5 },
    };
    window.echarts.registerTheme("lab", {
      color: T.b,
      backgroundColor: "transparent",
      textStyle: { fontFamily: T.sans, color: T.muted },
      categoryAxis: axis, valueAxis: axis, logAxis: axis, timeAxis: axis,
      legend: { textStyle: { color: T.muted, fontFamily: T.mono, fontSize: 10.5 } },
      tooltip: {
        backgroundColor: T.high, borderColor: T.border, borderWidth: 1,
        textStyle: { color: T.fg, fontFamily: T.sans, fontSize: 12 }, extraCssText: "box-shadow:none;border-radius:0;",
      },
      line: { symbolSize: 5, lineStyle: { width: 1.75 } },
    });
    themed = true;
  }
  /** Draw (or redraw) a chart into an element. Without the library, say so in words; the tables still carry the figures. */
  function chart(target, option) {
    const el = typeof target === "string" ? $(target) : target;
    if (!el) return null;
    if (!window.echarts) {
      el.classList.add("chart-off");
      el.innerHTML = '<p class="chart-missing">The chart library did not load, so this chart is not drawn. The figures beside it come from the same response.</p>';
      return null;
    }
    registerTheme();
    let c = window.echarts.getInstanceByDom(el);
    if (!c) {
      c = window.echarts.init(el, "lab", { renderer: "canvas" });
      if ("ResizeObserver" in window) new ResizeObserver(() => !c.isDisposed() && c.resize()).observe(el);
    }
    c.setOption({ animation: !window.Motion.REDUCED, animationDuration: 560, animationEasing: "cubicOut", ...option }, true);
    return c;
  }
  function grid(extra) {
    return { left: 64, right: 20, top: 36, bottom: 48, containLabel: false, ...(extra || {}) };
  }
  /** Axis-trigger tooltip that escapes every name it prints. */
  function axisTip(fmtRow) {
    return {
      trigger: "axis",
      confine: true,
      formatter: (ps) => `${esc(ps[0].axisValueLabel ?? ps[0].axisValue)}<br>` + ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${fmtRow(p)}`).join("<br>"),
    };
  }
  /** A discrete sequential ramp between two token colours (no gradient fills anywhere). */
  function ramp(from, to, k) {
    const hex = (c) => c.replace("#", "").match(/.{2}/g).map((x) => parseInt(x, 16));
    const a = hex(from), b = hex(to);
    return Array.from({ length: k }, (_, i) => {
      const f = k === 1 ? 1 : i / (k - 1);
      return "#" + a.map((x, j) => Math.round(x + (b[j] - x) * f).toString(16).padStart(2, "0")).join("");
    });
  }

  /* ---------- sparkline and range bar (plain SVG / HTML, no library) ---------- */

  function sparkline(values, { height = 48, label = "" } = {}) {
    const pts = [];
    (values || []).forEach((v, i) => isNum(v) && pts.push([i, Number(v)]));
    if (!pts.length) return `<p class="dim mono">NOT IN THE DATA</p>`;
    let lo = Infinity, hi = -Infinity;
    pts.forEach(([, v]) => { if (v < lo) lo = v; if (v > hi) hi = v; });
    const span = hi - lo || 1;
    const W = Math.max(1, values.length - 1);
    const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${((i / W) * 100).toFixed(2)} ${(96 - ((v - lo) / span) * 92).toFixed(2)}`).join("");
    return (
      `<svg class="spark" viewBox="0 0 100 100" preserveAspectRatio="none" style="height:${height}px" role="img" aria-label="${esc(label)}">` +
      `<path d="${d}" vector-effect="non-scaling-stroke"></path>` +
      `<line class="cursor" x1="0" x2="0" y1="0" y2="100" vector-effect="non-scaling-stroke"></line></svg>`
    );
  }
  function moveCursor(svg, i, count) {
    const line = svg && svg.querySelector("line.cursor");
    if (!line) return;
    const x = ((i / Math.max(1, count - 1)) * 100).toFixed(2);
    line.setAttribute("x1", x);
    line.setAttribute("x2", x);
  }

  /** Low-high bar on a shared scale, with an optional marker (the seed, or where this site sits). */
  function rangeBar({ low, high, marker, min, max, colour, dashed, label, unit, markerLabel }) {
    if (!isNum(low) || !isNum(high) || !isNum(min) || !isNum(max) || max <= min) return `<div class="rbar-none">${NITD}</div>`;
    const pct = (v) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
    const a = pct(Math.min(low, high)), b = pct(Math.max(low, high));
    const single = Number(low) === Number(high);
    const mk = isNum(marker)
      ? `<b style="left:calc(${pct(marker).toFixed(2)}% - 1px)" title="${esc(markerLabel || "")}"></b>`
      : "";
    return (
      `<div class="rbar" role="img" aria-label="${esc(label || "")}: ${esc(txt(low))} to ${esc(txt(high))} ${esc(unit || "")}">` +
      `<div class="rbar-track"><i class="${dashed ? "dashed" : ""}${single ? " point" : ""}" style="left:${single ? `calc(${a.toFixed(2)}% - 2px)` : a.toFixed(2) + "%"};width:${single ? "4px" : Math.max(0.8, b - a).toFixed(2) + "%"};--c:${colour || "var(--accent)"}"></i>${mk}</div>` +
      `<div class="rbar-axis"><span>${esc(txt(min))}</span><span>${esc(txt(max))} ${esc(unit || "")}</span></div></div>`
    );
  }
  /** A scale that holds every value given, padded, and includes zero when the values straddle or sit near it. */
  function scale(values) {
    const v = values.filter(isNum).map(Number);
    if (!v.length) return { min: null, max: null };
    let lo = Math.min(...v), hi = Math.max(...v);
    if (lo >= 0 && lo < hi * 0.5) lo = 0;
    if (hi <= 0 && hi > lo * 0.5) hi = 0;
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
    return { min: lo === 0 ? 0 : lo - pad, max: hi === 0 ? 0 : hi + pad };
  }

  /* ---------- the Lab Analyst over SSE ---------- */

  /** POST /api/chat and call onEvent for every `data:` frame (session, text, tool_call, tool_result,
   *  pending_action, final, error). Returns when the stream closes; throws on an HTTP error. */
  async function streamChat(message, sessionId, onEvent) {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message, session_id: sessionId || null }),
    });
    if (!r.ok || !r.body) throw new Error(`/api/chat: HTTP ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    const handle = (chunk) => {
      const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, "")).join("\n");
      if (!data) return;
      let ev;
      try { ev = JSON.parse(data); } catch (e) { ev = { type: "unparsable", raw: data.slice(0, 200) }; }
      onEvent(ev);
    };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        handle(buf.slice(0, i));
        buf = buf.slice(i + 2);
      }
    }
    buf += dec.decode();
    if (buf.trim()) handle(buf);
  }

  /** One question to the analyst, with an honest outcome. It succeeded only if the stream closed with a `final`
   *  frame and no `error` frame. An HTTP error, an error frame, or a stream that stops early is a failure, and the
   *  failure message is returned so the page can say so in words. */
  async function ask(message, sessionId, onEvent) {
    let sawFinal = false, error = null, frame = false;
    try {
      await streamChat(message, sessionId, (ev) => {
        if (ev.type === "final") sawFinal = true;
        if (ev.type === "error" && !error) { error = String(ev.error || "the server reported an error without a message"); frame = true; }
        onEvent(ev);
      });
    } catch (e) {
      error = error || (e && e.message ? e.message : String(e));
    }
    if (!error && !sawFinal) error = "the stream ended before the analyst finished its answer";
    // frame: the error arrived as an `error` frame (already traced); otherwise the page must trace it itself.
    return { ok: !error, error, sawFinal, frame };
  }
  /** The failure sentence every chat surface uses. */
  const failText = (msg) => `The model call failed: ${msg}`;

  const trunc = (s, k) => {
    const x = String(s ?? "");
    return x.length > k ? x.slice(0, k - 3) + "..." : x;
  };
  /** One line in a trace console. Text only. */
  function trace(consoleEl, kind, text) {
    if (!consoleEl) return;
    const stamp = new Date().toISOString().slice(11, 19);
    consoleEl.append(h("div", { class: kind }, `${stamp}  ${text}`));
    while (consoleEl.childElementCount > 400) consoleEl.firstElementChild.remove();
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
  function traceEvent(consoleEl, ev) {
    switch (ev.type) {
      case "session": return trace(consoleEl, "dim", `session ${ev.session_id}`);
      case "tool_call": return trace(consoleEl, "", `${ev.author || "agent"} > ${ev.tool}(${trunc(JSON.stringify(ev.args ?? {}), 300)})`);
      case "tool_result": return trace(consoleEl, "ok", `${ev.tool} < ${trunc(JSON.stringify(ev.result ?? {}), 360)}`);
      case "pending_action": return trace(consoleEl, "warn", `sign-off needed: ${(ev.action && ev.action.summary) || (ev.action && ev.action.kind) || "action"}`);
      case "text": return trace(consoleEl, "dim", `${ev.author || "agent"} wrote ${String(ev.text || "").length} characters`);
      case "final": return trace(consoleEl, "ok", `final answer${ev.author ? ` from ${ev.author}` : ""}`);
      case "error": return trace(consoleEl, "crit", `ERROR · ${failText(ev.error)}`);
      default: return trace(consoleEl, "dim", `event ${trunc(JSON.stringify(ev), 200)}`);
    }
  }

  /** Lights the four flow nodes (1 lead, 2 specialists, 3 reviewer, 4 sign-off) as the live trace reaches them.
   *  text before any tool call: the lead. tool_call / tool_result: the specialists. text after the tools and the
   *  final frame: the reviewer. pending_action: your sign-off. Each node also carries a word, never colour alone. */
  function flowTracker(nodes) {
    let reached = new Set();
    let tools = false;
    const WORD = { 1: "WORKING", 2: "WORKING", 3: "CHECKING", 4: "NEEDS YOU" };
    let finished = false;
    function paint(step) {
      nodes.forEach((node, i) => {
        const s = i + 1;
        const cur = s === step;
        node.classList.toggle("active", cur);
        node.classList.toggle("done", !cur && reached.has(s));
        const st = node.querySelector(".state");
        if (st) {
          st.textContent = cur ? (finished && s === 3 ? "DONE" : WORD[s]) : reached.has(s) ? "REACHED" : "WAITING";
          st.className = `state badge ${cur ? (s === 4 ? "b-warn" : finished && s === 3 ? "b-ok" : "b-info") : reached.has(s) ? "b-ok" : "b-idle"}`;
        }
      });
    }
    return {
      reset() { reached = new Set(); tools = false; finished = false; nodes.forEach((n) => n.classList.remove("failed")); paint(0); },
      /** The call failed: the reviewer and the sign-off were not reached, and the step it stopped at says FAILED. */
      fail() {
        reached.delete(3); reached.delete(4);
        const at = reached.has(2) ? 2 : 1;
        reached.delete(at);
        nodes.forEach((node, i) => {
          const s = i + 1;
          node.classList.remove("active");
          node.classList.toggle("done", reached.has(s));
          node.classList.toggle("failed", s === at);
          const st = node.querySelector(".state");
          if (st) {
            st.textContent = s === at ? "FAILED" : reached.has(s) ? "REACHED" : "NOT REACHED";
            st.className = `state badge ${s === at ? "b-crit" : reached.has(s) ? "b-ok" : "b-idle"}`;
          }
        });
      },
      event(ev) {
        let step = null;
        if (ev.type === "text") step = tools ? 3 : 1;
        else if (ev.type === "tool_call") { reached.add(1); tools = true; step = 2; }
        else if (ev.type === "tool_result") { tools = true; step = 2; }
        else if (ev.type === "final") { finished = true; step = reached.has(4) ? 4 : 3; }
        else if (ev.type === "pending_action") step = 4;
        if (step) { reached.add(step); paint(step); }
      },
      reached: () => new Set(reached),
    };
  }

  /* ---------- sign-off (only ever for mark_human_reviewed) ---------- */

  function valueText(v) {
    if (v === null || v === undefined) return "not recorded";
    if (typeof v === "number") return txt(v);
    return String(v);
  }
  /** What the gate could not settle: every unmet check except the review itself, then the promotion control. */
  function unmet(gate, promotionControl) {
    const out = (gate && gate.checks ? gate.checks : [])
      .filter((c) => !c.ok && c.id !== "human_review")
      .map((c) => `${c.label}. Recorded value: ${valueText(c.value)}.`);
    const pc = promotionControl || (gate && gate.promotion_control);
    if (pc) out.push(`Promotion control: ${pc}. Recording a review does not change this.`);
    return out;
  }

  /** (a) A finished run's champion, marked human-reviewed from Handover or the Cockpit. */
  function signOffReview({ runId, gate, provenance, reasoning, sources, note, onDone, caveat: cav }) {
    const pid = gate && gate.best_program_id;
    const un = unmet(gate);
    if (cav) un.unshift(`Caveat the server attaches to this result: ${cav}`);
    if (provenance) un.push(`Where the run came from: ${provenance}.`);
    window.SignOff.open(
      {
        kind: "mark_human_reviewed",
        summary: `Mark ${pid} in ${runId} as human-reviewed`,
        details: { run_id: runId, program_id: pid },
        unverified: un,
        reasoning,
        sources: sources || [],
      },
      {
        onConfirm: async () => {
          const r = await postJSON(`/api/runs/${encodeURIComponent(runId)}/review`, {
            program_id: pid,
            reviewer: "demo-reviewer",
            note: typeof note === "function" ? note() : note || "",
          });
          if (onDone) onDone(r);
          return r;
        },
      }
    );
  }

  /** (b) A pending action the analyst proposed in chat. Only mark_human_reviewed opens the sheet. */
  async function signOffAction(action, { reasoning, onDone } = {}) {
    if (!action || action.kind !== "mark_human_reviewed") return false;
    const d = action.details || {};
    let gate = null;
    try {
      if (d.run_id) gate = await window.Shell.api(`/api/runs/${encodeURIComponent(d.run_id)}/gate`);
    } catch (e) {
      gate = null;
    }
    const un = gate ? unmet(gate) : [`The promotion gate for ${d.run_id || "this run"} could not be read.`];
    if (d.run_source) un.push(`Run source recorded by the agent: ${d.run_source}.`);
    if (action.risk) un.push(`Risk, as the agent states it: ${action.risk}`);
    const src = action.reasoning_source;
    window.SignOff.open(
      { ...action, unverified: un, reasoning: reasoning || action.summary, sources: Array.isArray(src) ? src : src ? [src] : [] },
      {
        onConfirm: async (a) => {
          const r = await postJSON(`/api/actions/${encodeURIComponent(a.id)}/confirm`);
          if (onDone) onDone(r);
          return r;
        },
        onReject: async (a) => {
          const r = await postJSON(`/api/actions/${encodeURIComponent(a.id)}/reject`);
          if (onDone) onDone(r);
          return r;
        },
      }
    );
    return true;
  }

  window.LAB = {
    DISCLAIMER, $, esc, isNum, NITD, dp, n, txt, t, st, fig, fyOf, plural, when, badge, runStatus, provTag,
    PROBLEMS, problemLabel, footer, caveat, nav, counts, countEl, errorNote, h, renderRich, postJSON, tokens, chart, grid,
    axisTip, ramp, sparkline, moveCursor, rangeBar, scale, streamChat, trace, traceEvent, flowTracker, trunc,
    signOffReview, signOffAction, unmet, valueText, ask, failText,
  };
})();
