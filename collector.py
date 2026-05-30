"""
collector.py — RSS + Google News collector for global funding rounds.

Sources (all free):
  • TechCrunch RSS          — global, high volume
  • VentureBeat RSS         — tech-focused
  • Sifted RSS              — European startups
  • YourStory RSS           — India-specific
  • e27 RSS                 — Southeast Asia
  • Forbes Startups RSS     — global
  • Crunchbase News RSS     — confirmed rounds
  • Business Insider RSS    — funding news
  • Google News RSS         — synthetic queries: "raised $X million"

Each article is parsed by extractor.py and saved to funding.db.
"""

import hashlib
import logging
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from extractor import (
    parse_amount, format_amount, parse_round_type, get_stage,
    parse_investors, parse_geography, classify_sector,
    parse_company, parse_domain, parse_founder, content_hash, compute_confidence,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "funding.db"

# ── Feed sources ──────────────────────────────────────────────────────────────

RSS_SOURCES = [
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "region_hint": None,
    },
    {
        "name": "VentureBeat",
        "url": "https://feeds.feedburner.com/venturebeat/SZYF",
        "region_hint": None,
    },
    {
        "name": "Sifted",
        "url": "https://sifted.eu/feed",
        "region_hint": "Europe",
    },
    {
        "name": "YourStory",
        "url": "https://yourstory.com/feed",
        "region_hint": "South Asia",
    },
    {
        "name": "Inc42",
        "url": "https://inc42.com/feed/",
        "region_hint": "South Asia",
    },
    {
        "name": "e27",
        "url": "https://e27.co/feed/",
        "region_hint": "Southeast Asia",
    },
    {
        "name": "Forbes Startups",
        "url": "https://www.forbes.com/startups/feed2/",
        "region_hint": None,
    },
    {
        "name": "Business Insider VC",
        "url": "https://feeds.businessinsider.com/custom/all",
        "region_hint": None,
    },
    {
        "name": "Crunchbase News",
        "url": "https://news.crunchbase.com/feed/",
        "region_hint": None,
    },
    {
        "name": "The Information",
        "url": "https://www.theinformation.com/feed",
        "region_hint": None,
    },
    {
        "name": "African Tech Startups (Disrupt Africa)",
        "url": "https://disrupt-africa.com/feed/",
        "region_hint": "Africa",
    },
    {
        "name": "Tech in Asia",
        "url": "https://www.techinasia.com/feed",
        "region_hint": "Southeast Asia",
    },
    {
        "name": "LatAm Startups (Contxto)",
        "url": "https://contxto.com/en/feed/",
        "region_hint": "Latin America",
    },
    {
        "name": "Hacker News",
        "url": "https://news.ycombinator.com/rss",
        "region_hint": None,
    },
    {
        "name": "Entrackr",
        "url": "https://entrackr.com/feed/",
        "region_hint": "South Asia",
    },
    {
        "name": "EU-Startups",
        "url": "https://www.eu-startups.com/feed/",
        "region_hint": "Europe",
    },
    {
        "name": "Deal Street Asia",
        "url": "https://www.dealstreetasia.com/feed/",
        "region_hint": "Southeast Asia",
    },
    {
        "name": "African Business",
        "url": "https://african.business/feed",
        "region_hint": "Africa",
    },
    {
        "name": "KrASIA",
        "url": "https://kr.asia/feed",
        "region_hint": "Southeast Asia",
    },
    {
        "name": "Startup Story",
        "url": "https://startupstory.co/feed/",
        "region_hint": "South Asia",
    },
]

# Google News RSS — queries that reliably surface funding news
GOOGLE_NEWS_QUERIES = [
    "startup raises million seed funding",
    "startup raises million series A",
    "startup raises million series B",
    "startup raises million series C",
    "startup secures funding round",
    "raises funding led by",
    "venture capital funding round 2025",
    "seed funding india startup",
    "series A india startup",
    "seed funding europe startup",
    "series A southeast asia",
    "YC W25 startup funding",
    "YC S25 startup funding",
    "Y Combinator funding 2025",
]

GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# ── Funding signal filter ─────────────────────────────────────────────────────

_FUNDING_KEYWORDS = re.compile(
    r"\b(?:raises?|raised|secures?|secured|closes?|closed|gets?|bags?|receives?|"
    r"lands?\s+funding|nets?\s+funding|bags?\s+funding|"
    r"seed|series\s+[a-f]|funding\s+round|venture\s+capital|backed\s+by|"
    r"pre-seed|angel\s+round|ipo|acquisition|acqui[- ]hire)\b",
    re.I
)

def _is_funding_related(title: str, summary: str) -> bool:
    """Quick check: does this article mention funding?"""
    combined = f"{title} {summary}"
    return bool(_FUNDING_KEYWORDS.search(combined))


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _save_round(conn: sqlite3.Connection, data: dict) -> bool:
    """Insert a funding round. Returns True if new, False if duplicate."""
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
        # Duplicate hash
        return False


