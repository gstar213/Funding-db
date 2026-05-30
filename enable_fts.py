"""
enable_fts.py — Create SQLite FTS5 index on funding_rounds for Datasette search.
Run once: python enable_fts.py
"""
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).parent / "funding.db")

print("Creating FTS5 index on funding_rounds...")
try:
    conn.executescript("""
        -- Drop old FTS if it exists
        DROP TABLE IF EXISTS funding_rounds_fts;

        -- Create FTS5 virtual table linked to funding_rounds
        CREATE VIRTUAL TABLE funding_rounds_fts USING fts5(
            company_name,
            headline,
            description,
            lead_investor,
            investors_raw,
            hq_country,
            sector,
            round_type,
            founder_name,
            content='funding_rounds',
            content_rowid='id'
        );

        -- Populate it
        INSERT INTO funding_rounds_fts(rowid, company_name, headline, description,
            lead_investor, investors_raw, hq_country, sector, round_type, founder_name)
        SELECT id, company_name, headline, description,
            lead_investor, investors_raw, hq_country, sector, round_type, founder_name
        FROM funding_rounds;

        -- Triggers to keep FTS in sync on insert/delete/update
        DROP TRIGGER IF EXISTS funding_rounds_ai;
        DROP TRIGGER IF EXISTS funding_rounds_ad;
        DROP TRIGGER IF EXISTS funding_rounds_au;

        CREATE TRIGGER funding_rounds_ai AFTER INSERT ON funding_rounds BEGIN
            INSERT INTO funding_rounds_fts(rowid, company_name, headline, description,
                lead_investor, investors_raw, hq_country, sector, round_type, founder_name)
            VALUES (new.id, new.company_name, new.headline, new.description,
                new.lead_investor, new.investors_raw, new.hq_country, new.sector,
                new.round_type, new.founder_name);
        END;

        CREATE TRIGGER funding_rounds_ad AFTER DELETE ON funding_rounds BEGIN
            INSERT INTO funding_rounds_fts(funding_rounds_fts, rowid, company_name, headline,
                description, lead_investor, investors_raw, hq_country, sector, round_type, founder_name)
            VALUES ('delete', old.id, old.company_name, old.headline, old.description,
                old.lead_investor, old.investors_raw, old.hq_country, old.sector,
                old.round_type, old.founder_name);
        END;

        CREATE TRIGGER funding_rounds_au AFTER UPDATE ON funding_rounds BEGIN
            INSERT INTO funding_rounds_fts(funding_rounds_fts, rowid, company_name, headline,
                description, lead_investor, investors_raw, hq_country, sector, round_type, founder_name)
            VALUES ('delete', old.id, old.company_name, old.headline, old.description,
                old.lead_investor, old.investors_raw, old.hq_country, old.sector,
                old.round_type, old.founder_name);
            INSERT INTO funding_rounds_fts(rowid, company_name, headline, description,
                lead_investor, investors_raw, hq_country, sector, round_type, founder_name)
            VALUES (new.id, new.company_name, new.headline, new.description,
                new.lead_investor, new.investors_raw, new.hq_country, new.sector,
                new.round_type, new.founder_name);
        END;
    """)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM funding_rounds_fts").fetchone()[0]
    print(f"[OK] FTS index created with {count} rows. Search is now fast.")
except Exception as e:
    print(f"[ERROR] {e}")
finally:
    conn.close()
