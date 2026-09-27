/* UI v2 motion. Functional only: things enter in reading order, numbers count so the eye lands on the figure
 * that changed, lines draw. Nothing loops. setInterval, not requestAnimationFrame (rAF does not fire in hidden
 * documents, which is how automated checks see the page). Reduced motion jumps to the final state. */
(function () {
  const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /** Reveal .reveal elements as they scroll into view, staggered in document order. Polled, not observed. */
  function reveal(root) {
    const nodes = Array.from((root || document).querySelectorAll(".reveal:not(.in)"));
    if (!nodes.length) return;
    if (REDUCED) return nodes.forEach((n) => n.classList.add("in"));
    let stagger = 0;
    const timer = setInterval(() => {
      const h = window.innerHeight || 900;
      let pending = 0;
      nodes.forEach((n) => {
        if (n.classList.contains("in")) return;
        const r = n.getBoundingClientRect();
        if (r.top < h * 0.94 && r.bottom > 0) {
          setTimeout(() => n.classList.add("in"), (stagger++ % 6) * 70);
        } else pending++;
      });
      if (!pending) clearInterval(timer);
    }, 120);
    // Safety net: never leave content hidden (e.g. print, very tall pages).
    setTimeout(() => nodes.forEach((n) => n.classList.add("in")), 4000);
  }

  /** Count a number up to its value. el.dataset: value, dp, unit. */
  function countUp(el, value, { dp = 0, unit = "", ms = 900 } = {}) {
    const fmt = (v) => Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }) + (unit ? `<span class="u">${unit}</span>` : "");
    if (REDUCED || !Number.isFinite(value)) return (el.innerHTML = fmt(value));
    const t0 = Date.now();
    const id = setInterval(() => {
      const p = Math.min(1, (Date.now() - t0) / ms);
      const e = 1 - Math.pow(1 - p, 3);
      el.innerHTML = fmt(value * e);
      if (p >= 1) clearInterval(id);
    }, 30);
  }

  window.Motion = { reveal, countUp, REDUCED };
  document.addEventListener("DOMContentLoaded", () => reveal());
})();
