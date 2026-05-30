"""
backfill.py — Historical funding data collection for 2022, 2023, 2024.
Uses Google News RSS with date-range operators: after:YYYY-MM-DD before:YYYY-MM-DD
"""
import sqlite3
import time
import re
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser

from extractor import (
    parse_amount, format_amount, parse_round_type, get_stage,
    parse_investors, parse_geography, classify_sector,
    parse_company, parse_domain, parse_founder, content_hash, compute_confidence,
)

logging.basicConfig(level=logging.WARNING)
DB_PATH = Path(__file__).parent / "funding.db"

GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

FUNDING_QUERIES = [
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

YEAR_RANGES = [
    ("2022-01-01", "2022-06-30"),
    ("2022-07-01", "2022-12-31"),
    ("2023-01-01", "2023-06-30"),
    ("2023-07-01", "2023-12-31"),
    ("2024-01-01", "2024-06-30"),
    ("2024-07-01", "2024-12-31"),
]

_FUNDING_KEYWORDS = re.compile(
    r"\b(?:raises?|raised|secures?|secured|closes?|closed|gets?|bags?|receives?|"
    r"lands?\s+funding|nets?\s+funding|"
    r"seed|series\s+[a-f]|funding\s+round|venture\s+capital|backed\s+by|"
    r"pre-seed|angel\s+round|ipo|acquisition)\b",
    re.I
)


def _is_funding_related(title: str, summary: str) -> bool:
    return bool(_FUNDING_KEYWORDS.search(f"{title} {summary}"))


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _save_round(conn, data: dict) -> bool:
    try:
        conn.execute("""
            INSERT INTO funding_rounds
                (company_name, company_domain, description,
                 hq_country, hq_city, region,
                 round_type, amount_usd, amount_display,
                 valuation_usd, lead_investor, investors_raw,
                 sector, sub_sector, stage,
                 source_name, source_url, headline, confidence,
                 announced_date, content_hash,
                 founder_name, founder_linkedin)
            VALUES
                (:company_name, :company_domain, :description,
                 :hq_country, :hq_city, :region,
                 :round_type, :amount_usd, :amount_display,
                 :valuation_usd, :lead_investor, :investors_raw,
                 :sector, :sub_sector, :stage,
                 :source_name, :source_url, :headline, :confidence,
                 :announced_date, :content_hash,
                 :founder_name, :founder_linkedin)
        """, data)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def collect_period(query: str, after: str, before: str, conn) -> tuple[int, int]:
    dated_query = f"{query} after:{after} before:{before}"
    url = GNEWS_BASE.format(query=dated_query.replace(" ", "+").replace(":", "%3A"))
    found = new = 0
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get("title", "") or ""
            summary = entry.get("summary", "") or ""
            link = entry.get("link", "") or ""
            summary_clean = re.sub(r"<[^>]+>", " ", summary)
            full_text = f"{title}. {summary_clean}"

            if not _is_funding_related(title, summary_clean):
                continue

            amount = parse_amount(full_text)
            round_type = parse_round_type(full_text)
            stage = get_stage(round_type)
            investors = parse_investors(full_text)
            lead_investor = investors[0] if investors else None
            country, city, region = parse_geography(full_text)
            sector, sub_sector = classify_sector(full_text)
            company = parse_company(title, summary_clean)
            domain = parse_domain(summary_clean, title)
            founder_name, founder_linkedin = parse_founder(full_text, company)

            if company == "Unknown":
                continue

            announced_date = None
            if entry.get("published_parsed"):
                try:
                    announced_date = datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
                except Exception:
                    pass
            elif entry.get("published"):
                try:
                    announced_date = parsedate_to_datetime(entry.published).strftime("%Y-%m-%d")
                except Exception:
                    pass

            # Force the date into the correct year range if feed date is missing
            if not announced_date:
                announced_date = after  # use start of range as fallback

            confidence = compute_confidence(amount, round_type, investors, "Google News", company != "Unknown")
            if confidence < 0.2:
                continue

            chash = content_hash(company, amount, announced_date)
            found += 1
            if _save_round(conn, {
                "company_name": company, "company_domain": domain,
                "description": summary_clean[:500],
                "hq_country": country, "hq_city": city, "region": region,
                "round_type": round_type, "amount_usd": amount,
                "amount_display": format_amount(amount) if amount else "Undisclosed",
                "valuation_usd": None, "lead_investor": lead_investor,
                "investors_raw": ", ".join(investors) if investors else None,
                "sector": sector, "sub_sector": sub_sector, "stage": stage,
                "source_name": "Google News (Historical)",
                "source_url": link, "headline": title[:500],
                "confidence": confidence, "announced_date": announced_date,
                "content_hash": chash,
                "founder_name": founder_name, "founder_linkedin": founder_linkedin,
            }):
                new += 1
    except Exception as e:
        print(f"  ERROR: {e}")
    return found, new


if __name__ == "__main__":
    conn = _get_conn()
    total_found = total_new = 0
    total_requests = len(YEAR_RANGES) * len(FUNDING_QUERIES)
    done = 0

    print(f"Historical backfill: {len(YEAR_RANGES)} periods x {len(FUNDING_QUERIES)} queries = {total_requests} requests")
    print("This will take ~5-8 minutes (rate-limited to respect Google News)\n")

    for after, before in YEAR_RANGES:
        period_new = 0
        print(f"[{after} to {before}]")
        for query in FUNDING_QUERIES:
            f, n = collect_period(query, after, before, conn)
            total_found += f
            total_new += n
            period_new += n
            done += 1
            print(f"  ({done}/{total_requests}) '{query[:45]}' -> {f} found, {n} new")
            time.sleep(1.0)  # respect rate limits
        print(f"  => Period total: {period_new} new rounds\n")

    conn.close()
    print(f"DONE! Total found: {total_found} | New saved: {total_new}")
