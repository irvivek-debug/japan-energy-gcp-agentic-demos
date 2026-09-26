"""CFE provenance tools: hourly (24/7) vs annual matching scores and the 30-minute NFC ledger audit.

24/7 CFE score (Google method, MARKET_FACTS 6.4):
  contracted hourly-matched = sum_h min(load_h, allocated_clean_h)
  grid CFE contribution     = sum_h (load_h - matched_h) x grid_cfe_share_h
  CFE score                 = (contracted matched + grid contribution) / sum_h load_h
  annual/volumetric matched = sum_h allocated_clean_h / sum_h load_h (can exceed 100 %; excess hours do not carry over)
"""
from __future__ import annotations

from ..store import STORE, src
from ._common import err, r2, safe_tool

LEDGER_START = "2026-08-01"


@safe_tool
def list_cfe_customers() -> dict:
    """List existing customers with clean-energy (CFE) supply contracts, their product (hourly_24x7 or
    annual_volumetric) and contracted demand."""
    rows = STORE.query("SELECT customer_id, name, segment, cfe_product, contracted_kw FROM {t:customers} "
                       "WHERE cfe_contract = TRUE ORDER BY customer_id")
    return {"status": "ok", "customers": rows, "source": src("customers")}


def cfe_score(customer_id: str, month: str) -> dict | None:
    rows = STORE.query(
        """
        SELECT SUM(a.load_mwh) AS load_mwh, SUM(a.allocated_cfe_mwh) AS alloc_mwh,
               SUM(LEAST(a.load_mwh, a.allocated_cfe_mwh)) AS matched_mwh,
               SUM((a.load_mwh - LEAST(a.load_mwh, a.allocated_cfe_mwh)) * g.grid_cfe_share_pct / 100.0) AS grid_cfe_mwh,
               SUM(GREATEST(a.allocated_cfe_mwh - a.load_mwh, 0)) AS excess_mwh,
               SUM(CASE WHEN a.allocated_cfe_mwh < 0.5 * a.load_mwh THEN 1 ELSE 0 END) AS hours_below_half,
               COUNT(*) AS hours, MIN(a.date) AS first_date, MAX(a.date) AS last_date
        FROM {t:cfe_allocation_hourly} a
        JOIN {t:grid_mix_hourly} g ON g.date = a.date AND g.hour = a.hour
        WHERE a.customer_id = @c AND a.month = @m
        """, c=customer_id, m=month)
    if not rows or not rows[0]["hours"]:
        return None
    by_hour = STORE.query(
        "SELECT hour, SUM(LEAST(load_mwh, allocated_cfe_mwh)) / SUM(load_mwh) * 100 AS pct "
        "FROM {t:cfe_allocation_hourly} WHERE customer_id = @c AND month = @m GROUP BY hour ORDER BY hour", c=customer_id, m=month)
    return {**rows[0], "by_hour": by_hour}


