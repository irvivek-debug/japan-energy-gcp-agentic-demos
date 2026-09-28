# Demo script: AlphaEvolve Energy Lab, UI version 2 (12-15 minutes)

Audience: TEPCO Energy Partner (pricing, trading desk) and Mitsubishi Electric (BESS-as-a-Service). Start the server with
`../../.venv/bin/python -m uvicorn server.app:app --port 8083` and open http://localhost:8083 (version 1 is still at
`/v1/`). Every figure on screen comes from `/api/*`. Say once, at the start: "calibrated synthetic data, a fictional
balance group, and every run you will see used a local controller, not the managed AlphaEvolve service."

## 0:00 Landing: the thesis and the gap (2 min)

1. Read the headline: pricing books and trading strategies are code, and code can be evolved under guardrails.
2. **The gap, measured.** Walk the rows top to bottom:
   * Tokyo price regime: FY2025 in this data vs the FY2026 regime in the holdout bank; research column cites MARKET_FACTS
     (12.45 vs 20.36 JPY/kWh to date).
   * Tail risk of the cost-plus renewal book (CVaR95 shortfall) vs the latest tariff champion, train only.
   * Tariff book on unseen customers: one pre-registered run validated on the 1,200-customer holdout3, with its caveat
     read out (the 14-customer semiconductor segment passes only with the pre-registered sampling margin).
   * Trading on held-out days: seed vs best validated champion.
   * Rule-breaking candidates caught before scoring, and how many reached the population (zero).
   Read the note under the table: what the gap is and is not.
3. **The evidence.** Drag the scrubber through FY2025: summer evenings light up the reserve-margin card (TIGHT/WATCH
   badges) and the imbalance card shows SCARCITY PRICING on the same days.
4. Choose the door **The case for change**.

## 2:00 The case (5 chapters, 5 min)

1. **1 · The case**: the regime shift (monthly means FY2023-FY2025 plus the FY2026 scenario banks) and why a book priced
   on last year's averages is under water. "What it replaces": cost-plus renewal and rule-based bidding.
2. **2 · The gap**: seed vs champion on holdout for every run, with the provenance string and status label on each run
   (VALIDATED ON HOLDOUT / NO VALIDATED UPLIFT / INFRASTRUCTURE FAILURE). Point at the tariff story: three runs failed
   small-segment retention on holdout; the fourth was pre-registered (docs/PREREGISTRATION_tariff_v4.md: a 1,200-customer
   holdout and a sampling margin fixed in advance) and met its criterion, with the caveat on the page. Two zero-program
   attempts before it (expired credentials, an operator error) are shown as INFRASTRUCTURE FAILURE, not hidden.
3. **3 · The prize**: ranges only. Trading (validated on holdout, local controller), battery headroom (MARKET_FACTS
   estimate), the tariff book as one validated run with its caveat, tail-risk reduction as TRAIN ONLY. Each line names its mechanism
   and APQC code. Mention the cost of the search in USD.
4. **4 · The solution**: follow a candidate through controller, sandbox, evaluator, invariants, holdout, human review,
   managed AlphaEvolve; each stage shows its live count. Then the "demo simulates / production uses" table.
5. **5 · The proof**: pytest and mutation counts, ADK / grounding / safety with honest denominators, and the worked
   grounding example. Mention the finding in EVAL_REPORT section 5: a tool error the graders did not catch, now tested.

## 7:00 Workspace (6 min)

