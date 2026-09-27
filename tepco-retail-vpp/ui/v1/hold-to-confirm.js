// Hold-to-Confirm: 2 s press-and-hold (pointer, Space or Enter) before onConfirm fires. Releasing early cancels.
// Usage: holdToConfirm(buttonEl, () => fetch(`/api/actions/${id}/confirm`, {method: "POST"}), {ms: 2000});
export function holdToConfirm(btn, onConfirm, { ms = 2000 } = {}) {
  btn.classList.add("htc");
  let start = 0, raf = 0, done = false;
  const label = btn.textContent;
  const tick = (t) => {
    const p = Math.min(1, (t - start) / ms);
    btn.style.setProperty("--p", p);
    if (p >= 1) { done = true; btn.style.setProperty("--p", 0); btn.disabled = true; btn.textContent = "Confirmed"; onConfirm(); return; }
    raf = requestAnimationFrame(tick);
  };
  const begin = (e) => { if (done || btn.disabled) return; e.preventDefault(); start = performance.now(); btn.textContent = "Keep holding"; raf = requestAnimationFrame(tick); };
  const cancel = () => { if (done) return; cancelAnimationFrame(raf); btn.style.setProperty("--p", 0); btn.textContent = label; };
  btn.addEventListener("pointerdown", begin);
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => btn.addEventListener(ev, cancel));
  btn.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) begin(e); });
  btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") cancel(); });
  btn.setAttribute("aria-label", `${label}. Press and hold for ${ms / 1000} seconds to confirm`);
}
