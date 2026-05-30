"""
export_csv.py — Export funding_rounds to a clean CSV snapshot.
Output: funding_rounds_export.csv
"""
import sqlite3, csv
from pathlib import Path
from datetime import datetime

conn = sqlite3.connect(Path(__file__).parent / "funding.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT
        company_name, company_domain, hq_country, hq_city, region,
        round_type, stage, amount_display, amount_usd,
        sector, sub_sector, lead_investor, investors_raw,
        founder_name, founder_linkedin,
        announced_date, announced_year, announced_month,
        source_name, source_url, headline, confidence
    FROM funding_rounds
    WHERE company_name != 'Unknown'
    ORDER BY announced_date DESC
""").fetchall()
conn.close()

out = Path(__file__).parent / "funding_rounds_export.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows([dict(r) for r in rows])

print(f"Exported {len(rows)} rows to {out}")
print(f"File size: {out.stat().st_size / 1024:.1f} KB")
