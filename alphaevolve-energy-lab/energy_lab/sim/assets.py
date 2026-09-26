"""KBG physical assets: 8-site BESS fleet (BESS-as-a-Service) and a 40 MW solar PPA. Fictional sites.

Battery parameters follow MARKET_FACTS 12 (RTE 85% AC-AC, NREL ATB 2024; degradation ~8 JPY/kWh discharged,
ESTIMATE from MRI/METI capex / 6,000 cycles). SOC window, cycle and warranty limits are LAB-ASSUMPTIONS typical of
LFP warranties. The fleet is dispatched as one aggregate (60 MW / 180 MWh) by the trading strategy.
"""
from __future__ import annotations

from . import facts

BESS_SITES = [
    # site_id, name, prefecture, MW, MWh, duration_h, commissioned, grid voltage
    ("B01", "Inzai North", "Chiba", 10.0, 20.0, 2, "2024-10", "EHV"),
    ("B02", "Sagamihara Depot", "Kanagawa", 7.5, 15.0, 2, "2025-03", "EHV"),
    ("B03", "Kawagoe Logistics Park", "Saitama", 7.5, 15.0, 2, "2025-06", "HV"),
    ("B04", "Oyama Works", "Tochigi", 5.0, 10.0, 2, "2025-09", "HV"),
    ("B05", "Kashima Coast", "Ibaraki", 10.0, 40.0, 4, "2025-12", "EHV"),
    ("B06", "Tama Data Campus", "Tokyo", 7.5, 30.0, 4, "2026-02", "EHV"),
    ("B07", "Mooka Cold Chain", "Tochigi", 7.5, 30.0, 4, "2026-04", "HV"),
    ("B08", "Kisarazu Port", "Chiba", 5.0, 20.0, 4, "2026-06", "HV"),
]
FLEET_MW = sum(s[3] for s in BESS_SITES)            # 60 MW
FLEET_MWH = sum(s[4] for s in BESS_SITES)           # 180 MWh

BESS = {
    "power_mw": FLEET_MW,
    "energy_mwh": FLEET_MWH,
    "rte": facts.BESS_RTE,
    "eta_charge": facts.BESS_RTE ** 0.5,
    "eta_discharge": facts.BESS_RTE ** 0.5,
    "soc_min_frac": 0.10,
    "soc_max_frac": 0.95,
    "soc_start_frac": 0.50,
    "degradation_jpy_per_mwh": facts.BESS_DEGRADATION_JPY_KWH * 1000.0,
    "max_cycles_per_day": 2.0,                       # discharge throughput <= 2 x energy per day
    "warranty_cycles_per_year": 450.0,               # annual discharge throughput <= 450 x energy
    "aux_loss_mw": 0.0,
}

PV_PPA = {"name": "Kanto Solar PPA (fictional)", "capacity_mw": 40.0, "sites": 6, "prefectures": "Ibaraki, Chiba, Tochigi",
          "contract": "physical PPA, 20 years; energy cost is sunk and not part of the trading score"}
