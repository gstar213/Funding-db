"""
dedup.py — Find and merge near-duplicate funding rounds.
Duplicates = same company + same round_type + same year, from different sources.
Keeps the row with highest confidence, merges source info into it.
"""
import sqlite3
from pathlib import Path
from difflib import SequenceMatcher

conn = sqlite3.connect(Path(__file__).parent / "funding.db")

# Load all rows
rows = conn.execute("""
    SELECT id, company_name, round_type, amount_usd, announced_year, 
           source_name, source_url, confidence, investors_raw
    FROM funding_rounds
    ORDER BY confidence DESC
""").fetchall()

print(f"Scanning {len(rows)} rows for duplicates...")

def similar(a, b):
    if not a or not b: return 0
    a2 = a.lower().strip()
    b2 = b.lower().strip()
    return SequenceMatcher(None, a2, b2).ratio()

to_delete = set()
merged = 0

for i, r1 in enumerate(rows):
    if r1[0] in to_delete:
        continue
    id1, name1, rtype1, amt1, yr1, src1, url1, conf1, inv1 = r1

    for r2 in rows[i+1:]:
        if r2[0] in to_delete:
            continue
        id2, name2, rtype2, amt2, yr2, src2, url2, conf2, inv2 = r2

        # Same year, same round type
        if yr1 != yr2 or rtype1 != rtype2:
            continue
        # Similar company name
        if similar(name1, name2) < 0.88:
            continue
        # Similar or identical amount (within 10%)
        if amt1 and amt2:
            if abs(amt1 - amt2) / max(amt1, amt2) > 0.1:
                continue
        elif amt1 != amt2:  # one is None, other isn't
            continue

        # It's a duplicate — keep r1 (higher confidence), merge sources, delete r2
        merged_investors = inv1 or ""
        if inv2:
            for inv in inv2.split(","):
                inv = inv.strip()
                if inv and inv.lower() not in merged_investors.lower():
                    merged_investors = f"{merged_investors}, {inv}".strip(", ")

        conn.execute("""
            UPDATE funding_rounds 
            SET investors_raw = ?
            WHERE id = ?
        """, (merged_investors or None, id1))

        to_delete.add(id2)
        merged += 1

# Delete the duplicate rows
if to_delete:
    conn.executemany("DELETE FROM funding_rounds WHERE id=?", [(i,) for i in to_delete])

conn.commit()
remaining = conn.execute("SELECT COUNT(*) FROM funding_rounds").fetchone()[0]
conn.close()
print(f"Merged/removed {merged} duplicate rows")
print(f"Remaining rows: {remaining}")
