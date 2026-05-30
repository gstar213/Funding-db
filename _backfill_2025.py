"""Backfill 2025 + early 2026 and rebuild FTS index."""
import sqlite3, re, time, logging
from datetime import datetime
from pathlib import Path
from email.utils import parsedate_to_datetime
import feedparser
from extractor import (
    parse_amount, format_amount, parse_round_type, get_stage,
    parse_investors, parse_geography, classify_sector,
    parse_company, parse_domain, parse_founder, content_hash, compute_confidence,
)

logging.basicConfig(level=logging.WARNING)
DB_PATH = Path(__file__).parent / "funding.db"
GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

QUERIES = [
    "startup raises million seed funding",
    "startup raises million series A",
    "startup raises million series B",
    "startup raises million series C",
    "startup secures funding round",
    "raises funding led by venture capital",
    "seed funding startup raised",
    "series A funding raised",
    "seed funding india startup",
    "series A india startup raised",
    "seed funding europe startup raised",
    "series A europe startup",
    "series A southeast asia startup",
    "seed funding africa startup",
    "series A latin america startup",
    "YC startup funding raised",
    "Y Combinator startup funding",
    "startup funding round announced",
]

PERIODS = [
    ("2025-01-01", "2025-06-30"),
    ("2025-07-01", "2025-12-31"),
    ("2026-01-01", "2026-05-30"),
]

_FUNDING_KW = re.compile(
    r"\b(?:raises?|raised|secures?|secured|closes?|closed|gets?|bags?|receives?|"
    r"lands?\s+funding|seed|series\s+[a-f]|funding\s+round|venture\s+capital|backed\s+by|pre-seed|angel\s+round|ipo)\b", re.I
)

def _save(conn, data):
    try:
        conn.execute("""
            INSERT INTO funding_rounds
                (company_name, company_domain, description, hq_country, hq_city, region,
                 round_type, amount_usd, amount_display, valuation_usd, lead_investor,
                 investors_raw, sector, sub_sector, stage, source_name, source_url,
                 headline, confidence, announced_date, content_hash,
                 founder_name, founder_linkedin, announced_year, announced_month)
            VALUES
                (:company_name, :company_domain, :description, :hq_country, :hq_city, :region,
                 :round_type, :amount_usd, :amount_display, :valuation_usd, :lead_investor,
                 :investors_raw, :sector, :sub_sector, :stage, :source_name, :source_url,
                 :headline, :confidence, :announced_date, :content_hash,
                 :founder_name, :founder_linkedin, :announced_year, :announced_month)
        """, data)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

MONTH_MAP = {'01':'Jan','02':'Feb','03':'Mar','04':'Apr','05':'May','06':'Jun',
             '07':'Jul','08':'Aug','09':'Sep','10':'Oct','11':'Nov','12':'Dec'}

conn = sqlite3.connect(DB_PATH)
total_new = 0
done = 0
total = len(PERIODS) * len(QUERIES)

for after, before in PERIODS:
    period_new = 0
    print(f"\n[{after} → {before}]")
    for q in QUERIES:
        done += 1
        url = GNEWS_BASE.format(query=f"{q} after:{after} before:{before}".replace(" ", "+").replace(":", "%3A"))
        found = new = 0
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "") or ""
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "")
                link = entry.get("link", "") or ""
                full = f"{title}. {summary}"
                if not _FUNDING_KW.search(full): continue
                amount = parse_amount(full)
                rt = parse_round_type(full)
                investors = parse_investors(full)
                country, city, region = parse_geography(full)
                sector, sub = classify_sector(full)
                company = parse_company(title, summary)
                if company == "Unknown": continue
                domain = parse_domain(summary, title)
                fname, flink = parse_founder(full, company)
                conf = compute_confidence(amount, rt, investors, "Google News", True)
                if conf < 0.2: continue
                dt = None
                if entry.get("published_parsed"):
                    try: dt = datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
                    except: pass
                if not dt: dt = after
                yr = int(dt[:4]) if dt else None
                mo = MONTH_MAP.get(dt[5:7]) if dt and len(dt) >= 7 else None
                chash = content_hash(company, amount, dt)
                found += 1
                if _save(conn, {
                    "company_name": company, "company_domain": domain,
                    "description": summary[:500], "hq_country": country,
                    "hq_city": city, "region": region, "round_type": rt,
                    "amount_usd": amount, "amount_display": format_amount(amount) if amount else "Undisclosed",
                    "valuation_usd": None, "lead_investor": investors[0] if investors else None,
                    "investors_raw": ", ".join(investors) if investors else None,
                    "sector": sector, "sub_sector": sub, "stage": get_stage(rt),
                    "source_name": "Google News (Historical)", "source_url": link,
                    "headline": title[:500], "confidence": conf, "announced_date": dt,
                    "content_hash": chash, "founder_name": fname, "founder_linkedin": flink,
                    "announced_year": yr, "announced_month": mo,
                }):
                    new += 1
        except Exception as e:
            print(f"  ERROR: {e}")
        total_new += new
        period_new += new
        print(f"  ({done}/{total}) {q[:45]!r} -> {found} found, {new} new")
        time.sleep(1.0)
    print(f"  => {period_new} new rounds this period")

# Rebuild FTS with all new rows
print("\nRebuilding FTS index...")
conn.executescript("""
    DROP TABLE IF EXISTS funding_rounds_fts;
    CREATE VIRTUAL TABLE funding_rounds_fts USING fts5(
        company_name, headline, description, lead_investor, investors_raw,
        hq_country, sector, round_type, founder_name,
        content='funding_rounds', content_rowid='id'
    );
    INSERT INTO funding_rounds_fts(rowid, company_name, headline, description,
        lead_investor, investors_raw, hq_country, sector, round_type, founder_name)
    SELECT id, company_name, headline, description,
        lead_investor, investors_raw, hq_country, sector, round_type, founder_name
    FROM funding_rounds;
""")
conn.commit()

total_all = conn.execute("SELECT COUNT(*) FROM funding_rounds").fetchone()[0]
conn.close()
print(f"\nDone! New rows added: {total_new}")
print(f"Total in DB: {total_all}")
