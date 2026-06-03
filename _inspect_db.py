import sqlite3
conn = sqlite3.connect('funding.db')

print('=== All tables ===')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    cnt = conn.execute(f'SELECT COUNT(*) FROM [{t[0]}]').fetchone()[0]
    print(f'  {t[0]}: {cnt} rows')

print()
print('=== vc_portfolios sample (first 20) ===')
rows = conn.execute('SELECT vc_name, vc_website, portfolio_url, company_name, company_website FROM vc_portfolios LIMIT 20').fetchall()
for r in rows:
    print(r)

print()
print('=== Distinct VCs in portfolio ===')
vcs = conn.execute('SELECT vc_name, COUNT(*) as cnt FROM vc_portfolios GROUP BY vc_name ORDER BY cnt DESC LIMIT 20').fetchall()
for v in vcs:
    print(v)

print()
print('=== portfolio_url vs vc_website comparison ===')
rows = conn.execute('SELECT vc_website, portfolio_url, COUNT(*) FROM vc_portfolios GROUP BY portfolio_url LIMIT 20').fetchall()
for r in rows:
    print(r)

print()
print('=== vc_portfolios FTS? ===')
fts = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'").fetchall()
print(fts)

conn.close()
