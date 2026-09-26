"""KBG FY2026 C&I renewal price book. Only the EVOLVE-BLOCK is searched; the helpers above it are fixed.

price_book(customer, market) -> offer dict, called once per customer with read-only inputs.
"""
import math


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def loss_factor(customer, market):
    return market["loss_factor"][customer["voltage"]]


def energy_cost_jpy_kwh(customer, market):
    """Expected JEPX energy cost for this customer's load shape at the pricing-time forward, incl. losses."""
    return customer["expected_energy_cost_jpy_kwh"] * loss_factor(customer, market)


def non_energy_cost_jpy_kwh(customer, market):
    """Per-kWh wheeling energy charge, capacity contribution, balancing overhead and NFC (green products)."""
    cs = market["cost_stack"]
    c = cs["wheeling_energy_jpy_kwh"][customer["voltage"]] + customer["capacity_cost_jpy_kwh"]
    c += cs["balancing_overhead_jpy_kwh"]
    if customer["green_required"]:
        c += cs["nfc_renewable_jpy_kwh"]
    return c


def wheeling_basic_jpy_kw_month(customer, market):
    """Year-average wheeling basic charge (tariff rises in November 2026)."""
    b = market["cost_stack"]["wheeling_basic_jpy_kw_month"][customer["voltage"]]
    return (b["Apr-Oct"] * 7 + b["Nov-Mar"] * 5) / 12.0


def segment_reference(customer, market):
    return market["segment_reference_jpy_kwh"][customer["segment"]][customer["voltage"]]


# EVOLVE-BLOCK-START
def price_book(customer, market):
    """Seed: cost-plus. Fixed margin on expected cost; market link only for data centers."""
    margin = 1.5
    energy = energy_cost_jpy_kwh(customer, market)
    other = non_energy_cost_jpy_kwh(customer, market)
    alpha = 0.5 if customer["segment"] == "data_center" else 0.0
    return {
        "energy_rate_jpy_kwh": round(energy + other + margin, 3),
        "alpha": alpha,
        "market_adder_jpy_kwh": round(other + margin, 3),
        "demand_charge_jpy_kw_month": round(wheeling_basic_jpy_kw_month(customer, market) + 50.0, 1),
        "deviation_band_pct": 10.0,
        "deviation_penalty_jpy_kwh": 1.0,
        "dr_discount_jpy_kw_month": 0.0,
        "term_years": 1,
    }
# EVOLVE-BLOCK-END
