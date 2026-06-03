import sqlite3
conn = sqlite3.connect('funding.db')

print("=== Table counts ===")
tables_fts = {
    'funding_rounds': 'funding_rounds_fts',
    'vc_portfolios': 'vc_portfolios_fts',
    'indian_vcs': 'indian_vcs_fts',
    'vc_enrichments': None,
    'collection_runs': None,
}
for t, fts in tables_fts.items():
    cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    fts_info = ""
    if fts:
        try:
            fc = conn.execute(f"SELECT COUNT(*) FROM [{fts}]").fetchone()[0]
            fts_info = f" (FTS: {fc})"
        except Exception as e:
            fts_info = f" (FTS: MISSING - {e})"
    print(f"  {t}: {cnt} rows{fts_info}")

print()
print("=== vc_portfolios: VCs with clean data ===")
vcs = conn.execute(
    "SELECT vc_name, COUNT(*) as cnt FROM vc_portfolios GROUP BY vc_name ORDER BY cnt DESC"
).fetchall()
print(f"  Total VCs: {len(vcs)}")
print(f"  Total portfolio company rows: {sum(c for _, c in vcs)}")
print()
print("  Top 20 VCs by portfolio size:")
for vc, cnt in vcs[:20]:
    print(f"    {vc}: {cnt}")

print()
print("=== Sample clean rows from Alteria Capital ===")
rows = conn.execute(
    "SELECT company_name, company_website FROM vc_portfolios WHERE vc_name='Alteria Capital' LIMIT 10"
).fetchall()
for r in rows:
    print(f"  {r[0]}  ->  {r[1]}")

print()
print("=== FTS search test: 'Zepto' ===")
try:
    r = conn.execute(
        "SELECT vc_name, company_name FROM vc_portfolios_fts WHERE vc_portfolios_fts MATCH 'Zepto' LIMIT 5"
    ).fetchall()
    print(f"  Results: {r}")
except Exception as e:
    print(f"  Error: {e}")

print()
print("=== FTS search test on funding_rounds: 'Zepto' ===")
try:
    r = conn.execute(
        "SELECT company_name, round_type, amount_display FROM funding_rounds WHERE rowid IN (SELECT rowid FROM funding_rounds_fts WHERE funding_rounds_fts MATCH 'Zepto') LIMIT 5"
    ).fetchall()
    print(f"  Results: {r}")
except Exception as e:
    print(f"  Error: {e}")

conn.close()
print("\nDone.")
