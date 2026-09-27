/* Retail Energy Desk: shell configuration for the v2 kit (kit/shell.js reads window.APP_SHELL).
 * Words and routes only. The pill is filled from /api/clock, like every figure on every screen. */
window.APP_SHELL = {
  product: "Retail Energy Desk",
  company: "TEPCO",
  base: "/",
  nav: {
    case: [
      { key: "case", href: "/case/", label: "1 · The case" },
      { key: "gap", href: "/case/gap.html", label: "2 · The gap" },
      { key: "prize", href: "/case/prize.html", label: "3 · The prize" },
      { key: "solution", href: "/case/solution.html", label: "4 · The solution" },
      { key: "proof", href: "/case/proof.html", label: "5 · The proof" },
      { key: "to-workspace", href: "/workspace/value.html", label: "Workspace" },
    ],
    workspace: [
      { key: "value", href: "/workspace/value.html", label: "Value" },
      { key: "cockpit", href: "/workspace/", label: "Cockpit" },
      { key: "swarm", href: "/workspace/swarm.html", label: "Agent teams" },
      { key: "persona", href: "/workspace/persona.html", label: "My role" },
      { key: "handover", href: "/workspace/handover.html", label: "Handover" },
      { key: "to-case", href: "/case/", label: "The case" },
    ],
  },
  pill: async () => {
    const c = await window.Shell.api("/api/clock");
    const g = c.next_gate_closure;
    return g
      ? { text: `${c.now.slice(11)} JST · slot ${g.slot} gate closes ${g.gate_closure.slice(11)}, ${g.minutes_left} min`, title: "Source: desk clock" }
      : { text: `${c.now.slice(11)} JST · no gate open`, title: "Source: desk clock" };
  },
};
