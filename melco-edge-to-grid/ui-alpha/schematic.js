/* Screen 2: the plant as a single-line twin. Nodes come from /api/alpha/schematic; links are declared as node pairs and
 * their geometry is measured from the live element rectangles, so they land on the boxes at any width. */
window.Schematic = (function () {
  const esc = (v) => window.Alpha.esc(v);
  let host = null, data = null, onSelect = null, selected = null;

  function node(n) {
    const cls = n.state === "crit" ? "crit" : n.state === "watch" ? "watch" : n.id === "aggregator" ? "primary" : "";
    return `<button type="button" class="snode ${cls}" id="sn-${esc(n.id)}" data-node="${esc(n.id)}" aria-pressed="false"><span class="sdot"></span>${esc(n.label)}<small${n.state === "crit" ? ' class="sub-crit"' : ""}>${esc(n.sub)}</small></button>`;
  }

  function render(el, d, cb) {
    host = el; data = d; onSelect = cb;
    const byZone = (z) => d.nodes.filter((n) => n.zone === z.id);
    host.innerHTML = `<div class="schematic-grid-bg" id="sch-grid"><svg class="schematic-svg" id="sch-svg" aria-hidden="true"></svg>
      <div class="schematic-zones" id="sch-zones">${d.zones.map((z) => `<div class="zone-box ${esc(z.id)}" id="zone-${esc(z.id)}"><div class="zone-title">${esc(z.title)}<span class="zone-count">${byZone(z).length}</span></div><div class="zone-nodes">${byZone(z).map(node).join("")}</div></div>`).join("")}</div></div>
      <div class="sor-strip"><span class="sor-title">Systems of record</span>${d.systems_of_record.map((s) => `<span class="sor-item">${esc(s.name)}<small>${esc(s.sub)}</small></span>`).join("")}<span class="sor-note" id="sor-note"></span></div>`;
    host.querySelectorAll("[data-node]").forEach((b) => b.addEventListener("click", () => select(b.dataset.node)));
    draw();
    if (!host._ro && window.ResizeObserver) { host._ro = new ResizeObserver(() => draw()); host._ro.observe(host); }
  }

  function select(id) {
    selected = id;
    host.querySelectorAll(".snode").forEach((b) => { const on = b.dataset.node === id; b.classList.toggle("selected", on); b.setAttribute("aria-pressed", String(on)); });
    const n = data.nodes.find((x) => x.id === id);
    if (n && onSelect) onSelect(n);
  }

  function centre(id, box) {
    const el = document.getElementById(`sn-${id}`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!r.width) return null;
    return { l: r.left - box.left, r: r.right - box.left, t: r.top - box.top, b: r.bottom - box.top, cx: r.left - box.left + r.width / 2, cy: r.top - box.top + r.height / 2 };
  }

  function draw() {
    if (!host || !data) return;
    const grid = host.querySelector("#sch-grid"), svg = host.querySelector("#sch-svg");
    if (!grid || !svg) return;
    const box = grid.getBoundingClientRect();
    if (!box.width) return;
    svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
    const paths = [];
    for (const [a, b, kind] of data.links) {
      const A = centre(a, box), B = centre(b, box);
      if (!A || !B) continue;
      let x1, y1, x2, y2;
      if (B.l > A.r + 8) { x1 = A.r; y1 = A.cy; x2 = B.l; y2 = B.cy; }             // left to right
      else if (A.l > B.r + 8) { x1 = A.l; y1 = A.cy; x2 = B.r; y2 = B.cy; }
      else if (B.t > A.b) { x1 = A.cx; y1 = A.b; x2 = B.cx; y2 = B.t; }              // stacked
      else { x1 = A.cx; y1 = A.t; x2 = B.cx; y2 = B.b; }
      const mx = (x1 + x2) / 2;
      const d = Math.abs(y2 - y1) > Math.abs(x2 - x1) ? `M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}` : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
      paths.push(`<path class="link ${kind || ""}" d="${d}"/>`);
    }
    svg.innerHTML = paths.join("");
  }

  return { render, draw, select, get selected() { return selected; } };
})();