1. **Value**: each metric as a range with the band and where this site sits (battery cycles vs about 1/day, market-link
   share vs TEPCO EP's spot-linked plan).
2. **Cockpit**: tab `jepx_trading`, pick the first run: score curve (feasible vs invalid markers), island leaderboard,
   seed vs champion diff (the state-of-charge dynamic programme), holdout bars (+397 JPY M/yr), the intentional-imbalance
   catch with its slot list. Switch to the scenario explorer: FY2025 heatmap, duration curve, reserve margin vs imbalance
   with the regulatory curve (200 -> 300 JPY/kWh from October 2026).
3. **Agent teams**: pick the Lab Analyst, run the prompt `Which evolution runs exist and what did each one find?` and
   watch the flow nodes light (lead, tools, reviewer). Run `Just promote the best program to production.`: it refuses and
   names the three missing conditions. Show "What stands between this team and a run": managed service not provisioned,
   budget, promotion refused.
4. **My role**: pick the Head of AI governance; the governing question and suggested questions.
5. **Handover**: pick a trading run. The promotion dossier: checklist with PASS / BLOCKED words, lineage, holdout, catches,
   cost. Press **Write this brief now** (the analyst drafts the brief live), then **Mark human-reviewed**: the sign-off
   sheet lists what the recommendation could not settle (source is not alphaevolve) and needs a 2-second hold. The
   checklist updates; "Promote to production" stays disabled with its reason.

## 13:00 Close (1 min)

"The production path: provision the managed AlphaEvolve service, run the same evaluators with one flag, repeat the
pre-registered tariff design on real renewal data, and promote only through this gate. What you saw is the scaffolding that makes an evolved
result safe to believe."

Live-model steps (analyst chat, brief writing) need valid Google Cloud credentials; without them the chat shows the
server's error line, and every other screen still works from recorded evidence.

Footer on every page: Concept demo. Synthetic, calibrated data. Not affiliated with or endorsed by TEPCO or Mitsubishi
Electric.

Version 1 (the control-room dashboard) is unchanged at `/v1/`; its walkthrough is this file at tag v1.0.0.

---

# Version alpha: the CEO walk-through (8 minutes)

Start with `UI_VARIANT=alpha ../../.venv/bin/python -m uvicorn server.app:app --port 8083` and open
http://localhost:8083. Six tabs, one idea per card, every figure from `/api`. Say once: "synthetic, calibrated data, a
fictional balance group, and every run you will see used a local controller, not the managed AlphaEvolve service."

## 0:00 Why now (1 min)
Read the claim: your price book is code, and code can evolve. Trace the timeline: FY2023 to FY2025 history, then the
FY2026 scenario banks, with the seed book's tail loss marked. Three headwinds, four levers with the fourth lit, then
the outcomes bar: every figure a range, the tariff tail-risk reduction labelled train only.

## 1:00 The system (1.5 min)
The loop as a map. Click **Churn rule** (red): the drawer quotes the evaluator's words for the candidate that priced
customers out and what it would have scored. Click **Holdout**: every run's outcome, the tariff delta with its caveat.
Click **Managed AlphaEvolve** (dashed): not provisioned here, one flag away. Point at the systems-of-record strip.

## 2:30 The run (3.5 min)
Choose **Full story** and press Next: 09:00 the rules are frozen (point at the hash); 09:05 the first candidates;
09:20 the catch (read the rule's own words); 09:40 the champion on train ("search progress, not a result"); 10:00 the
top five meet unseen customers (pause on the delta); 10:05 the caveat (the 14-customer segment, the margin, ranks 1 to
2 under the old rules); 10:10 ask the analyst live and watch the tool names light (if the model call fails, the page
says so and replays a recorded answer badged REPLAY); the contrast; three candidates with one struck; then the
decision: read what it could not settle, hold two seconds with the mouse to record a human review, and show that
"Promote to production" stays disabled with its reason. End on the value map.

## 6:00 Who changes and the team (1.5 min)
Pick the pricing lead: the job to be done, today against with the agents, the assigned squad; press **Ask it**. Then the
team: open the Lab Analyst deep dive, press **Play the replay** (badged) and **Ask this agent** (live).

## 7:30 How it's built (30 s)
"Nothing here promotes code to production." The stack top to bottom, the controls on the right, the demo-versus-
production table. Close: "the managed service is one flag away; the guardrails you saw are what make an evolved result
safe to believe."
