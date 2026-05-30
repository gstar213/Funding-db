"""
enrich_missing.py — Second-pass enrichment for rows missing country/sector.
Re-runs geography + sector extraction on the headline + description fields.
"""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from extractor import parse_geography, classify_sector

conn = sqlite3.connect(Path(__file__).parent / "funding.db")

# Rows missing country OR sector
rows = conn.execute("""
    SELECT id, headline, description
    FROM funding_rounds
    WHERE (hq_country IS NULL OR sector IS NULL)
    AND (headline IS NOT NULL OR description IS NOT NULL)
""").fetchall()

print(f"Rows needing enrichment: {len(rows)}")
country_fixed = sector_fixed = 0

for row_id, headline, description in rows:
    text = f"{headline or ''} {description or ''}"
    country, city, region = parse_geography(text)
    sector, sub_sector = classify_sector(text)

    updates = {}
    if country: updates["hq_country"] = country
    if city:    updates["hq_city"] = city
    if region:  updates["region"] = region
    if sector:  updates["sector"] = sector
    if sub_sector: updates["sub_sector"] = sub_sector

    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE funding_rounds SET {set_clause} WHERE id=? AND ({' OR '.join(f'{k} IS NULL' for k in updates)})",
            list(updates.values()) + [row_id]
        )
        if "hq_country" in updates: country_fixed += 1
        if "sector" in updates: sector_fixed += 1

conn.commit()
conn.close()
print(f"Fixed country: {country_fixed} rows")
print(f"Fixed sector:  {sector_fixed} rows")
print("Done.")
