/* UI alpha shell: hash-routed screens, API helper, figures, slide-over drawer, toast, hold-to-approve ring,
 * live agent stream. Nothing here holds a number of its own; every figure comes from /api.
 *
 *   window.ALPHA = { product, company, screens: [{id, label}], avatar: "VS" }
 *   Alpha.mount();  Alpha.api("/api/..."); Alpha.fig(v, unit, dp); Alpha.range(lo, hi, unit);
 *   Alpha.drawer.open(title, html); Alpha.toast("Copied"); Alpha.hold(btn, onDone);
 *   Alpha.stream("/api/chat", message, onEvent) -> Promise (SSE events from the demo server)
 */
(function () {
  const C = () => window.ALPHA || { screens: [] };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function fig(v, unit = "", dp = 1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '<span class="gap-value">NOT IN THE DATA</span>';
    const n = Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return unit ? `${n}<span class="t-unit">${esc(unit)}</span>` : n;
  }
  /** Value as a range, never a point: "2.1 to 3.4 B JPY". */
  function range(lo, hi, unit = "", dp = 1) {
    if ([lo, hi].some((x) => x === null || x === undefined || Number.isNaN(Number(x)))) return '<span class="gap-value">NOT IN THE DATA</span>';
    const f = (x) => Number(x).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return `${f(lo)} to ${f(hi)}${unit ? `<span class="t-unit">${esc(unit)}</span>` : ""}`;
  }
  async function api(path, opts) {
    const r = await fetch(path, { headers: { Accept: "application/json" }, ...(opts || {}) });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  /* ---- hash-routed screens ---- */
  function switchScreen(id) {
    const ids = C().screens.map((s) => s.id);
    if (!ids.includes(id)) id = ids[0];
    document.querySelectorAll(".screen-pane").forEach((p) => p.classList.toggle("active", p.id === `pane-${id}`));
    document.querySelectorAll(".nav-item").forEach((a) => {
      const on = a.id === `tab-${id}`;
      a.classList.toggle("active", on);
      a.setAttribute("aria-selected", on ? "true" : "false");
    });
    window.scrollTo({ top: 0, behavior: "auto" });
    document.dispatchEvent(new CustomEvent("alpha:screen", { detail: { id } }));
  }
  function mount() {
    const c = C();
    const header = document.createElement("header");
    header.className = "app-header";
    header.innerHTML =
      `<div class="brand-cluster"><svg class="brand-logo" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5zm0 8.5L4 6.5v9l8 4 8-4v-9l-8 4z"/></svg>
         <span class="brand-title">${esc(c.product)}</span><span class="header-sep">|</span>
         <span class="sys-badge" title="Every customer, plant and figure is fictional; actions run in a sandbox"><span class="dot"></span>SYNTHETIC · SANDBOX</span></div>
       <nav class="header-nav" role="tablist">${c.screens.map((s, i) => `<a class="nav-item${i === 0 ? " active" : ""}" id="tab-${s.id}" href="#${s.id}" role="tab" aria-selected="${i === 0}">${esc(s.label)}</a>`).join("")}</nav>
       <div class="header-actions"><div class="user-avatar" title="Signed in">${esc(c.avatar || "VS")}</div></div>`;
    document.body.prepend(header);
    const toast = document.createElement("div"); toast.id = "toast"; document.body.appendChild(toast);
    const dr = document.createElement("aside"); dr.className = "drawer-overlay"; dr.id = "drawer"; dr.setAttribute("aria-hidden", "true");
    dr.innerHTML = `<div class="drawer-head"><div><div class="eyebrow" id="drawer-eyebrow"></div><h3 id="drawer-title"></h3></div><button class="icon-btn" id="drawer-close" aria-label="Close">✕</button></div><div class="drawer-body" id="drawer-body"></div>`;
    document.body.appendChild(dr);
    dr.querySelector("#drawer-close").onclick = drawer.close;
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") drawer.close(); });
    window.addEventListener("hashchange", () => switchScreen(location.hash.slice(1)));
    switchScreen(location.hash.slice(1));
  }

  const drawer = {
    open(title, html, eyebrow = "") {
      const d = document.getElementById("drawer");
      d.querySelector("#drawer-title").textContent = title;
      d.querySelector("#drawer-eyebrow").textContent = eyebrow;
      d.querySelector("#drawer-body").innerHTML = html;
      d.classList.add("open"); d.setAttribute("aria-hidden", "false");
      return d.querySelector("#drawer-body");
    },
    close() { const d = document.getElementById("drawer"); if (d) { d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); } },
  };
  let toastTimer = 0;
  function toast(msg) { const t = document.getElementById("toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.style.display = "none"), 2200); }

  /** Two seconds of held contact, shown as a ring filling. Releasing early cancels. Keyboard: hold Space/Enter. */
  function hold(btn, onDone, ms = 2000) {
    btn.classList.add("mo-hold");
    if (!btn.querySelector(".ring")) btn.insertAdjacentHTML("afterbegin", `<svg class="ring" viewBox="0 0 24 24" aria-hidden="true"><circle class="bg" cx="12" cy="12" r="10"/><circle class="fg" cx="12" cy="12" r="10" transform="rotate(-90 12 12)"/></svg>`);
    let timer = 0, done = false;
    const start = (e) => { if (done) return; e.preventDefault(); btn.classList.add("holding"); timer = setTimeout(async () => { done = true; btn.classList.remove("holding"); btn.classList.add("done"); btn.querySelector(".lbl") && (btn.querySelector(".lbl").textContent = "Approved"); await onDone(); }, ms); };
    const cancel = () => { if (done) return; clearTimeout(timer); btn.classList.remove("holding"); };
    btn.addEventListener("pointerdown", start); ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => btn.addEventListener(ev, cancel));
    btn.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) start(e); });
    btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") cancel(); });
  }

  /** Read the demo server's SSE chat stream; onEvent gets each parsed event ({type, author, tool, text, action ...}). */
  async function stream(url, message, onEvent, session_id) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id }) });
    if (!r.ok || !r.body) throw new Error(`chat: HTTP ${r.status}`);
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) { try { onEvent(JSON.parse(line.slice(6))); } catch (e) { /* ignore malformed */ } }
      }
    }
  }

  /** Stagger entrance for a container's children (riseIn). Removes the class when the run ends. */
  function play(container) {
    if (!container) return;
    Array.from(container.children).forEach((el, i) => el.style.setProperty("--motion-i", i));
    container.classList.add("motion-playing");
    setTimeout(() => container.classList.remove("motion-playing"), 60 * container.children.length + 400);
  }

  window.Alpha = { esc, fig, range, api, mount, switchScreen, drawer, toast, hold, stream, play };
})();