@safe_tool
def get_cfe_score(customer_id: str, month: str) -> dict:
    """Carbon-free energy score for an existing customer and month: contracted clean energy matched hour by hour,
    the grid's hourly carbon-free contribution, the resulting 24/7 CFE score, and the annual-style volumetric match
    for comparison, plus the hour-of-day profile and certificate-ledger findings that affect this customer.

    Args:
      customer_id: Customer id with a CFE contract, for example C-0001 (see list_cfe_customers).
      month: Month YYYY-MM (2026-07 full month; 2026-08 month to date, to 2026-08-19 15:00).
    """
    cid = str(customer_id).upper().strip()
    cust = STORE.query("SELECT customer_id, name, cfe_product FROM {t:customers} WHERE customer_id = @c", c=cid)
    if not cust:
        return err(f"unknown customer {customer_id}")
    s = cfe_score(cid, month)
    if s is None:
        return {"status": "not_found", "customer_id": cid, "month": month,
                "note": "CFE allocations exist for CFE-contract customers in 2026-07 and 2026-08 (to date)",
                "source": src("cfe_allocation_hourly")}
    L = s["load_mwh"]
    findings = []
    if month >= "2026-08":
        a = nfc_audit(month)
        for kind in ("double_claims", "claims_without_generation", "expired_or_wrong_vintage"):
            for f in a[kind]:
                if cid in f.get("customers", [f.get("customer_id")]):
                    findings.append({"type": kind, "certificate_id": f["certificate_id"]})
    worst = sorted(s["by_hour"], key=lambda r: r["pct"])[:3]
    return {
        "status": "ok", "customer_id": cid, "name": cust[0]["name"], "cfe_product": cust[0]["cfe_product"], "month": month,
        "period": f"{s['first_date']} to {s['last_date']}", "hours": int(s["hours"]),
        "load_mwh": r2(L, 1), "contracted_clean_mwh": r2(s["alloc_mwh"], 1),
        "annual_style_volumetric_match_pct": r2(100 * s["alloc_mwh"] / L, 1),
        "contracted_hourly_matched_pct": r2(100 * s["matched_mwh"] / L, 1),
        "grid_cfe_contribution_pct": r2(100 * s["grid_cfe_mwh"] / L, 1),
        "cfe_score_24x7_pct": r2(100 * (s["matched_mwh"] + s["grid_cfe_mwh"]) / L, 1),
        "excess_clean_mwh_not_counted": r2(s["excess_mwh"], 1),
        "hours_below_50pct_matched": int(s["hours_below_half"]),
        "weakest_hours_of_day": [{"hour": int(w["hour"]), "matched_pct": r2(w["pct"], 1)} for w in worst],
        "certificate_ledger_findings": findings,
        "method": "24/7 CFE = contracted clean matched hour by hour (capped at load each hour) + grid hourly CFE share on "
                  "the remainder; excess in one hour never offsets another [desk_policy_guide.md Section 8].",
        "source": src("cfe_allocation_hourly", "grid_mix_hourly", "customers"),
    }


def nfc_audit(month: str) -> dict:
    fy = f"FY{int(month[:4]) - (1 if int(month[5:7]) < 4 else 0)}"
    base = STORE.query("SELECT COUNT(*) AS entries, COUNT(DISTINCT certificate_id) AS certs, SUM(mwh) AS mwh, "
                       "COUNT(DISTINCT claimed_by_customer_id) AS customers FROM {t:nfc_ledger} WHERE claim_month = @m", m=month)[0]
    dup = STORE.query(
        """
        WITH d AS (SELECT certificate_id FROM {t:nfc_ledger} WHERE claim_month = @m
                   GROUP BY certificate_id HAVING COUNT(DISTINCT claimed_by_customer_id) > 1)
        SELECT l.entry_id, l.certificate_id, l.claimed_by_customer_id, l.mwh, l.resource_id, l.generation_start, l.claim_date
        FROM {t:nfc_ledger} l JOIN d ON d.certificate_id = l.certificate_id
        WHERE l.claim_month = @m ORDER BY l.certificate_id, l.claim_date
        """, m=month)
    doubles: dict[str, dict] = {}
    for r in dup:
        d = doubles.setdefault(r["certificate_id"], {"certificate_id": r["certificate_id"], "resource_id": r["resource_id"],
                                                     "generation_start": r["generation_start"], "mwh": r2(r["mwh"], 4),
                                                     "customers": [], "entries": [], "claim_dates": []})
        d["customers"].append(r["claimed_by_customer_id"])
        d["entries"].append(r["entry_id"])
        d["claim_dates"].append(r["claim_date"])
    expired = STORE.query(
        "SELECT entry_id, certificate_id, claimed_by_customer_id AS customer_id, vintage_fy, expiry_date, claim_date, mwh "
        "FROM {t:nfc_ledger} WHERE claim_month = @m AND (claim_date > expiry_date OR vintage_fy <> @fy)", m=month, fy=fy)
    nogen = STORE.query(
        """
        WITH c AS (
          SELECT resource_id, generation_date, generation_hour, generation_slot, SUM(mwh) AS cert_mwh
          FROM {t:nfc_ledger} WHERE claim_month = @m AND vintage_fy = @fy AND generation_date >= @start
          GROUP BY resource_id, generation_date, generation_hour, generation_slot)
        SELECT c.resource_id, c.generation_date, c.generation_hour, c.generation_slot, c.cert_mwh,
               COALESCE(g.generation_mwh, 0) / 2.0 AS generation_in_slot_mwh
        FROM c LEFT JOIN {t:clean_supply_hourly} g
          ON g.resource_id = c.resource_id AND g.date = c.generation_date AND g.hour = c.generation_hour AND g.period = 'actual'
        WHERE c.cert_mwh > COALESCE(g.generation_mwh, 0) / 2.0 + 0.01
        """, m=month, fy=fy, start=LEDGER_START)
    ghost = []
    for g in nogen:
        ents = STORE.query("SELECT entry_id, certificate_id, claimed_by_customer_id, mwh FROM {t:nfc_ledger} WHERE claim_month = @m "
                           "AND resource_id = @r AND generation_date = @d AND generation_slot = @s",
                           m=month, r=g["resource_id"], d=g["generation_date"], s=int(g["generation_slot"]))
        for e in ents:
            ghost.append({"entry_id": e["entry_id"], "certificate_id": e["certificate_id"], "customer_id": e["claimed_by_customer_id"],
                          "resource_id": g["resource_id"], "generation_slot_start": f"{g['generation_date']} slot {g['generation_slot']}",
                          "certified_mwh": r2(g["cert_mwh"], 3), "metered_generation_mwh": r2(g["generation_in_slot_mwh"], 3)})
    return {"month": month, "fy": fy, "base": base, "double_claims": list(doubles.values()),
            "claims_without_generation": ghost,
            "expired_or_wrong_vintage": [{**e, "mwh": r2(e["mwh"], 3)} for e in expired]}


