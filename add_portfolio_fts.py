"""
add_portfolio_fts.py
Creates FTS5 search index on vc_portfolios (and indian_vcs if present).
Run: python add_portfolio_fts.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "funding.db"
conn = sqlite3.connect(DB_PATH)

print("Creating FTS5 index on vc_portfolios...")
try:
    conn.executescript("""
        DROP TABLE IF EXISTS vc_portfolios_fts;

        CREATE VIRTUAL TABLE vc_portfolios_fts USING fts5(
            vc_name,
            company_name,
            company_website,
            vc_website,
            content='vc_portfolios',
            content_rowid='id'
        );

        INSERT INTO vc_portfolios_fts(rowid, vc_name, company_name, company_website, vc_website)
        SELECT id, vc_name, company_name, company_website, vc_website
        FROM vc_portfolios;

        DROP TRIGGER IF EXISTS vc_portfolios_ai;
        DROP TRIGGER IF EXISTS vc_portfolios_ad;
        DROP TRIGGER IF EXISTS vc_portfolios_au;

        CREATE TRIGGER vc_portfolios_ai AFTER INSERT ON vc_portfolios BEGIN
            INSERT INTO vc_portfolios_fts(rowid, vc_name, company_name, company_website, vc_website)
            VALUES (new.id, new.vc_name, new.company_name, new.company_website, new.vc_website);
        END;

        CREATE TRIGGER vc_portfolios_ad AFTER DELETE ON vc_portfolios BEGIN
            INSERT INTO vc_portfolios_fts(vc_portfolios_fts, rowid, vc_name, company_name, company_website, vc_website)
            VALUES ('delete', old.id, old.vc_name, old.company_name, old.company_website, old.vc_website);
        END;

        CREATE TRIGGER vc_portfolios_au AFTER UPDATE ON vc_portfolios BEGIN
            INSERT INTO vc_portfolios_fts(vc_portfolios_fts, rowid, vc_name, company_name, company_website, vc_website)
            VALUES ('delete', old.id, old.vc_name, old.company_name, old.company_website, old.vc_website);
            INSERT INTO vc_portfolios_fts(rowid, vc_name, company_name, company_website, vc_website)
            VALUES (new.id, new.vc_name, new.company_name, new.company_website, new.vc_website);
        END;
    """)
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM vc_portfolios_fts").fetchone()[0]
    print(f"[OK] vc_portfolios FTS index created with {cnt} rows.")
except Exception as e:
    print(f"[ERROR] vc_portfolios FTS: {e}")

# Also add FTS for indian_vcs if it has searchable columns
print("Checking indian_vcs columns...")
try:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(indian_vcs)").fetchall()]
    print(f"  Columns: {cols}")
    
    text_cols = [c for c in cols if c not in ('id', 'rowid')]
    if text_cols:
        fts_cols = ", ".join(text_cols[:5])  # max 5 columns
        conn.executescript(f"""
            DROP TABLE IF EXISTS indian_vcs_fts;
            CREATE VIRTUAL TABLE indian_vcs_fts USING fts5(
                {fts_cols},
                content='indian_vcs',
                content_rowid='id'
            );
            INSERT INTO indian_vcs_fts(rowid, {fts_cols})
            SELECT id, {fts_cols} FROM indian_vcs;
        """)
        conn.commit()
        cnt2 = conn.execute("SELECT COUNT(*) FROM indian_vcs_fts").fetchone()[0]
        print(f"[OK] indian_vcs FTS index created with {cnt2} rows.")
except Exception as e:
    print(f"[NOTE] indian_vcs FTS skipped: {e}")

# Show sample of clean portfolio data
print("\nSample of clean vc_portfolios rows:")
rows = conn.execute(
    "SELECT vc_name, company_name, company_website FROM vc_portfolios LIMIT 25"
).fetchall()
for r in rows:
    print(f"  {r[0]} | {r[1]} | {r[2]}")

print("\nAll done.")
conn.close()
