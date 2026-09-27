/* UI v2 sign-off sheet. Raised from an agent team or a role page, never a destination of its own.
 *
 * Order is deliberate: what the recommendation could NOT settle is drawn first and never collapses; then the
 * agent's own case in its own words; then what it read; then the 2-second hold. A click is one slip away from
 * committing; two seconds of held contact cannot be made by accident. Completing the hold reports exactly what
 * the server did (sandbox execution + audit row), never more.
 *
 *   SignOff.open(action, { onConfirm: async (a) => fetch(`/api/actions/${a.id}/confirm`, {method: "POST"}).then(r => r.json()),
 *                          onReject: async (a) => ... });
 * action = { id, kind, summary, details, risk, unverified: [..strings..], reasoning, sources: [..], author }
 */
(function () {
  const HOLD_MS = 2000;
  const esc = (v) => (window.Shell ? window.Shell.esc(v) : String(v ?? ""));

  function hold(btn, ms, done) {
    const fill = btn.querySelector(".hold-fill");
    let t0 = 0, id = 0, fired = false;
    const stop = () => { clearInterval(id); if (!fired) fill.style.width = "0%"; };
    const start = (e) => {
      if (fired || btn.disabled) return;
      e.preventDefault(); t0 = Date.now();
      id = setInterval(() => {
        const p = Math.min(1, (Date.now() - t0) / ms);
        fill.style.width = `${p * 100}%`;
        if (p >= 1) { clearInterval(id); fired = true; done(); }
      }, 30);
    };
    btn.addEventListener("pointerdown", start);
    ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => btn.addEventListener(ev, stop));
    btn.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) start(e); });
    btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") stop(); });
  }

  function open(a, { onConfirm, onReject } = {}) {
    const un = (a.unverified && a.unverified.length ? a.unverified : ["Nothing flagged by the agent. The reviewer's verdict is below."]);
    const src = (a.sources || []).map((s) => `<span class="pill">${esc(s)}</span>`).join(" ");
    const back = document.createElement("div");
    back.className = "sheet-backdrop";
    back.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-label="Sign-off">
      <div class="eyebrow">Needs your sign-off · ${esc(a.kind || "action")}</div>
      <h2>${esc(a.summary || "Proposed action")}</h2>
      <div class="unverified"><strong class="mono">What this recommendation could not settle</strong>
        <ul class="tight">${un.map((u) => `<li>${esc(u)}</li>`).join("")}</ul></div>
      <div class="card-cap">The agent's case, in its own words</div>
      <p>${esc(a.reasoning || a.details_text || "")}</p>
      ${a.details ? `<details class="drawer"><summary>What it wants to do, exactly<span class="hint">order lines</span></summary><div class="body"><pre class="console">${esc(JSON.stringify(a.details, null, 2))}</pre></div></details>` : ""}
      <div class="card-cap" style="margin-top:16px">What it read</div><div>${src || '<span class="pill">not stated</span>'}</div>
      <div class="btn-row" style="margin-top:20px">
        <button class="btn danger" id="so-hold"><span class="hold-fill"></span><span class="lbl">Hold 2 s to approve</span></button>
        <button class="btn" id="so-reject">Reject</button><button class="btn" id="so-close">Close</button></div>
      <div class="foot" id="so-result">Approving runs the action in the demo sandbox and writes one audit record. Nothing reaches a real market or plant.</div>
    </div>`;
    document.body.appendChild(back);
    const $ = (id) => back.querySelector(id);
    const close = () => back.remove();
    $("#so-close").onclick = close;
    back.addEventListener("click", (e) => { if (e.target === back) close(); });
    $("#so-reject").onclick = async () => { const r = onReject ? await onReject(a) : null; $("#so-result").textContent = r ? `Rejected. Audit status: ${r.status}.` : "Rejected."; };
    hold($("#so-hold"), HOLD_MS, async () => {
      $("#so-hold").disabled = true; $("#so-hold .lbl").textContent = "Approved";
      try { const r = onConfirm ? await onConfirm(a) : null; $("#so-result").textContent = r ? `Server status: ${r.status}. One audit record written.` : "Approved."; }
      catch (e) { $("#so-result").textContent = `The server refused: ${e.message}`; }
    });
    $("#so-hold").focus();
  }

  window.SignOff = { open, HOLD_MS };
})();
