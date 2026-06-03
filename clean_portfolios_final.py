"""
clean_portfolios_final.py
Final targeted cleanup of known-bad VCs + remaining edge cases.
Run: python clean_portfolios_final.py
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).parent / "funding.db"
conn = sqlite3.connect(DB_PATH)

# ── VCs whose data is entirely garbage (scraper hit wrong page) ───────────────
# These will be fully wiped so the scraper can retry them properly
WIPE_VCS = [
    "Accel India",          # Scraping Accel's homepage/legal, not portfolio
    "Alkemi Growth Capital", # Scraping blog/google forms, not portfolio
    "Alter Global",         # Scraping a news/policy site, totally wrong VC
    "Anicut capital",       # Scraping crunchbase-like SaaS, not portfolio
    "Ankur Capital",        # Scraping filter labels
    "Arkam Ventures",       # Only 4 junk rows
    "Atrium Angels",        # Scraping a shared blog (Auto Plunge blog?)
    "Audacity VC",          # Scraping blog comments form
    "Avataar Ventures",     # Scraping wrong site (shared blog)
    "BYT Capital",          # Only "Life Sciences" filter label
]

# ── Additional per-row cleanup patterns (for VCs with mixed data) ─────────────
BAD_COMPANY_PATTERNS = [
    re.compile(r"^(legal|privacy|zepz-logo|accel)$", re.I),
    re.compile(r"\d{3,}\s*(companies|results|items)", re.I),  # "Companies(758)"
    re.compile(r"^(advanced materials|agritech|biotech|healthcare|climate|others?)$", re.I),
    re.compile(r"All Companies", re.I),
    re.compile(r"competitive data|discover companies|create free account|funding.*known", re.I),
    re.compile(r"^(geographic reference|geopolitics|government policy)", re.I),
    re.compile(r"^(name\*|email\*|next post|previous post|recent posts)$", re.I),
    re.compile(r"ByAshutosh|ByAuto Plunge|July \d|June \d", re.I),
    re.compile(r"See Details|Start a Conversation|One-in-a-Million|Skyroot becomes", re.I),
    re.compile(r"^(Join Us|Get Featured|Company|Industries|Life Sciences)$", re.I),
    re.compile(r"agritech.*food|All Companies.*Agritech", re.I),
    re.compile(r"^(Checkbox 8|Clear All)$", re.I),  # UI filter elements
    re.compile(r"^Companies\(\d+\)$"),               # "Companies(758)"
    re.compile(r"^Agritech & Food$"),                # Pure category label
]


def row_is_bad(name):
    for pat in BAD_COMPANY_PATTERNS:
        if pat.search(name):
            return True
    return False


# Step 1: Wipe the fully-bad VCs
total_before = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
print(f"Rows before: {total_before}")

for vc in WIPE_VCS:
    deleted = conn.execute(
        "DELETE FROM vc_portfolios WHERE vc_name = ?", (vc,)
    ).rowcount
    if deleted:
        print(f"  Wiped {deleted} rows for: {vc}")

conn.commit()

# Step 2: Per-row cleanup of bad entries in otherwise-good VCs
rows = conn.execute("SELECT id, company_name FROM vc_portfolios").fetchall()
bad_ids = [rid for rid, name in rows if row_is_bad(name)]
print(f"\nAdditional bad rows to remove: {len(bad_ids)}")
if bad_ids:
    chunk = 500
    for i in range(0, len(bad_ids), chunk):
        ids_str = ",".join(str(x) for x in bad_ids[i:i+chunk])
        conn.execute(f"DELETE FROM vc_portfolios WHERE id IN ({ids_str})")
    conn.commit()

total_after = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
print(f"Rows after:  {total_after}")

# Step 3: Stats
vc_counts = conn.execute(
    "SELECT vc_name, COUNT(*) as cnt FROM vc_portfolios GROUP BY vc_name ORDER BY cnt DESC"
).fetchall()
print(f"\nVCs remaining: {len(vc_counts)}")
print(f"Top VCs by portfolio size:")
for vc, cnt in vc_counts[:15]:
    print(f"  {vc}: {cnt} companies")

# Step 4: Rebuild FTS
print("\nRebuilding FTS index...")
conn.executescript("""
    DROP TABLE IF EXISTS vc_portfolios_fts;
    CREATE VIRTUAL TABLE vc_portfolios_fts USING fts5(
        vc_name, company_name, company_website, vc_website,
        content='vc_portfolios', content_rowid='id'
    );
    INSERT INTO vc_portfolios_fts(rowid, vc_name, company_name, company_website, vc_website)
    SELECT id, vc_name, company_name, company_website, vc_website FROM vc_portfolios;

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
fts_cnt = conn.execute("SELECT COUNT(*) FROM vc_portfolios_fts").fetchone()[0]
print(f"[OK] FTS index: {fts_cnt} rows")

conn.close()
print("\nAll done. Restart datasette to see clean data.")
