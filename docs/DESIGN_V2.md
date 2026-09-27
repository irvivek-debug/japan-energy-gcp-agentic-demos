# UI Version 2: the "mining" design language

Version 1 of the three demos opened on a dense control-room dashboard. Version 2 adopts the design language of the
owner's mining agents reference application: an **editorial, CEO-first argument** that earns the right to show the
operational workspace. The v1 screens stay reachable at `/v1/` for comparison.

Kit (copy into each demo's `ui/`, never import across demos): [`docs/reference/ui-v2/`](reference/ui-v2/)
`kit.css` (tokens + components), `shell.js` (top bar, drawer, provenance, `fig`, `api`), `motion.js` (reveal, countUp),
`signoff.js` (sign-off sheet with the 2 s hold). Charts stay on ECharts, restyled to the tokens (no gradients, 1px
grid lines in `--border-soft`, axis labels in `--mono` 10.5px `--fg-muted`, series colours from `--b1..--b6`).

## 1. Information architecture (three families, same in every demo)

| Route | Family | Purpose | Reader |
|---|---|---|---|
| `/` | **Landing** | The thesis, the gap measured in this data against cited research, the evidence, then two doors | Executive, first 60 seconds |
| `/case/` ... | **The case for change** (5 numbered chapters) | `1 · The case` → `2 · The gap` → `3 · The prize` → `4 · The solution` → `5 · The proof` | Executive deciding whether the gap is real |
| `/workspace/` ... | **Workspace** | `Value` · `Cockpit` · `Agent teams` · `My role` · `Handover` | Someone who has decided and wants to use it |
| `/v1/` | Version 1 | Unchanged v1 dashboard | Comparison |

### Landing (`/`)
1. **Hero**: eyebrow (product name), one plain thesis sentence as `h1` (max ~18 words, no technology), two lede
   paragraphs that state the business gap in this data with real figures from `/api`.
2. **The gap, measured**: a table `Quantity | Ordinary | Best / target | The gap | What the research says is available`,
   4-6 rows, every research cell cited in small mono caps (source from `docs/research/MARKET_FACTS.md`; if no benchmark
   exists write `NO VERIFIED BENCHMARK HELD`), followed by a `.note` stating what the gap is and is not.
3. **The evidence**: a time scrubber (range input over the data window) and 4-6 sparkline cards of the assets/markets the
   figures came off (value, unit, status badge, sparkline). Moving the scrubber updates every card.
4. **Where to start**: two door cards, "The case for change" and "The workspace", each with 3 counted facts and a button.
5. **Provenance** footer (`Shell.provenance`) listing tables, generator seed, data window, and the disclaimer.

### The case (`/case/index.html`, `gap.html`, `prize.html`, `solution.html`, `proof.html`)
Editorial column (`.read`, 720px) with wide cards where data needs room. Each chapter: eyebrow, a statement headline
(not a label), lede, 2-4 evidence blocks, "What it replaces" (before/after), a `Technical detail` drawer, provenance,
and a `Next:` button to the next chapter. Chapter 3 shows **value as ranges only** (low-high bars, mechanism named on
every line, MECE branches coloured `--b1..--b6` with their code printed). Chapter 4 shows how a question moves through
the agents and a "demo simulates / production uses" architecture. Chapter 5 (`The proof`) is the evaluation: what was
tested, pass counts with honest denominators, and one worked grounding example.

### Workspace (`/workspace/`)
* **Value** (first in the nav): the metrics the agents move, each as a range with the industry band and where this site sits.
* **Cockpit** (`index.html`): the v1 operational panels, restyled: KPI row with counted metrics, the main charts, the
  approval queue. Header states counts ("N agents you can talk to · M need your sign-off").
* **Agent teams** (`swarm.html`): left list of teams/agents with `SIGN-OFF` badges; right "How the question moves":
  `1 · The lead` → `2 · Specialists, working together` → `3 · The reviewer` → `4 · Your sign-off`, each a `.flow-node`
  that lights (`.active`) as the live SSE trace reaches it; a trace console below; a scenario prompt runner. Also a
  "What stands between this team and a run" list (honest limits).
* **My role** (`persona.html`): role picker (the PRD personas), "What you're answerable for", "Your governing question",
  the agents you ask (cards with pattern, sign-off, what they read), suggested questions and a chat side panel.
* **Handover** (`handover.html`): a brief the agents write on request for the next shift/desk, sections per team, each
  starting in an honest `Not yet written` state; `Write this brief now` runs the orchestrator; `Print this brief`.
* Any `pending_action` opens through `SignOff.open(...)`, never inline buttons.

## 2. Visual rules
* Tokens exactly as `kit.css`: `#131313` canvas, `#1F2020` surfaces, 1px `#374151` borders, **12px card radius, 8px
  badges, pill buttons, square tables/consoles/charts**. No shadows, no gradients, no gloss.
* Type: Bricolage Grotesque (display, 700), Work Sans (body 15px), JetBrains Mono (eyebrows, nav, captions, figures in
  tables). Metrics use tabular numerals and count up once (`Motion.countUp`).
* Motion: `.reveal` in reading order, 560ms emphasized ease, reduced motion paints the final state. Only cards that lead
  somewhere lift on hover.
* 44x44px targets, 8px gaps; colour is never the only signal (always a code or word next to a hue).
* Per-demo accent: TEPCO `#a7caed`, MELCO `#c4b0e8`, Lab `#8fd0bc` (set `--accent` only; everything else is shared).

## 3. Voice
* Lead with value and the gap in the customer's own data; technology appears only from chapter 4 and the workspace.
* Plain sentences, active voice, no em or en dashes in UI copy, none of: delve, tapestry, testament, underscore, elevate,
  crucial, pivotal, vital, foster, vibrant, intricate, landscape, showcase, boasts.
* Value as ranges, never a single point. Every research figure carries its source.
* Honesty strings are part of the design: a missing figure renders `NOT IN THE DATA`; a section no agent has written
  says so; the Lab says `local controller, not the managed AlphaEvolve service` wherever a run is shown.

## 4. Engineering rules
* Every figure on every screen comes from `/api/*` (existing endpoints first; add read-only endpoints when needed).
  No hand-typed numbers in HTML/JS.
* Serve `ui/` at `/` with the three families as real files; keep v1 at `ui/v1/` served at `/v1/`.
* Verify: `node --check` on every JS file; TestClient tests for any new endpoint; render every page headless and assert
  zero console errors; screenshots at 1440px and 390px wide with no horizontal page scroll.
