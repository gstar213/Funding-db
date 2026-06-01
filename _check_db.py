import sqlite3, os

db_files = [f for f in os.listdir('.') if f.endswith('.db') or f.endswith('.sqlite')]
print('DB files found:', db_files)

for db in db_files:
    print(f'\n=== {db} ===')
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print('Tables:', tables)
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cur.fetchone()[0]
        print(f'  {t}: {count} rows')

    # Sample from vc_portfolios if exists
    if 'vc_portfolios' in tables:
        cur.execute("SELECT * FROM vc_portfolios LIMIT 5")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        print(f'\n  vc_portfolios sample columns: {cols}')
        for r in rows:
            print(' ', r)

    # Sample from indian_vcs if exists
    if 'indian_vcs' in tables:
        cur.execute("SELECT COUNT(*) FROM indian_vcs WHERE website IS NOT NULL AND website != ''")
        print(f'  indian_vcs with website: {cur.fetchone()[0]}')

    conn.close()
