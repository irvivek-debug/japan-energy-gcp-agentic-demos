"""Calibration figures for docs/SCENARIO_AND_DATA.md (dependency-free SVG; reads data/out CSVs).

    python data/make_figures.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from energy_lab.sim import facts  # noqa: E402

OUT = ROOT / "docs" / "figures"
PALETTE = ["#7fd1c7", "#e0a458", "#a7caed", "#c792ea", "#ff8a80"]
BG, FG, MUTED, GRID = "#131313", "#e4e2e1", "#a0a3a8", "#2a2f38"


def svg_lines(path: Path, title: str, series: list[tuple[str, list[float], list[float], str]], xlabel: str, ylabel: str,
              w: int = 760, h: int = 360, ylog: bool = False, ymin: float | None = None, ymax: float | None = None) -> None:
    ml, mr, mt, mb = 64, 170, 40, 48
    xs = [x for _, xv, _, _ in series for x in xv]
    ys = [y for _, _, yv, _ in series for y in yv if y is not None]
    x0, x1 = min(xs), max(xs)
    y0 = ymin if ymin is not None else min(ys)
    y1 = ymax if ymax is not None else max(ys)
    if ylog:
        y0, y1 = np.log10(max(y0, 0.5)), np.log10(y1)

    def X(x):
        return ml + (x - x0) / (x1 - x0 or 1) * (w - ml - mr)

    def Y(y):
        v = np.log10(max(y, 0.5)) if ylog else y
        return mt + (1 - (v - y0) / (y1 - y0 or 1)) * (h - mt - mb)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="Inter, sans-serif">',
             f'<rect width="{w}" height="{h}" fill="{BG}"/>',
             f'<text x="{ml}" y="24" fill="{FG}" font-size="15" font-weight="600">{title}</text>']
    for k in range(6):
        yy = mt + k * (h - mt - mb) / 5
        val = y1 - k * (y1 - y0) / 5
        lab = f"{10 ** val:.0f}" if ylog else f"{val:.1f}"
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w - mr}" y2="{yy:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" fill="{MUTED}" font-size="11" text-anchor="end">{lab}</text>')
    for k in range(6):
        xx = ml + k * (w - ml - mr) / 5
        parts.append(f'<text x="{xx:.1f}" y="{h - mb + 18}" fill="{MUTED}" font-size="11" text-anchor="middle">{x0 + k * (x1 - x0) / 5:.0f}</text>')
    parts.append(f'<text x="{(ml + w - mr) / 2}" y="{h - 8}" fill="{MUTED}" font-size="12" text-anchor="middle">{xlabel}</text>')
    parts.append(f'<text x="14" y="{(mt + h - mb) / 2}" fill="{MUTED}" font-size="12" transform="rotate(-90 14 {(mt + h - mb) / 2})" text-anchor="middle">{ylabel}</text>')
    for i, (name, xv, yv, style) in enumerate(series):
        col = PALETTE[i % len(PALETTE)]
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xv, yv) if y is not None)
        dash = ' stroke-dasharray="5 4"' if style == "dash" else ""
        if style == "dots":
            parts += [f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.2" fill="{col}" fill-opacity="0.6"/>' for x, y in zip(xv, yv)]
        else:
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"{dash}/>')
        ly = mt + 16 + i * 20
        parts.append(f'<line x1="{w - mr + 12}" y1="{ly - 4}" x2="{w - mr + 34}" y2="{ly - 4}" stroke="{col}" stroke-width="2"{dash}/>')
        parts.append(f'<text x="{w - mr + 40}" y="{ly}" fill="{FG}" font-size="11">{name}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(ROOT / "data" / "out" / "market_history.csv")))
    by_fy = defaultdict(list)
    for r in rows:
        by_fy[int(r["fiscal_year"])].append(r)
    # 1. price duration curves
    series = []
    for fy in (2023, 2024, 2025):
        p = np.sort(np.array([float(r["tokyo_price_jpy_kwh"]) for r in by_fy[fy]]))[::-1]
        idx = np.linspace(0, len(p) - 1, 200).astype(int)
        series.append((f"FY{fy} synthetic", list(100 * idx / (len(p) - 1)), list(p[idx]), "line"))
    svg_lines(OUT / "price_duration.svg", "Tokyo area price duration curve (synthetic, calibrated)", series,
              "% of half-hours exceeded", "JPY/kWh", ymin=0, ymax=50)
    # 2. intraday shape vs MARKET_FACTS FY2025 by season
    season_months = {"spring": (3, 4, 5), "summer": (6, 7, 8, 9), "autumn": (10, 11), "winter": (12, 1, 2)}
    series = []
    for k, (season, months) in enumerate(season_months.items()):
        acc = defaultdict(list)
        for r in by_fy[2025]:
            if int(r["month"]) in months:
                acc[int(r["hour"])].append(float(r["tokyo_price_jpy_kwh"]))
        syn = [float(np.mean(acc[h])) for h in range(24)]
        series.append((f"{season} synthetic", list(range(24)), syn, "line"))
        series.append((f"{season} MARKET_FACTS", list(range(24)), facts.HOURLY_SHAPE_FY2025[season], "dash"))
    svg_lines(OUT / "intraday_shape_fy2025.svg", "FY2025 hour-of-day mean price: synthetic (solid) vs MARKET_FACTS 1.4 (dashed)",
              series[:4] + series[4:8], "hour of day (JST)", "JPY/kWh", w=820, ymin=6, ymax=20)
    # 3. monthly means vs targets FY2025
    months_fy = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    syn = [float(np.mean([float(r["tokyo_price_jpy_kwh"]) for r in by_fy[2025] if int(r["month"]) == m])) for m in months_fy]
    svg_lines(OUT / "monthly_fy2025.svg", "FY2025 monthly mean Tokyo price: synthetic vs MARKET_FACTS 1.3", [
        ("synthetic", list(range(1, 13)), syn, "line"), ("MARKET_FACTS", list(range(1, 13)), facts.TOKYO_MONTHLY_FY2025, "dash")],
        "fiscal month (1 = April)", "JPY/kWh", ymin=10, ymax=15)
    # 4. reserve margin vs imbalance price with the scarcity curve
    from energy_lab.sim.market import scarcity_curve

    pts = [(float(r["reserve_margin_pct"]), float(r["imbalance_price_jpy_kwh"])) for r in by_fy[2025] if float(r["reserve_margin_pct"]) < 16]
    curve_x = list(np.linspace(0, 16, 65))
    series = [("FY2025 slots (RM < 16%)", [p[0] for p in pts], [p[1] for p in pts], "dots"),
              ("scarcity curve C=200, D=45", curve_x, [float(scarcity_curve(x / 100, 200.0, 45.0)) for x in curve_x], "line"),
              ("from 2026-10: C=300, D=50", curve_x, [float(scarcity_curve(x / 100, 300.0, 50.0)) for x in curve_x], "dash")]
    svg_lines(OUT / "scarcity_curve.svg", "Imbalance price vs wide-area reserve margin (MARKET_FACTS 3)", series,
              "reserve margin (%)", "JPY/kWh", ymin=0, ymax=310)
    # 5. spike frequency: slots above thresholds by FY vs MARKET_FACTS (imbalance >= 45 and >= 100)
    lines = ["| FY | spot >= 30 | spot >= 40 | spot max | imbalance >= 45 | imbalance >= 100 | imbalance max | MARKET_FACTS reference |",
             "|---|---|---|---|---|---|---|---|"]
    ref = {2023: "Tokyo max 50.00", 2024: "Tokyo max 49.65; imbalance max 194.11",
           2025: "Tokyo max 45.01; imbalance >=45: 38, >=100: 8, max 131.49"}
    for fy in (2023, 2024, 2025):
        p = np.array([float(r["tokyo_price_jpy_kwh"]) for r in by_fy[fy]])
        im = np.array([float(r["imbalance_price_jpy_kwh"]) for r in by_fy[fy]])
        lines.append(f"| FY{fy} | {(p >= 30).sum()} | {(p >= 40).sum()} | {p.max():.2f} | {(im >= 45).sum()} | {(im >= 100).sum()} | "
                     f"{im.max():.2f} | {ref[fy]} |")
    (OUT / "spike_frequency.md").write_text("\n".join(lines) + "\n")
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
