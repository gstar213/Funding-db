"""Add announced_year and announced_month columns and populate them."""
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).parent / "funding.db")

for col, typ in [("announced_year", "INTEGER"), ("announced_month", "TEXT")]:
    try:
        conn.execute(f"ALTER TABLE funding_rounds ADD COLUMN {col} {typ}")
        print(f"Added: {col}")
    except Exception:
        print(f"Already exists: {col}")

conn.commit()

# Populate from announced_date (format: YYYY-MM-DD)
updated = conn.execute("""
    UPDATE funding_rounds
    SET
        announced_year  = CAST(substr(announced_date, 1, 4) AS INTEGER),
        announced_month = CASE substr(announced_date, 6, 2)
            WHEN '01' THEN 'Jan' WHEN '02' THEN 'Feb' WHEN '03' THEN 'Mar'
            WHEN '04' THEN 'Apr' WHEN '05' THEN 'May' WHEN '06' THEN 'Jun'
            WHEN '07' THEN 'Jul' WHEN '08' THEN 'Aug' WHEN '09' THEN 'Sep'
            WHEN '10' THEN 'Oct' WHEN '11' THEN 'Nov' WHEN '12' THEN 'Dec'
            ELSE NULL END
    WHERE announced_date IS NOT NULL AND length(announced_date) >= 7
""").rowcount
conn.commit()
conn.close()
print(f"Populated year/month for {updated} rows.")
