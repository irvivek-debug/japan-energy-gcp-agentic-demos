/* Shell configuration for the Factory Energy Copilot (UI v2). Destinations only; every figure comes from /api. */
window.APP_SHELL = {
  product: "Factory Energy Copilot",
  company: "Mitsubishi Electric",
  base: "/",
  nav: {
    landing: [
      { href: "/case/index.html", label: "The case for change" },
      { href: "/workspace/value.html", label: "The workspace" },
      { href: "/v1/", label: "Version 1" },
    ],
    case: [
      { href: "/case/index.html", label: "1 · The case" },
      { href: "/case/gap.html", label: "2 · The gap" },
      { href: "/case/prize.html", label: "3 · The prize" },
      { href: "/case/solution.html", label: "4 · The solution" },
      { href: "/case/proof.html", label: "5 · The proof" },
      { href: "/workspace/value.html", label: "Workspace" },
    ],
    workspace: [
      { href: "/workspace/value.html", label: "Value" },
      { href: "/workspace/index.html", label: "Cockpit" },
      { href: "/workspace/swarm.html", label: "Agent teams" },
      { href: "/workspace/persona.html", label: "My role" },
      { href: "/workspace/handover.html", label: "Handover" },
      { href: "/case/index.html", label: "The case" },
    ],
  },
  pill: async () => {
    const o = await window.Shell.api("/api/overview");
    const k = o.kpis;
    return { text: `${o.demo_now.replace("T", " ")} JST · ${k.dr.event_id} ${k.dr.window}`,
             title: "Demo clock and today's DR dispatch. Source: dr_events, demo clock" };
  },
};
