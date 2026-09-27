/* UI v2 shell: shared chrome for the three screens families (landing, case, workspace).
 *
 * Every figure comes from the demo's /api endpoints; nothing here holds a number of its own.
 * Each demo defines window.APP_SHELL before loading this file:
 *
 *   window.APP_SHELL = {
 *     product: "Retail Energy Desk",
 *     company: "TEPCO Energy Partner",             // used only in the disclaimer
 *     base: "/",                                  // where landing lives
 *     nav: {
 *       case:      [{ href: "/case/", label: "1 · The case" }, ...],
 *       workspace: [{ href: "/workspace/value.html", label: "Value" }, ...],
 *     },
 *     pill: async (app) => ({ text: "Slot 35 gate closes 16:00", title: "Source: balance_position_30min" }),
 *   };
 */
(function () {
  const S = () => window.APP_SHELL || {};

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** Format a figure with units and fixed places; a missing value renders as text, never as 0. */
  function fig(v, unit, dp = 1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '<span class="metric gap">NOT IN THE DATA</span>';
    const n = Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return unit ? `${n}<span class="u">${esc(unit)}</span>` : n;
  }

  async function api(path) {
    const r = await fetch(path, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  /** Sticky top bar: brand, the app's destinations, and a factual pill on the right. */
  async function mountNav(app, current) {
    const s = S();
    const items = (s.nav && s.nav[app]) || [];
    const bar = document.createElement("header");
    bar.className = "topbar";
    const brand = app === "case" ? `${s.product} · The case for change` : app === "workspace" ? `${s.product} · Workspace` : s.product;
    bar.innerHTML =
      `<a class="brand" href="${esc(s.base || "/")}">${esc(brand)}</a>` +
      `<nav aria-label="${esc(app)}">${items
        .map((i) => `<a href="${esc(i.href)}"${i.href.endsWith(current) || i.key === current ? ' aria-current="page"' : ""}>${esc(i.label)}</a>`)
        .join("")}</nav><span class="spacer"></span><span class="pill" id="shell-pill">…</span>`;
    document.body.prepend(bar);
    if (s.pill) {
      try {
        const p = await s.pill(app);
        const el = document.getElementById("shell-pill");
        el.textContent = p.text;
        el.title = p.title || "";
      } catch (e) {
        document.getElementById("shell-pill").textContent = "data unavailable";
      }
    }
  }

  /** Collapsed drawer for the technical detail a CEO does not need first. */
  function technicalDrawer(bodyHtml, hint) {
    return `<details class="drawer"><summary>Technical detail<span class="hint">${esc(hint || "")}</span></summary><div class="body">${bodyHtml}</div></details>`;
  }

  /** Provenance footer: where every figure on the page came from, plus the disclaimer. */
  function provenance(rows) {
    const s = S();
    const kv = (rows || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
    return `<div class="prov reveal"><div class="card-cap">Provenance</div><dl class="kv prov">${kv}</dl>
      <div class="foot">Concept demo. Synthetic data. Not affiliated with or endorsed by ${esc(s.company || "the companies named")}.</div></div>`;
  }

  window.Shell = { esc, fig, api, mountNav, technicalDrawer, provenance };
})();
