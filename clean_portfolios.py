"""
clean_portfolios.py
Cleans junk rows from vc_portfolios and adds FTS search.

Junk detection rules:
  1. portfolio_url == vc_website  → scraper fell back to homepage, not a real portfolio page
  2. company_name contains only uppercase words OR numbers OR typical nav/ui strings
  3. company_name is all-digits or very short (< 3 chars)
  4. company_name matches known noise patterns (fund stats, nav labels, etc.)
  5. company_name has no proper-noun pattern (no capital letter at start of a word)
  
Run: python clean_portfolios.py
"""
import sqlite3
import re
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).parent / "funding.db"

# ── Noise patterns ─────────────────────────────────────────────────────────────
NOISE_WORDS = {
    "portfolio", "companies", "startups", "investments", "home", "about",
    "team", "contact", "blog", "news", "press", "careers", "resources",
    "login", "signup", "get in touch", "learn more", "view all", "see all",
    "apply", "apply now", "our portfolio", "exit", "menu", "search", "filter",
    "all rights reserved", "privacy policy", "terms", "cookie", "cookies",
    "subscribe", "newsletter", "follow us", "linkedin", "twitter", "instagram",
    "facebook", "youtube", "medium", "read more", "load more", "show more",
    "back to top", "next", "previous", "page", "skip", "navigation",
    "fund i", "fund ii", "fund iii", "fund iv", "fund v",
    "number of funds", "start-ups reviewed", "investments", "aum",
    "illustrated", "unicorn",
}

# Regex patterns for junk
JUNK_PATTERNS = [
    re.compile(r"^\d+$"),                                    # Pure numbers: "100", "150"
    re.compile(r"^\d+[\w+]*$"),                              # Numbers with suffix: "14K+"
    re.compile(r"^[A-Z\s]+$"),                               # ALL CAPS only
    re.compile(r"^USD\d+", re.I),                            # Fund sizes: "USD100Mn"
    re.compile(r"\d+Mn|\d+Bn|\d+M\b|\d+B\b", re.I),        # Embedded fund amounts
    re.compile(r"©|@|http"),                                 # Copyright, URLs, emails
    re.compile(r"^[\W\s]+$"),                                # Only punctuation/whitespace
    re.compile(r"Contact\s+Us|Sign\s*[Uu]p|Log\s*[Ii]n|Privacy|Terms", re.I),
    re.compile(r"[A-Z]{2,}\s+[A-Z]{2,}\s+[A-Z]{2,}"),      # 3+ consecutive ALL-CAPS words
    re.compile(r"^(The\s+)?Transformation|Illustrated$", re.I),
    re.compile(r"Start-ups reviewed|Number of|Fund (I|II|III|IV|V)$", re.I),
    re.compile(r"Founders?Companies?Teams?Programs?", re.I),
    re.compile(r"UNSTOPPABLE|UNICORN\.", re.I),
]

def is_junk_company(name: str) -> bool:
    """Return True if this company_name is clearly scraped noise."""
    n = name.strip()
    
    # Too short or empty
    if len(n) < 3:
        return True
    
    # Too long (nav text concatenated)
    if len(n) > 80:
        return True
    
    # In noise words list
    if n.lower() in NOISE_WORDS:
        return True
    
    # Starts with lowercase (likely nav/UI text)
    if n and n[0].islower():
        return True
    
    # Matches junk regex patterns
    for pattern in JUNK_PATTERNS:
        if pattern.search(n):
            return True
    
    # Must have at least one word that looks like a proper noun
    # (capital letter followed by lowercase letters, length >= 2)
    words = n.split()
    has_proper_noun = any(
        len(w) >= 2 and w[0].isupper() and any(c.islower() for c in w[1:])
        for w in words
    )
    if not has_proper_noun:
        return True
    
    return False


def homepage_fallback(vc_website: str, portfolio_url: str) -> bool:
    """Return True if portfolio_url is just the homepage (no real portfolio path)."""
    if not vc_website or not portfolio_url:
        return False
    
    # Normalize: strip trailing slashes
    vc = vc_website.rstrip("/")
    pf = portfolio_url.rstrip("/")
    
    # Same URL = homepage fallback
    if vc == pf:
        return True
    
    # portfolio_url is vc_website with just a trailing slash or fragment
    pf_parsed = urlparse(pf)
    vc_parsed = urlparse(vc)
    if pf_parsed.netloc == vc_parsed.netloc and pf_parsed.path in ("", "/", "#"):
        return True
    
    return False


def main():
    conn = sqlite3.connect(DB_PATH)
    
    total = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Total rows before cleaning: {total}")
    
    # Fetch all rows
    rows = conn.execute(
        "SELECT id, vc_name, vc_website, portfolio_url, company_name FROM vc_portfolios"
    ).fetchall()
    
    junk_ids = []
    homepage_ids = []
    
    for row_id, vc_name, vc_website, portfolio_url, company_name in rows:
        if is_junk_company(company_name):
            junk_ids.append(row_id)
        elif homepage_fallback(vc_website, portfolio_url):
            # Homepage fallback rows are also junk — the whole VC's data is bad
            homepage_ids.append(row_id)
    
    print(f"Junk company names to delete: {len(junk_ids)}")
    print(f"Homepage-fallback rows to delete: {len(homepage_ids)}")
    
    # Identify VCs whose ENTIRE dataset is homepage fallback 
    # (we'll wipe their rows so re-scraping can fix them)
    homepage_fallback_vcs = set()
    for row_id, vc_name, vc_website, portfolio_url, company_name in rows:
        if homepage_fallback(vc_website, portfolio_url):
            homepage_fallback_vcs.add(vc_name)
    
    print(f"VCs with homepage-only data (will be wiped for re-scraping): {len(homepage_fallback_vcs)}")
    for v in sorted(homepage_fallback_vcs):
        print(f"  - {v}")
    
    # Delete junk rows
    all_delete = set(junk_ids) | set(homepage_ids)
    if all_delete:
        ids_str = ",".join(str(i) for i in all_delete)
        conn.execute(f"DELETE FROM vc_portfolios WHERE id IN ({ids_str})")
        conn.commit()
        print(f"\nDeleted {len(all_delete)} junk rows.")
    
    remaining = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Remaining rows: {remaining}")
    
    # Show sample of what's left
    print("\n=== Sample of KEPT rows ===")
    sample = conn.execute(
        "SELECT vc_name, company_name, company_website FROM vc_portfolios LIMIT 30"
    ).fetchall()
    for r in sample:
        print(f"  [{r[0]}] {r[1]} → {r[2]}")
    
    # ── Create FTS for vc_portfolios ─────────────────────────────────────────
    print("\nCreating FTS5 index on vc_portfolios...")
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
        print(f"[OK] FTS index created with {cnt} rows.")
    except Exception as e:
        print(f"[ERROR] FTS creation failed: {e}")
    
    conn.close()
    print("\nDone! Run: datasette funding.db -m datasette_metadata.json")


if __name__ == "__main__":
    main()
