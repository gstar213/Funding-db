"""
reprocess_unknowns.py — Fix existing "Unknown" company names in funding.db
Run once: python reprocess_unknowns.py
"""

import sqlite3
import sys
from pathlib import Path

# Make sure we can import extractor from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from extractor import parse_company

DB_PATH = Path(__file__).parent / "funding.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Fetch all Unknown rows
rows = conn.execute("""
    SELECT id, headline, description
    FROM funding_rounds
    WHERE company_name = 'Unknown'
""").fetchall()

print(f"Found {len(rows)} rows with Unknown company name. Re-processing...")

fixed = 0
still_unknown = 0

for row in rows:
    headline = row["headline"] or ""
    description = row["description"] or ""
    new_name = parse_company(headline, description)

    if new_name != "Unknown":
        conn.execute(
            "UPDATE funding_rounds SET company_name = ? WHERE id = ?",
            (new_name, row["id"])
        )
        fixed += 1
        print(f"  [FIXED] id={row['id']}  '{headline[:60]}' -> '{new_name}'")
    else:
        still_unknown += 1

conn.commit()
conn.close()

print(f"\nDone! Fixed: {fixed}  Still Unknown: {still_unknown}")
if still_unknown > 0:
    print("Tip: rows still Unknown likely have headlines that mention funding without")
    print("     a recognisable company pattern. They can be deleted with:")
    print("     DELETE FROM funding_rounds WHERE company_name = 'Unknown';")
