/* Retail Energy Desk v2: Cockpit. The v1 operational panels in the kit's language.
 * Every figure comes from /api/*. Agent text and tool previews are untrusted: they reach the page only through
 * Desk.md / Desk.traceLine / Shell.esc. Approvals only through the sign-off sheet (Desk.bindQueue -> Desk.openAction). */
(function () {
  "use strict";
  const esc = (v) => Shell.esc(v);
  const $ = (id) => document.getElementById(id);
  const PPA_QUERY = { prospect_id: "PR-01", target: 90 }; // request parameters for the prospect design toggle
  const DEFAULT_CUSTOMER = "C-0001";                         // request parameter for the first CFE view
  const GATE_WORD = { delivered: "Delivered", in_delivery: "In delivery", closed: "Gate closed", open: "Gate open" };
  const GATE_OPACITY = { delivered: 0.35, in_delivery: 0.6, closed: 0.6, open: 1 };
  const CLASS_LABEL = { residential_battery: "Residential batteries", cni_bess: "C&I batteries", ev_depot: "EV depots",
    heat_pump_water_heater: "Heat pump water heaters", dr_load: "Demand response loads" };
  const CLASS_ORDER = Object.keys(CLASS_LABEL);
  const HEALTH = { ok: ["b-ok", "OK"], degraded: ["b-warn", "DEGRADED"], untrusted: ["b-crit", "UNTRUSTED"] };
  const RANK = { untrusted: 0, degraded: 1, ok: 2 };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // agents/actions stay undefined until loaded (null means the call failed) so the counts line never shows a guess
  const S = { clock: null, kpis: null, market: null, position: null, fleet: null, selected: null, agents: undefined, actions: undefined,
    customers: [], cfe: null, ppa: null, ppaMode: false, counted: false, cfeCounted: false, sessionId: null, running: false, abort: null };

  /* ------------------------------------------------------------------------------------ small helpers */
  const hhmm = (iso) => (/T(\d{2}:\d{2})/.exec(iso || "") || [])[1] || "";
  const startOf = (range) => String(range || "").split("-")[0];
  const signed = (v, dp = 1) => { const n = Desk.num(v, dp); return n === null ? "NOT IN THE DATA" : Number(v) > 0 ? `+${n}` : n; };
  const list = (x) => (Array.isArray(x) ? x : x == null ? [] : [x]);
  function nowPos(iso) { const m = /T(\d{2}):(\d{2})/.exec(iso || ""); return m ? 0.5 + (Number(m[1]) * 60 + Number(m[2])) / 30 : null; }
  function runs(rows, pred) {
    const out = []; let cur = null;
    rows.forEach((r) => { if (pred(r)) { if (cur) cur[1] = r.slot; else cur = [r.slot, r.slot]; } else if (cur) { out.push(cur); cur = null; } });
    if (cur) out.push(cur);
    return out;
  }
  function slotTime(slot) { const r = (S.market?.slots || S.position?.slots || []).find((x) => x.slot === Number(slot)); return r ? r.time : ""; }
  function table(head, rows, numCols = []) {
    return `<table class="data"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows
      .map((r) => `<tr>${r.map((c, i) => `<td${numCols.includes(i) ? ' class="num"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  const tip = {
    head: (t) => `<div style="font:700 12px var(--mono);margin-bottom:4px">${esc(t)}</div>`,
    row: (label, value) => `<div style="display:flex;justify-content:space-between;gap:16px;font:400 11.5px var(--mono)"><span style="color:var(--fg-muted)">${esc(label)}</span><span>${esc(value)}</span></div>`,
  };

  /** Count a KPI once; later refreshes paint the new value directly. */
  function paint(el, value, { dp = 1, unit = "" } = {}) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) { el.innerHTML = Shell.fig(null); return; }
    if (!S.counted) Motion.countUp(el, Number(value), { dp, unit });
    else el.innerHTML = `${Desk.num(value, dp)}${unit ? `<span class="u">${esc(unit)}</span>` : ""}`;
  }
  /** Money through Desk.money, counted on its own scale (886.3M JPY counts to 886.3 with the unit "M JPY"). */
  function paintMoney(el, v) {
    const m = /^(-?)([\d,.]+)([kMB]?) JPY$/.exec(Desk.money(v));
    if (!m) { el.innerHTML = Shell.fig(null); return; }
    const dp = (m[2].split(".")[1] || "").length;
    paint(el, Number(`${m[1]}${m[2].replace(/,/g, "")}`), { dp, unit: `${m[3]} JPY`.trim() });
  }

  /* ------------------------------------------------------------------------------------ header */
  async function loadClock() {
    try { S.clock = await Shell.api("/api/clock"); } catch (e) { S.clock = null; }
  }
  async function loadAgents() {
    try { S.agents = list((await Shell.api("/api/agents")).agents); } catch (e) { S.agents = null; }
    renderCounts();
  }
  function renderCounts() {
    if (S.agents === undefined || S.actions === undefined) return;
    const n = S.agents ? S.agents.length : null;
    const m = S.actions ? S.actions.filter((a) => a.status === "pending").length : null;
    $("counts").textContent = `${n ?? "NOT IN THE DATA"} agents you can talk to · ${m ?? "NOT IN THE DATA"} need your sign-off`;
  }
  function renderHeadline() {
    const k = S.kpis?.net_open_position_next4;
    const g = S.clock?.next_gate_closure;
    if (!k) return;
    const v = Number(k.value), slots = list(k.slots);
    const span = slots.length ? `slots ${slots[0]} to ${slots[slots.length - 1]}` : "the open slots";
    $("headline").textContent = v < -0.05
      ? `The evening is ${Desk.f(-v, k.unit, 1)} short across ${span}${g ? `, and the slot ${g.slot} gate closes at ${hhmm(g.gate_closure)}` : ""}.`
      : `The evening short across ${span} is covered, ${Desk.f(k.sandbox_cover_mwh, k.unit, 1)} of it in the sandbox.`;
  }

  /* ------------------------------------------------------------------------------------ KPIs */
  async function loadKpis() {
    try {
      S.kpis = await Shell.api("/api/kpis");
      renderKpis();
      renderHeadline();
      S.counted = true;
    } catch (e) {
      ["k-spot", "k-reserve", "k-position", "k-vpp", "k-mar"].forEach((id) => Desk.fail($(id).querySelector(".kb"), e));
    }
  }
  function capBadge(id, cls, word) {
    const cap = $(id).querySelector(".card-cap");
    cap.querySelector(".badge")?.remove();
    if (word) cap.insertAdjacentHTML("beforeend", `<span class="badge ${cls}">${esc(word)}</span>`);
  }
  function kpiBody(id, subs) {
    const kb = $(id).querySelector(".kb");
    kb.innerHTML = `<div class="metric" data-m></div>${subs.filter(Boolean).map((s) => `<div class="metric-sub${s.hot ? " hot" : ""}">${s.html ?? esc(s.text)}</div>`).join("")}`;
    return kb.querySelector("[data-m]");
  }
  function renderKpis() {
    const k = S.kpis;
    const sp = k.tokyo_spot_now || {};
    paint(kpiBody("k-spot", [{ text: `Slot ${sp.slot ?? "?"}, ${sp.slot_time || ""}` }, { text: `Evening max ${Desk.f(sp.evening_max, sp.unit, 2)}`, hot: true }]),
      sp.value, { dp: 2, unit: sp.unit });

    const rm = k.reserve_margin || {};
    const worst = Math.min(Number(rm.now), Number(rm.min_ahead));
    capBadge("k-reserve", worst < 5 ? "b-crit" : worst < 8 ? "b-warn" : "b-ok", worst < 5 ? "CRITICAL" : worst < 8 ? "TIGHT" : "NORMAL");
    paint(kpiBody("k-reserve", [{ text: `Now, slot ${k.tokyo_spot_now?.slot ?? "?"}` },
      { text: `Minimum ahead ${Desk.f(rm.min_ahead, rm.unit, 1).replace(" %", "%")} at ${rm.min_slot_time || "?"} (slot ${rm.min_slot ?? "?"})`, hot: true }]),
    rm.now, { dp: 1, unit: rm.unit });

    const np = k.net_open_position_next4 || {};
    const v = Number(np.value), slots = list(np.slots), cover = Number(np.sandbox_cover_mwh) || 0;
    capBadge("k-position", v < -0.05 ? "b-crit" : v > 0.05 ? "b-info" : "b-ok", v < -0.05 ? "SHORT" : v > 0.05 ? "LONG" : "FLAT");
    paint(kpiBody("k-position", [{ text: slots.length ? `Next ${slots.length} open slots, ${slots[0]} to ${slots[slots.length - 1]}. Negative is short.` : "No open slots" },
      { text: cover > 0 ? `Sandbox cover ${signed(cover, 1)} ${np.unit} approved` : `Sandbox cover ${Desk.f(cover, np.unit, 1)}, nothing approved yet`, hot: cover > 0 }]),
    np.value, { dp: 1, unit: np.unit });

    const vp = k.vpp_available || {};
    const un = list(vp.untrusted);
    capBadge("k-vpp", un.length ? "b-crit" : "b-ok", un.length ? `${un.length} UNTRUSTED` : "ALL TRUSTED");
    paint(kpiBody("k-vpp", [{ text: `${vp.clusters_trusted ?? "?"} of ${vp.clusters_total ?? "?"} pools trusted, slot ${vp.slot ?? "?"}` },
      un.length ? { html: `Left out: ${un.map((id) => `<a href="#fleet" data-pool="${esc(id)}">${esc(id)}</a>`).join(", ")}`, hot: true } : null,
      { text: `dKW committed ${Desk.f(vp.committed_dkw_mw, "MW", 1)}` }]),
    vp.value, { dp: 1, unit: vp.unit });
    $("k-vpp").querySelectorAll("a[data-pool]").forEach((a) => a.addEventListener("click", () => selectPool(a.dataset.pool)));

    const mr = k.margin_at_risk || {};
    capBadge("k-mar", "b-warn", `+${mr.shock_pct ?? "?"}% SPOT`);
    paintMoney(kpiBody("k-mar", [{ text: `At +${mr.shock_pct ?? "?"}% spot, ${mr.period || "rest of August"}` },
      { text: `Hedge cover ${Desk.f(mr.hedge_cover_pct, "%", 1).replace(" %", "%")}`, hot: true },
      { text: `Expected margin before the shock ${Desk.money(mr.margin_before)}` }]), mr.value);
  }

  /* ------------------------------------------------------------------------------------ market chart */
  function slotAxis(gridIndex, rows, showLabels, step) {
    const labelSlots = rows.map((r) => r.slot).filter((s) => (s - 1) % step === 0);
    const start = Object.fromEntries(rows.map((r) => [r.slot, startOf(r.time)]));
    return { type: "value", gridIndex, min: rows[0].slot - 0.5, max: rows[rows.length - 1].slot + 0.5, interval: step, splitLine: { show: false },
      axisLabel: { show: showLabels, customValues: labelSlots, formatter: (v) => (Math.abs(v - Math.round(v)) < 1e-6 && start[Math.round(v)]) || "" },
      axisTick: { show: false }, axisPointer: { label: { show: false } } };
  }
  async function loadMarket() {
    try {
      S.market = await Shell.api("/api/market");
      renderMarket();
      if ($("market-tv").open) renderMarketTable();
    } catch (e) { Desk.fail($("market-chart"), e); }
  }
  function renderMarket() {
    const rows = S.market.slots, H = [0, 1, 2, 3, 4, 5].map(Desk.hue);
    const fg = Desk.css("--fg"), muted = Desk.css("--fg-muted"), warn = Desk.css("--warning"), crit = Desk.css("--critical");
    $("market-src").textContent = S.market.date || "";
    const now = S.clock?.now || S.market.now, np = nowPos(now);
    const gate = S.clock?.next_gate_closure, gateSlot = gate?.slot ?? rows.find((r) => r.gate_status === "open")?.slot;
    const band = rows.filter((r) => r.is_forecast && r.imbalance_p10 != null && r.imbalance_p90 != null);
    const scarce = runs(rows, (r) => r.scarcity);
    const lab = { fontFamily: "JetBrains Mono, monospace", fontSize: 10.5 };
    const w = $("market-chart").clientWidth || 800;
    const step = w < 480 ? 12 : w < 760 ? 8 : 4, top = w < 420 ? 92 : w < 620 ? 72 : 44;
    const vLines = (labels) => ({ symbol: "none", silent: true, data: [
      ...(np == null ? [] : [{ xAxis: np, lineStyle: { color: fg, type: "solid", width: 1 }, label: { show: labels, ...lab, color: fg, position: "end", formatter: `Now ${hhmm(now)}` } }]),
      ...(gateSlot ? [{ xAxis: gateSlot - 0.5, lineStyle: { color: warn, type: "dashed", width: 1 },
        label: { show: labels, ...lab, color: fg, position: "start", formatter: `Gate open from slot ${gateSlot}${gate ? `, closes ${hhmm(gate.gate_closure)}` : ""}` } }] : [])] });
    const scarcity = (labels) => ({ silent: true, itemStyle: { color: "rgba(234,88,12,0.08)" },
      label: { show: labels, position: "insideTopRight", ...lab, color: muted, formatter: "Scarcity" },
      data: scarce.map(([a, b]) => [{ xAxis: a - 0.5 }, { xAxis: b + 0.5 }]) });
    const line = (name, key, color, extra = {}) => ({ name, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, symbolSize: 8,
      data: rows.map((r) => [r.slot, r[key]]), lineStyle: { width: 2, color }, itemStyle: { color }, emphasis: { disabled: true }, ...extra });
    Desk.chart($("market-chart"), {
      aria: { enabled: true },
      legend: { data: ["Tokyo spot", "Intraday best ask", "Imbalance p50", "Imbalance p10 to p90", "Reserve margin"] },
      grid: [{ left: 44, right: 52, top, bottom: 128 }, { left: 44, right: 52, bottom: 26, height: 62 }],
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: [slotAxis(0, rows, false, step), slotAxis(1, rows, true, step)],
      yAxis: [{ type: "value", gridIndex: 0, name: "JPY/kWh", min: 0 },
        { type: "value", gridIndex: 1, name: "Reserve %", position: "right", min: 0, splitNumber: 2, axisLabel: { formatter: (v) => `${v}%` } }],
      tooltip: { trigger: "axis", formatter: (ps) => marketTip(ps) },
      series: [
        line("Tokyo spot", "tokyo_spot", H[0], { z: 5, markLine: vLines(true), markArea: scarcity(true) }),
        line("Intraday best ask", "intraday_ask", H[1]),
        line("Imbalance p50", "imbalance", H[2]),
        { name: "Imbalance p10 to p90", type: "custom", xAxisIndex: 0, yAxisIndex: 0, silent: true, z: 1, clip: true, itemStyle: { color: H[2] },
          encode: { x: 0, y: [1, 2] }, data: band.map((r) => [r.slot, Number(r.imbalance_p10), Number(r.imbalance_p90)]),
          renderItem: (params, api) => {
            if (params.dataIndex !== 0 || band.length < 2) return null;
            const top = band.map((r) => api.coord([r.slot, Number(r.imbalance_p90)]));
            const bottom = band.map((r) => api.coord([r.slot, Number(r.imbalance_p10)])).reverse();
            return { type: "polygon", silent: true, shape: { points: top.concat(bottom) }, style: { fill: H[2], opacity: 0.18 } };
          } },
        { name: "Reserve margin", type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, data: rows.map((r) => [r.slot, r.reserve_margin]),
          lineStyle: { width: 2, color: H[3] }, itemStyle: { color: H[3] }, emphasis: { disabled: true }, markArea: scarcity(false),
          markLine: { symbol: "none", silent: true, data: [
            { yAxis: 8, lineStyle: { color: warn, type: "dashed", width: 1 }, label: { ...lab, color: muted, position: "insideStartTop", formatter: "8% tight" } },
            { yAxis: 5, lineStyle: { color: crit, type: "dashed", width: 1 }, label: { ...lab, color: muted, position: "insideStartBottom", formatter: "5% critical" } },
            ...vLines(false).data] } },
      ],
    });
  }
  function marketTip(ps) {
    const slot = Math.round(ps?.[0]?.axisValue ?? NaN);
    const r = S.market.slots.find((x) => x.slot === slot);
    if (!r) return "";
    return tip.head(`Slot ${r.slot}, ${r.time}`) + tip.row("Status", `${GATE_WORD[r.gate_status] || r.gate_status}${r.is_forecast ? ", forecast" : ", actual"}${r.scarcity ? ", scarcity" : ""}`) +
      tip.row("Tokyo spot", Desk.f(r.tokyo_spot, "JPY/kWh", 2)) + tip.row("System spot", Desk.f(r.system_spot, "JPY/kWh", 2)) +
      tip.row("Intraday best ask", Desk.f(r.intraday_ask, "JPY/kWh", 2)) + tip.row("Imbalance p50", Desk.f(r.imbalance, "JPY/kWh", 2)) +
      (r.is_forecast ? tip.row("Imbalance p10 to p90", `${Desk.num(r.imbalance_p10, 2)} to ${Desk.f(r.imbalance_p90, "JPY/kWh", 2)}`) : "") +
      tip.row("Reserve margin", `${Desk.num(r.reserve_margin, 1)}%`) + tip.row("Temperature p50", Desk.f(r.temp_p50, "°C", 1));
  }
  function renderMarketTable() {
    if (!S.market) return;
    $("market-table").innerHTML = table(["Slot", "Time", "Gate", "Tokyo spot JPY/kWh", "Intraday ask JPY/kWh", "Imbalance p50 JPY/kWh", "p10 to p90 JPY/kWh", "Reserve %", "Scarcity"],
      S.market.slots.map((r) => [r.slot, esc(r.time), esc(GATE_WORD[r.gate_status] || r.gate_status), Desk.num(r.tokyo_spot, 2), Desk.num(r.intraday_ask, 2),
        Desk.num(r.imbalance, 2), r.is_forecast ? `${Desk.num(r.imbalance_p10, 2)} to ${Desk.num(r.imbalance_p90, 2)}` : "actual", Desk.num(r.reserve_margin, 1),
        r.scarcity ? "Yes" : "No"]), [0, 3, 4, 5, 7]);
  }

  /* ------------------------------------------------------------------------------------ position chart */
  async function loadPosition() {
    try {
      S.position = await Shell.api("/api/position");
      renderPosition();
      if ($("position-tv").open) renderPositionTable();
    } catch (e) { Desk.fail($("position-chart"), e); }
  }
  function renderPosition() {
    const rows = S.position.slots, H = [0, 1, 2, 3, 4, 5].map(Desk.hue);
    const fg = Desk.css("--fg"), muted = Desk.css("--fg-muted"), neutral = Desk.css("--bx") || muted;
    const open = rows.filter((r) => r.gate_status === "open");
    const worst = open.reduce((m, r) => (m == null || r.open_position < m.open_position ? r : m), null);
    const net = open.reduce((a, r) => a + Number(r.open_position || 0), 0);
    const cover = rows.reduce((a, r) => a + Number(r.sandbox_cover || 0), 0);
    $("position-lede").textContent = open.length
      ? `Open slots ${open[0].slot} to ${open[open.length - 1].slot}: net ${signed(net, 1)} MWh. Largest short ${Desk.f(worst.open_position, "MWh", 1)} at ${startOf(worst.time)} (slot ${worst.slot}).${cover > 0 ? ` Sandbox cover ${signed(cover, 1)} MWh included.` : ""}`
      : "No open slots in the data.";
    const now = S.clock?.now || S.position.now, np = nowPos(now);
    const lab = { fontFamily: "JetBrains Mono, monospace", fontSize: 10.5 };
    const bar = (r, short) => {
      const v = Number(r.open_position), show = short ? v < 0 : v >= 0;
      return { value: [r.slot, show ? v : null], itemStyle: { opacity: GATE_OPACITY[r.gate_status] ?? 1 },
        label: short && worst && r.slot === worst.slot && v < 0 ? { show: true, position: "bottom", ...lab, color: fg, formatter: `Short ${Desk.num(-v, 1)}` } : undefined };
    };
    const dline = (name, key, color, type = "solid") => ({ name, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, data: rows.map((r) => [r.slot, r[key]]),
      lineStyle: { width: 2, color, type }, itemStyle: { color }, emphasis: { disabled: true } });
    Desk.chart($("position-chart"), {
      aria: { enabled: true, decal: { show: true } },
      legend: { data: ["DA plan", "Latest", "Actual", "Short", "Long"], itemGap: 8 },
      grid: [{ left: 44, right: 12, top: 60, height: 96 }, { left: 44, right: 12, top: 190, bottom: 26 }],
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: [slotAxis(0, rows, false, 8), slotAxis(1, rows, true, 8)],
      yAxis: [{ type: "value", gridIndex: 0, name: "Demand MWh", scale: true, splitNumber: 3 }, { type: "value", gridIndex: 1, name: "Open MWh", splitNumber: 4 }],
      tooltip: { trigger: "axis", formatter: (ps) => positionTip(ps) },
      series: [
        dline("DA plan", "demand_da", H[0], "dashed"), dline("Latest", "demand_latest", H[1]), dline("Actual", "demand_actual", H[2]),
        { name: "Short", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barWidth: "70%", barGap: "-100%", emphasis: { disabled: true },
          itemStyle: { color: H[4], decal: { symbol: "rect", symbolSize: 1, dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: Math.PI / 4, color: "rgba(19,19,19,0.6)" } },
          data: rows.map((r) => bar(r, true)),
          markArea: { silent: true, itemStyle: { color: "rgba(167,202,237,0.06)" }, label: { position: "insideTop", ...lab, color: muted },
            data: [...runs(rows, (r) => r.gate_status === "open").map(([a, b]) => [{ xAxis: a - 0.5, name: "Gate open" }, { xAxis: b + 0.5 }]),
              ...runs(rows, (r) => r.gate_status === "delivered").map(([a, b]) => [{ xAxis: a - 0.5, name: "Delivered", itemStyle: { color: "rgba(0,0,0,0)" } }, { xAxis: b + 0.5 }])] },
          markLine: np == null ? undefined : { symbol: "none", silent: true, data: [{ xAxis: np, lineStyle: { color: fg, width: 1, type: "solid" },
            label: { ...lab, color: fg, position: "end", formatter: `Now ${hhmm(now)}` } }] } },
        { name: "Long", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barWidth: "70%", barGap: "-100%", emphasis: { disabled: true },
          itemStyle: { color: neutral, decal: { symbol: "none" } }, data: rows.map((r) => bar(r, false)) },
      ],
    });
  }
  function positionTip(ps) {
    const slot = Math.round(ps?.[0]?.axisValue ?? NaN);
    const r = S.position.slots.find((x) => x.slot === slot);
    if (!r) return "";
    const v = Number(r.open_position);
    return tip.head(`Slot ${r.slot}, ${r.time}`) + tip.row("Status", GATE_WORD[r.gate_status] || r.gate_status) +
      tip.row("DA plan", Desk.f(r.demand_da, "MWh", 1)) + tip.row("Latest forecast", Desk.f(r.demand_latest, "MWh", 1)) +
      tip.row("Actual", r.demand_actual == null ? "not metered yet" : Desk.f(r.demand_actual, "MWh", 1)) +
      tip.row("Bilateral", Desk.f(r.bilateral, "MWh", 1)) + tip.row("Day-ahead spot", Desk.f(r.spot, "MWh", 1)) + tip.row("Intraday", Desk.f(r.intraday, "MWh", 1)) +
      tip.row("Sandbox cover", Desk.f(r.sandbox_cover, "MWh", 2)) +
      tip.row("Open position", `${signed(v, 2)} MWh ${v < -0.05 ? "(short)" : v > 0.05 ? "(long)" : "(flat)"}`);
  }
  function renderPositionTable() {
    if (!S.position) return;
    $("position-table").innerHTML = table(["Slot", "Time", "Gate", "DA plan MWh", "Latest MWh", "Actual MWh", "Sandbox cover MWh", "Open MWh"],
      S.position.slots.map((r) => [r.slot, esc(r.time), esc(GATE_WORD[r.gate_status] || r.gate_status), Desk.num(r.demand_da, 1), Desk.num(r.demand_latest, 1),
        r.demand_actual == null ? "not metered" : Desk.num(r.demand_actual, 1), Desk.num(r.sandbox_cover, 2),
        `${signed(r.open_position, 2)}${r.open_position < -0.05 ? " short" : ""}`]), [0, 3, 4, 5, 6, 7]);
  }

  /* ------------------------------------------------------------------------------------ VPP fleet */
  async function loadFleet() {
    try {
      S.fleet = await Shell.api("/api/vpp/fleet");
      renderFleet();
      const first = [...S.fleet.clusters].sort((a, b) => RANK[a.health] - RANK[b.health])[0];
      if (first) selectPool(S.selected || first.cluster_id, false);
    } catch (e) { Desk.fail($("fleet-body"), e); }
  }
  function renderFleet() {
    const f = S.fleet, cl = list(f.clusters);
    $("fleet-when").textContent = `slot ${f.slot}${slotTime(f.slot) ? `, ${slotTime(f.slot)}` : ""}`;
    const classes = CLASS_ORDER.filter((k) => cl.some((c) => c.asset_class === k)).concat([...new Set(cl.map((c) => c.asset_class))].filter((k) => !CLASS_ORDER.includes(k)));
    const bad = cl.filter((c) => c.health !== "ok").sort((a, b) => RANK[a.health] - RANK[b.health]);
    const summary = classes.map((k) => {
      const g = cl.filter((c) => c.asset_class === k);
      const cnt = (h) => g.filter((c) => c.health === h).length;
      const socs = g.map((c) => c.soc_pct).filter((x) => x != null);
      const health = [`<span class="badge b-ok">${cnt("ok")} OK</span>`,
        cnt("degraded") ? `<span class="badge b-warn">${cnt("degraded")} DEGRADED</span>` : "",
        cnt("untrusted") ? `<span class="badge b-crit">${cnt("untrusted")} UNTRUSTED</span>` : ""].filter(Boolean).join(" ");
      return [esc(CLASS_LABEL[k] || k), g.length, health,
        Desk.num(g.reduce((a, c) => a + Number(c.dispatchable_kw || 0), 0) / 1000, 1),
        socs.length ? `${Desk.num(socs.reduce((a, b) => a + b, 0) / socs.length, 0)}%` : "no storage", g.filter((c) => c.committed_dkw_kw > 0).length];
    });
    $("fleet-body").innerHTML = `
      <div class="mono-cap" style="margin-bottom:6px">Needs attention</div>
      ${bad.length ? `<ul class="attn">${bad.map((c) => `<li><button type="button" data-pool="${esc(c.cluster_id)}" aria-pressed="false">
          <span class="badge ${HEALTH[c.health][0]}">${HEALTH[c.health][1]}</span><strong class="mono">${esc(c.cluster_id)}</strong>
          <span class="muted">${esc(list(c.reasons).join("; ") || "check telemetry")}</span>
          ${c.committed_dkw_kw > 0 ? `<span class="badge b-warn">dKW at risk ${esc(Desk.f(c.committed_dkw_kw, "kW", 0))}</span>` : ""}</button></li>`).join("")}</ul>`
        : `<p class="note info">Every pool is reporting fresh, moving telemetry.</p>`}
      <div class="card" id="pool" style="background:var(--bg);margin-bottom:12px"></div>
      <div class="table-scroll">${table(["Asset class", "Pools", "Health", "Dispatchable MW", "Avg SOC", "dKW pools"], summary, [1, 3, 4, 5])}</div>
      <details class="drawer" style="margin-top:12px"><summary>All ${cl.length} pools<span class="hint">tap one to see its state of charge</span></summary>
        <div class="body">${classes.map((k) => `<div class="mono-cap" style="margin:8px 0 6px">${esc(CLASS_LABEL[k] || k)}</div><div class="tiles">${
          cl.filter((c) => c.asset_class === k).sort((a, b) => RANK[a.health] - RANK[b.health] || a.cluster_id.localeCompare(b.cluster_id)).map((c) => `
          <button class="tile" type="button" data-pool="${esc(c.cluster_id)}" aria-pressed="false"
            aria-label="${esc(`${c.cluster_id}, ${HEALTH[c.health][1]}, SOC ${c.soc_pct == null ? "not reported" : Desk.num(c.soc_pct, 0) + "%"}, dispatchable ${Desk.num(c.dispatchable_kw, 0)} kW${c.committed_dkw_kw > 0 ? ", dKW committed" : ""}`)}">
            <strong>${esc(c.cluster_id.replace(/^VPP-/, ""))}${c.committed_dkw_kw > 0 ? ' <span class="dim">dKW</span>' : ""}</strong>
            <span class="badge ${HEALTH[c.health][0]}">${HEALTH[c.health][1]}</span>
            <span class="muted">SOC ${c.soc_pct == null ? "n/a" : `${Desk.num(c.soc_pct, 0)}%`}</span><span class="muted">${esc(Desk.f(c.dispatchable_kw, "kW", 0))}</span></button>`).join("")}</div>`).join("")}
        </div></details>`;
    $("fleet-body").querySelectorAll("button[data-pool]").forEach((b) => b.addEventListener("click", () => selectPool(b.dataset.pool, false)));
  }
  async function selectPool(id, scroll = true) {
    if (!S.fleet) return;
    const c = S.fleet.clusters.find((x) => x.cluster_id === id);
    if (!c) return;
    S.selected = id;
    $("fleet-body").querySelectorAll("button[data-pool]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pool === id)));
    const box = $("pool");
    const head = `<div class="card-cap"><strong class="mono">${esc(c.cluster_id)}</strong> <span class="muted" style="text-transform:none;letter-spacing:0">${esc(c.name)}</span><span class="spacer"></span><span class="badge ${HEALTH[c.health][0]}">${HEALTH[c.health][1]}</span></div>`;
    box.innerHTML = `${head}<p class="foot">Loading telemetry.</p>`;
    if (scroll) $("fleet").scrollIntoView({ block: "start" });
    let t;
    try { t = await Shell.api(`/api/vpp/telemetry/${encodeURIComponent(id)}`); } catch (e) { if (S.selected === id) Desk.fail(box, e); return; }
    if (S.selected !== id) return;
    const ser = list(t.series);
    const hasSoc = ser.some((r) => r.soc_pct != null);
    const vals = ser.map((r) => (hasSoc ? r.soc_pct : r.available_kw));
    let k = vals.length - 1;
    while (k > 0 && vals[k] != null && vals[k - 1] === vals[k]) k--;
    const flat = vals.length && vals[vals.length - 1] != null && vals.length - 1 - k >= 3 ? ser[k] : null;
    const ok = vals.filter((v) => v != null);
    const unit = hasSoc ? "%" : "kW";
    box.innerHTML = `${head}
      ${ok.length ? `${Desk.sparkline(vals, { color: c.health === "untrusted" ? "var(--critical)" : "var(--accent)", label: `${c.cluster_id} ${hasSoc ? "state of charge" : "available power"}` })}
      <div class="foot" style="margin-top:4px">${esc(hasSoc ? "State of charge" : "Available power")} ${esc(hhmm(ser[0].timestamp))} to ${esc(hhmm(ser[ser.length - 1].timestamp))}: ${esc(Desk.num(Math.min(...ok), hasSoc ? 1 : 0))} to ${esc(Desk.num(Math.max(...ok), hasSoc ? 1 : 0))} ${unit}${flat ? `. <span style="color:var(--critical)">Unchanged since ${esc(hhmm(flat.timestamp))}</span>` : ""}</div>`
    : '<p class="metric gap">NOT IN THE DATA</p>'}
      ${list(c.reasons).length ? `<ul class="tight">${list(c.reasons).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : '<p class="foot">Telemetry fresh and moving.</p>'}
      <dl class="kv" style="margin-top:10px">
        <dt>Dispatchable</dt><dd class="mono">${esc(Desk.f(c.dispatchable_kw, "kW", 0))}, ${esc(Desk.f(c.dispatchable_kwh, "kWh", 0))}</dd>
        <dt>dKW committed</dt><dd class="mono">${c.committed_dkw_kw > 0 ? `${esc(Desk.f(c.committed_dkw_kw, "kW", 0))} (${esc(list(c.commitments).join(", "))})` : "None"}</dd>
        <dt>Devices online</dt><dd class="mono">${esc(Desk.num(c.online_devices, 0))} of ${esc(Desk.num(c.device_count, 0))}</dd>
        <dt>Last seen</dt><dd class="mono">${esc(String(c.last_seen || "NOT IN THE DATA").replace("T", " "))}</dd></dl>`;
  }

  /* ------------------------------------------------------------------------------------ CFE */
  function cfeUrl(id) {
    const month = (S.clock?.date || "").slice(0, 7);
    return `/api/cfe/heatmap?customer_id=${encodeURIComponent(id)}${month ? `&month=${encodeURIComponent(month)}` : ""}`;
  }
  async function loadCfe() {
    const sel = $("cfe-customer");
    try {
      S.customers = list((await Shell.api("/api/cfe/customers")).customers);
      sel.innerHTML = S.customers.map((c) => `<option value="${esc(c.customer_id)}">${esc(c.name)} (${esc(c.customer_id)})</option>`).join("");
      sel.value = S.customers.some((c) => c.customer_id === DEFAULT_CUSTOMER) ? DEFAULT_CUSTOMER : S.customers[0]?.customer_id;
    } catch (e) { sel.innerHTML = "<option>Customers unavailable</option>"; }
    await loadHeat(sel.value || DEFAULT_CUSTOMER);
  }
  async function loadHeat(id) {
    $("cfe-figs").innerHTML = '<p class="foot">Loading the hourly match.</p>';
    try {
      const r = await Shell.api(cfeUrl(id));
      if (($("cfe-customer").value || DEFAULT_CUSTOMER) !== id) return;
      S.cfe = r;
      if (!S.ppaMode) { renderCfe(!S.cfeCounted); S.cfeCounted = true; }
    } catch (e) { if (!S.ppaMode) { Desk.fail($("cfe-figs"), e); Desk.chart($("cfe-chart"), { series: [], legend: false }); } }
  }
  function fig(label, sub) { return `<div><div class="mono-cap">${esc(label)}</div><div class="metric" data-f></div>${sub ? `<div class="metric-sub">${esc(sub)}</div>` : ""}</div>`; }
  function heat(x, y, data, tipFn) {
    const w = $("cfe-chart").clientWidth || 600;
    Desk.chart($("cfe-chart"), {
      aria: { enabled: true }, legend: false,
      grid: { left: 52, right: 12, top: 8, bottom: 84 },
      xAxis: { type: "category", data: x, name: "Hour of day, JST", nameLocation: "middle", nameGap: 26, splitLine: { show: false }, axisLabel: { interval: w < 480 ? 5 : 2 } },
      yAxis: { type: "category", data: y, inverse: true, splitLine: { show: false } },
      visualMap: { type: "continuous", min: 0, max: 100, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 12, itemHeight: w < 480 ? 110 : 200,
        text: ["100% matched", "0%"], textGap: 8, textStyle: { color: Desk.css("--fg-muted"), fontFamily: "JetBrains Mono, monospace", fontSize: 10.5 },
        inRange: { color: [Desk.css("--surface-top"), Desk.css("--accent")] } },
      tooltip: { trigger: "item", formatter: tipFn },
      series: [{ type: "heatmap", data, itemStyle: { borderColor: Desk.css("--surface"), borderWidth: 1 }, emphasis: { itemStyle: { borderColor: Desk.css("--fg"), borderWidth: 1 } } }],
    });
  }
  function renderCfe(count) {
    const r = S.cfe, sc = r.score || {};
    const cust = S.customers.find((c) => c.customer_id === r.customer_id);
    $("cfe-when").textContent = sc.period || r.month || "";
    $("cfe-figs").innerHTML = `<div class="fig-row">${fig("Annual-style volumetric", "what a certificate claim says")}${fig("Contracted, hour by hour", "excess never offsets another hour")}${fig("24/7 CFE score", `includes grid share ${Desk.f(sc.grid_cfe_contribution_pct, "%", 1).replace(" %", "%")}`)}</div>
      <p class="foot" style="margin:0 0 8px">${esc(cust ? `${cust.name}, ${String(cust.segment || "").replace(/_/g, " ")}, ${String(cust.cfe_product || "").replace(/_/g, " ")} product. ` : "")}${esc(Desk.num(sc.hours_below_50pct_matched, 0) ?? "NOT IN THE DATA")} hours below half matched; ${esc(Desk.f(sc.excess_clean_mwh_not_counted, "MWh", 1))} of clean supply fell in hours that did not need it.</p>`;
    const els = $("cfe-figs").querySelectorAll("[data-f]");
    [sc.annual_style_volumetric_match_pct, sc.contracted_hourly_matched_pct, sc.cfe_score_24x7_pct].forEach((v, i) => {
      if (v == null) els[i].innerHTML = Shell.fig(null);
      else if (count) Motion.countUp(els[i], Number(v), { dp: 1, unit: "%" });
      else els[i].innerHTML = Shell.fig(v, "%", 1);
    });
    $("cfe-foot").textContent = `Each cell is one hour: the share of load matched by contracted clean supply in that hour. ${sc.method || ""}`;
    const cells = list(r.cells);
    const dates = [...new Set(cells.map((c) => c.date))].sort();
    const hours = [...new Set(cells.map((c) => Number(c.hour)))].sort((a, b) => a - b);
    heat(hours.map((h) => `${String(h).padStart(2, "0")}:00`), dates.map((d) => d.slice(5)),
      cells.map((c) => [hours.indexOf(Number(c.hour)), dates.indexOf(c.date), c.matched_pct ?? "-"]),
      (p) => tip.head(`${dates[p.value[1]]}, ${String(hours[p.value[0]]).padStart(2, "0")}:00`) + tip.row("Matched", p.value[2] === "-" ? "NOT IN THE DATA" : `${Desk.num(p.value[2], 1)}%`));
  }
  async function togglePpa() {
    S.ppaMode = !S.ppaMode;
    $("ppa-toggle").setAttribute("aria-pressed", String(S.ppaMode));
    $("ppa-toggle").textContent = S.ppaMode ? "Back to customers" : `Prospect design: ${PPA_QUERY.prospect_id} at ${PPA_QUERY.target}%`;
    $("cfe-customer").disabled = S.ppaMode;
    if (!S.ppaMode) { if (S.cfe) renderCfe(false); else loadHeat($("cfe-customer").value); return; }
    if (S.ppa) { renderPpa(); return; }
    $("cfe-figs").innerHTML = `<p class="note info"><strong>Designing</strong><br>Solving the least-cost hourly portfolio for ${esc(PPA_QUERY.prospect_id)}. The first run takes about ten seconds.</p>`;
    Desk.chart($("cfe-chart"), { series: [], legend: false });
    try {
      S.ppa = await Shell.api(`/api/cfe/ppa-heatmap?prospect_id=${encodeURIComponent(PPA_QUERY.prospect_id)}&target=${encodeURIComponent(PPA_QUERY.target)}`);
      if (S.ppaMode) renderPpa();
    } catch (e) { if (S.ppaMode) Desk.fail($("cfe-figs"), e); }
  }
  function renderPpa() {
    const p = S.ppa, d = p.design || {}, grid = list(p.heatmap);
    const range = list(d.price_range_jpy_kwh);
    $("cfe-when").textContent = `${p.prospect_id} design`;
    $("cfe-figs").innerHTML = `<div class="fig-row">${fig("Hourly CFE achieved", `target ${Desk.num(p.target_pct, 0)}%`)}${fig("Annual-style match", "the volumetric view of the same design")}<div><div class="mono-cap">Price range</div><div class="metric">${range.length === 2 ? `${esc(Desk.num(range[0], 2))} to ${esc(Desk.num(range[1], 2))}<span class="u">JPY/kWh</span>` : Shell.fig(null)}</div><div class="metric-sub">${esc(Desk.f(d.annual_load_gwh, "GWh a year", 1))}, ${esc(Desk.f(d.term_years, "years", 0))}</div></div></div>
      <p class="foot" style="margin:0 0 8px"><span class="badge ${p.feasible ? "b-ok" : "b-crit"}">${p.feasible ? "FEASIBLE" : "NOT FEASIBLE"}</span> The target is the share of annual load matched hour by hour, so some month-hours sit below it while others reach 100%.</p>`;
    const els = $("cfe-figs").querySelectorAll("[data-f]");
    [d.achieved_hourly_cfe_pct, d.annual_matched_pct].forEach((v, i) => { els[i].innerHTML = v == null ? Shell.fig(null) : Shell.fig(v, "%", 1); });
    $("cfe-foot").textContent = "Each cell is the average matched share for that month and hour under the proposed clean portfolio.";
    const hours = grid[0] ? grid[0].map((_, i) => `${String(i).padStart(2, "0")}:00`) : [];
    const cells = [];
    grid.forEach((row, m) => list(row).forEach((v, h) => cells.push([h, m, v ?? "-"])));
    heat(hours, grid.map((_, m) => MONTHS[m] || String(m + 1)), cells,
      (pp) => tip.head(`${MONTHS[pp.value[1]] || pp.value[1] + 1}, ${hours[pp.value[0]]}`) + tip.row("Matched", pp.value[2] === "-" ? "NOT IN THE DATA" : `${Desk.num(pp.value[2], 1)}%`));
  }

  /* ------------------------------------------------------------------------------------ queue + audit */
  async function loadQueue() {
    try {
      S.actions = list(await Shell.api("/api/actions"));
      const root = $("queue");
      root.innerHTML = Desk.actionRows(S.actions);
      Desk.bindQueue(root, S.actions, afterDecision);
    } catch (e) { S.actions = null; Desk.fail($("queue"), e); }
    renderCounts();
  }
  async function loadAudit() {
    try {
      const rows = list(await Shell.api("/api/audit"));
      $("audit").innerHTML = rows.length
        ? `<div class="table-scroll">${table(["Time", "Decision", "Kind", "Summary", "Reviewer", "Execution"], rows.map((r) => [
          `<span class="mono">${esc(String(r.at_iso || "NOT IN THE DATA").replace("T", " "))}</span>`,
          r.decision === "confirm" ? '<span class="badge b-ok">APPROVED</span>' : '<span class="badge b-idle">REJECTED</span>',
          esc(Desk.KIND[r.kind] || r.kind || ""), esc(r.summary || ""),
          r.audit_verdict ? `<span class="badge ${r.audit_verdict === "pass" ? "b-ok" : "b-crit"}">${esc(String(r.audit_verdict).toUpperCase())}</span>` : '<span class="badge b-idle">NOT REVIEWED</span>',
          `<span class="mono">${esc(r.execution || "none")}</span>`]))}</div>`
        : '<p class="lede">No decisions yet. Approvals and rejections from the sign-off sheet appear here with the reviewer verdict.</p>';
    } catch (e) { Desk.fail($("audit"), e); }
  }
  function afterDecision() {
    Promise.allSettled([loadKpis(), loadPosition(), loadQueue(), loadAudit()]);
  }

  /* ------------------------------------------------------------------------------------ ask the desk */
  async function loadScenarios() {
    try {
      const sc = list(await Shell.api("/api/scenarios"));
      $("chips").innerHTML = sc.map((s) => `<button class="chip" type="button" data-id="${esc(s.id)}" title="${esc(`${s.persona}: ${s.prompt}`)}"><span class="mono">${esc(s.id)}</span>${esc(s.title)}</button>`).join("");
      $("chips").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
        const s = sc.find((x) => x.id === b.dataset.id);
        if (s) ask(s.prompt, `${s.id} ${s.title}`);
      }));
    } catch (e) { Desk.fail($("chips"), e); }
  }
  function setRunning(on) {
    S.running = on;
    $("ask-send").disabled = on;
    $("ask-stop").hidden = !on;
    $("chips").querySelectorAll(".chip").forEach((b) => { b.disabled = on; });
  }
  function traceAdd(html) {
    const t = $("trace");
    const stick = t.scrollHeight - t.scrollTop - t.clientHeight < 40;
    t.insertAdjacentHTML("beforeend", `${html}\n`);
    if (stick) t.scrollTop = t.scrollHeight;
  }
  async function ask(text, label) {
    const q = String(text || "").trim();
    if (!q || S.running) return;
    setRunning(true);
    $("ask-input").value = "";
    const log = $("chatlog");
    log.querySelector("p.foot")?.remove();
    log.insertAdjacentHTML("beforeend", `<div class="msg user"><div class="who">You${label ? `, ${esc(label)}` : ""}</div>${esc(q)}</div>`);
    const bot = document.createElement("div");
    bot.className = "msg";
    bot.innerHTML = `<div class="who">desk_orchestrator</div><div class="ans"><p class="foot">Working on it.</p></div>`;
    log.appendChild(bot);
    log.scrollTop = log.scrollHeight;
    if ($("trace").querySelector(".dim") && $("trace").childElementCount === 1) $("trace").innerHTML = "";
    traceAdd(`<span class="dim">Question: ${esc(label || q.slice(0, 60))}</span>`);
    const names = new Set((S.agents || []).map((a) => a.name));
    const t0 = Date.now();
    let progress = "sending the question to desk_orchestrator", answer = "", calls = 0, error = null;
    const status = () => { $("ask-status").textContent = `${Math.round((Date.now() - t0) / 1000)} s · ${progress}`; };
    status();
    const tick = setInterval(status, 1000);
    S.abort = new AbortController();
    try {
      S.sessionId = await Desk.chat(q, { sessionId: S.sessionId, signal: S.abort.signal, onEvent: (e) => {
        const line = Desk.traceLine(e);
        if (line) traceAdd(line);
        if (e.type === "session") { S.sessionId = e.session_id; $("session").textContent = `session ${e.session_id}`; }
        else if (e.type === "tool_call") { calls++; progress = names.has(e.tool) ? `${e.author} is asking ${e.tool}` : `${e.author} is calling ${e.tool}`; }
        else if (e.type === "tool_result") progress = `${e.author} has the ${e.tool} result`;
        else if (e.type === "text" && e.author === "desk_orchestrator") {
          answer = String(e.text || "");
          bot.querySelector(".ans").innerHTML = Desk.md(answer); // Desk.md escapes before formatting
          progress = "desk_orchestrator is writing the answer";
        } else if (e.type === "text") progress = `${e.author} is reporting back`;
        else if (e.type === "pending_action" || e.type === "audit") { progress = e.type === "audit" ? `risk_auditor returned ${String(e.verdict).toUpperCase()}` : `${e.author} drafted an action for your sign-off`; loadQueue(); }
        else if (e.type === "error") error = e.error;
        status();
      } });
    } catch (e) {
      if (e.name !== "AbortError") error = e.message;
      else progress = "stopped listening; the agents may still finish, and any proposal will appear in the queue";
    } finally {
      clearInterval(tick);
      S.abort = null;
      const secs = Math.round((Date.now() - t0) / 1000);
      if (answer) bot.querySelector(".ans").innerHTML = Desk.md(answer);
      else bot.querySelector(".ans").innerHTML = `<p class="${error ? "note crit" : "foot"}">${esc(error ? `The desk could not answer: ${error}` : "No answer text arrived from desk_orchestrator.")}</p>`;
      if (answer && error) bot.insertAdjacentHTML("beforeend", `<p class="note crit">${esc(`Stream error: ${error}`)}</p>`);
      $("ask-status").textContent = `${secs} s · ${calls} tool call${calls === 1 ? "" : "s"} · ${error ? "ended with an error" : progress.startsWith("stopped") ? progress : "done"}`;
      log.scrollTop = log.scrollHeight;
      setRunning(false);
      loadQueue();
      loadAudit();
    }
  }
  function wireAsk() {
    $("composer").addEventListener("submit", (e) => { e.preventDefault(); ask($("ask-input").value); });
    $("ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask($("ask-input").value); } });
    $("ask-stop").addEventListener("click", () => S.abort?.abort());
  }

  /* ------------------------------------------------------------------------------------ boot */
  async function main() {
    Shell.mountNav("workspace", "cockpit");
    wireAsk();
    $("cfe-customer").addEventListener("change", (e) => loadHeat(e.target.value));
    $("ppa-toggle").textContent = `Prospect design: ${PPA_QUERY.prospect_id} at ${PPA_QUERY.target}%`;
    $("ppa-toggle").addEventListener("click", togglePpa);
    $("market-tv").addEventListener("toggle", (e) => { if (e.target.open) renderMarketTable(); });
    $("position-tv").addEventListener("toggle", (e) => { if (e.target.open) renderPositionTable(); });
    let lastW = window.innerWidth, rt = 0;
    window.addEventListener("resize", () => {
      clearTimeout(rt);
      rt = setTimeout(() => {
        if (Math.abs(window.innerWidth - lastW) < 80) return;
        lastW = window.innerWidth;
        if (S.market) renderMarket();
        if (S.ppaMode && S.ppa) renderPpa(); else if (S.cfe && !S.ppaMode) renderCfe(false);
      }, 250);
    });
    await loadClock();
    await Promise.allSettled([loadAgents(), loadKpis(), loadMarket(), loadPosition(), loadFleet(), loadCfe(), loadQueue(), loadAudit(), loadScenarios()]);
    $("prov").innerHTML = await Desk.provenance();
    Motion.reveal();
  }
  main();
})();
