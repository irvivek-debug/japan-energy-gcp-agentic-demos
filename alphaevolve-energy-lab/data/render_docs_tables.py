"""Fill the generated tables into docs/SCENARIO_AND_DATA.md (between marker comments). Numbers come from data/out."""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
doc = ROOT / "docs" / "SCENARIO_AND_DATA.md"
rows = [r for r in csv.DictReader(open(ROOT / "data" / "out" / "calibration.csv")) if r["target"] and not r["metric"].startswith("monthly")]
lines = ["| FY | Metric | Synthetic | MARKET_FACTS | Rel. error | MF section |", "|---|---|---|---|---|---|"]
for r in rows:
    flag = " (!)" if abs(float(r["rel_error_pct"])) > 10 else ""
    lines.append(f"| {r['fiscal_year']} | {r['metric']} | {float(r['synthetic']):.4g} | {float(r['target']):.4g} | {float(r['rel_error_pct']):+.1f}%{flag} | {r['market_facts_section']} |")
table = "\n".join(lines) + "\n\n(!) = more than 10% off; see Honest misses."
spike = (ROOT / "docs" / "figures" / "spike_frequency.md").read_text().strip()
s = doc.read_text()
def put(s, marker, content):
    pat = re.compile(rf"<!-- {marker} -->.*?(<!-- /{marker} -->)", re.S)
    block = f"<!-- {marker} -->\n{content}\n<!-- /{marker} -->"
    return pat.sub(lambda m: block, s) if pat.search(s) else s.replace(f"<!-- {marker} -->", block)
s = put(s, "CALIBRATION_TABLE", table)
s = put(s, "SPIKE_TABLE", spike)
doc.write_text(s)
print("filled", doc)