@safe_tool
def audit_nfc_ledger(month: str) -> dict:
    """Audit the 30-minute non-fossil certificate claim ledger for one consumption month: certificates claimed by more
    than one customer (double counting), claims with no matching metered generation in that resource and 30-minute
    slot, and claims past expiry or from a different fiscal-year vintage. The 30-minute ledger is a provenance pilot
    that starts 2026-08-01.

    Args:
      month: Consumption month YYYY-MM, for example 2026-08.
    """
    if len(str(month)) != 7 or str(month)[4] != "-":
        return err("month must be YYYY-MM")
    a = nfc_audit(month)
    if not a["base"]["entries"]:
        return {"status": "not_found", "month": month,
                "note": f"The 30-minute certificate ledger pilot starts {LEDGER_START}; no entries for {month}.",
                "source": src("nfc_ledger")}
    affected = sorted({c for d in a["double_claims"] for c in d["customers"]} | {g["customer_id"] for g in a["claims_without_generation"]}
                      | {e["customer_id"] for e in a["expired_or_wrong_vintage"]})
    names = {r["customer_id"]: r["name"] for r in STORE.query("SELECT customer_id, name FROM {t:customers} WHERE cfe_contract = TRUE")}
    n_find = len(a["double_claims"]) + len(a["claims_without_generation"]) + len(a["expired_or_wrong_vintage"])
    return {
        "status": "ok", "month": month, "fiscal_year": a["fy"],
        "entries_checked": int(a["base"]["entries"]), "certificates": int(a["base"]["certs"]),
        "claimed_mwh": r2(a["base"]["mwh"], 1), "customers": int(a["base"]["customers"]),
        "findings_total": n_find,
        "double_claims": a["double_claims"],
        "claims_without_generation": a["claims_without_generation"],
        "expired_or_wrong_vintage": a["expired_or_wrong_vintage"],
        "affected_customers": [{"customer_id": c, "name": names.get(c)} for c in affected],
        "required_actions": [
            "Suspend both claims on a double-counted certificate until the ledger owner restates one [desk_policy_guide.md Section 8].",
            "Void claims that have no matching metered generation [desk_policy_guide.md Section 8].",
            "Void expired or wrong-vintage claims and replace them with current-vintage certificates [desk_policy_guide.md Section 8].",
        ],
        "source": src("nfc_ledger", "clean_supply_hourly", "customers"),
    }