def _start_run(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO collection_runs (source) VALUES (?)", (source,)
    )
    conn.commit()
    return cur.lastrowid


def _finish_run(conn: sqlite3.Connection, run_id: int, found: int, new: int,
                status: str = "ok", error: str = None):
    conn.execute("""
        UPDATE collection_runs
        SET finished_at=datetime('now'), found=?, new=?, status=?, error=?
        WHERE id=?
    """, (found, new, status, error, run_id))
    conn.commit()


# ── Article → FundingRound ────────────────────────────────────────────────────

def _parse_entry(entry: feedparser.FeedParserDict,
                 source_name: str,
                 region_hint: Optional[str] = None) -> Optional[dict]:
    """Convert a feedparser entry to a funding round dict, or None if not funding."""
    title = entry.get("title", "") or ""
    summary = entry.get("summary", "") or ""
    link = entry.get("link", "") or ""

    # Strip HTML from summary
    summary_clean = re.sub(r"<[^>]+>", " ", summary)
    full_text = f"{title}. {summary_clean}"

    if not _is_funding_related(title, summary_clean):
        return None

    # Extract all fields
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

    # Use region_hint if we couldn't detect
    if not region and region_hint:
        region = region_hint

    # Announced date from feed
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

    confidence = compute_confidence(amount, round_type, investors, source_name, company != "Unknown")

    # Skip very low confidence entries (likely not real funding news)
    if confidence < 0.2:
        return None

    chash = content_hash(company, amount, announced_date)

    return {
        "company_name": company,
        "company_domain": domain,
        "description": summary_clean[:500] if summary_clean else None,
        "hq_country": country,
        "hq_city": city,
        "region": region,
        "round_type": round_type,
        "amount_usd": amount,
        "amount_display": format_amount(amount) if amount else "Undisclosed",
        "valuation_usd": None,
        "lead_investor": lead_investor,
        "investors_raw": ", ".join(investors) if investors else None,
        "sector": sector,
        "sub_sector": sub_sector,
        "stage": stage,
        "source_name": source_name,
        "source_url": link,
        "headline": title[:500],
        "confidence": confidence,
        "announced_date": announced_date,
        "content_hash": chash,
        "founder_name": founder_name,
        "founder_linkedin": founder_linkedin,
    }


# ── Collector functions ───────────────────────────────────────────────────────

def collect_rss(source: dict, conn: sqlite3.Connection) -> tuple[int, int]:
    """Collect one RSS source. Returns (found, new)."""
    run_id = _start_run(conn, source["name"])
    found = new = 0
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries:
            data = _parse_entry(entry, source["name"], source.get("region_hint"))
            if data:
                found += 1
                if _save_round(conn, data):
                    new += 1
        _finish_run(conn, run_id, found, new)
    except Exception as e:
        logger.error(f"[{source['name']}] failed: {e}")
        _finish_run(conn, run_id, found, new, status="error", error=str(e))
    return found, new


def collect_google_news(conn: sqlite3.Connection) -> tuple[int, int]:
    """Collect Google News RSS for all funding queries."""
    total_found = total_new = 0
    for query in GOOGLE_NEWS_QUERIES:
        url = GNEWS_BASE.format(query=httpx.URL(query).__str__().replace("/", "%2F"))
        # feedparser handles URL encoding
        url = GNEWS_BASE.format(query=query.replace(" ", "+").replace("&", "%26"))
        run_id = _start_run(conn, f"Google News: {query[:40]}")
        found = new = 0
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                data = _parse_entry(entry, "Google News", None)
                if data:
                    found += 1
                    if _save_round(conn, data):
                        new += 1
            _finish_run(conn, run_id, found, new)
            total_found += found
            total_new += new
        except Exception as e:
            logger.error(f"[Google News: {query}] failed: {e}")
            _finish_run(conn, run_id, found, new, status="error", error=str(e))
        time.sleep(0.5)   # gentle rate limit
    return total_found, total_new


def run_collection(verbose: bool = True) -> dict:
    """Run a full collection cycle across all sources."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    console = Console()

    conn = _get_conn()
    total_found = total_new = 0

    all_sources = RSS_SOURCES + [{"name": "Google News (funding queries)", "url": None, "is_gnews": True}]

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=20),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Collecting...", total=len(all_sources))

        for source in all_sources:
            progress.update(task, description=f"[bold cyan]{source['name']}")
            if source.get("is_gnews"):
                f, n = collect_google_news(conn)
            else:
                f, n = collect_rss(source, conn)
            total_found += f
            total_new += n
            if verbose and n > 0:
                console.print(f"  ✓ [green]{source['name']}[/green] — {n} new rounds")
            elif verbose:
                console.print(f"  · [dim]{source['name']}[/dim] — {f} found, 0 new")
            progress.advance(task)

    conn.close()
    return {"total_found": total_found, "total_new": total_new}
