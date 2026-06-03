"""
clean_portfolios_v3.py  — Nuclear clean pass
Uses a strict allowlist approach: a row is KEPT only if it passes ALL quality checks.
Then rewrites vc_portfolio_scraper.py to fix the root cause.

Run: python clean_portfolios_v3.py
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).parent / "funding.db"

# ── Words that appear ONLY in junk (never in real company names) ──────────────
HARD_JUNK_WORDS = re.compile(
    r"\b(home|about us|our team|knowledge hub|pitch to us|newsletter|subscribe|"
    r"filters?|exited|acquired by|investor relations|online trading|"
    r"entry stage|focus area|series [abcde]|saas|active|archives?|"
    r"leave a reply|cancel reply|comment\*?|email\*?|"
    r"discover more|editorial|economic shock|"
    r"by [a-z]|april \d|may \d|june \d|july \d|august \d|"
    r"co-investors?:|add another company|"
    r"all companies|all deep|fin-tech|deep-tech|consumer tech|"
    r"clear all|answers to your|"
    r"founder-first|founder club|join the|insights|"
    r"ape systems?|appomni|bangalore|"
    r"atlassian|companies\(\d|jobs\b|"
    r"perspective|360 one wealth|360 one asset)\b",
    re.I
)

# Regex patterns for specific junk types
JUNK_PATTERNS = [
    re.compile(r"^\d{4}$"),                                    # Year: "2016", "2026"
    re.compile(r"^\d+\s+(comment|reply)", re.I),              # "1 Comment"
    re.compile(r"^(april|may|june|july|august|september|october|november|december|january|february|march)\s+\d", re.I),  # Dates
    re.compile(r"^by\s+[a-z]", re.I),                        # "By John" / "ByAshutosh"
    re.compile(r"entry\s*stage|focus\s*area|series\s+[a-f]\b", re.I),  # Filter labels
    re.compile(r"active$|exited$", re.I),                      # Status labels
    re.compile(r"acquired\s+by|acquir[de]", re.I),             # Exit notes
    re.compile(r"\.{3,}|…"),                                   # Ellipsis
    re.compile(r"^\s*[-–—]\s*$"),                              # Dashes only
    re.compile(r"&\s*(amp|nbsp|lt|gt|quot);"),                 # HTML entities
    re.compile(r"[\u0080-\u00FF]{2,}"),                       # Garbled unicode
    re.compile(r"^\d+\s*(comment|companies|results|items)", re.I),
    re.compile(r"^(filters?|jobs?|active|exited|archives?|perspective)$", re.I),
    re.compile(r"co-investors?:\s*", re.I),                    # "Co-Investors: Micelio"
    re.compile(r"exited in \d{4}", re.I),
    re.compile(r"^(investor relations|online trading)$", re.I),
    re.compile(r"founder-first|straight to your inbox|join the", re.I),
    re.compile(r"(deep-tech|fin-tech|consumer tech).*(deep-tech|fin-tech)", re.I),  # repeated filter labels
    re.compile(r"\.(com|in|co|io|ai)\s*$"),                   # domain text without being a URL
    re.compile(r"^[A-Z][a-z]+\s+\d{1,2},\s+\d{4}$"),          # "April 15, 2026"
    re.compile(r"^\d+\s+\w+\s+\d{4}$"),                       # "15 April 2026"
    re.compile(r"leave a reply|cancel reply|comment\*|email\*", re.I),
    re.compile(r"^(all|active|exited|none|other|filters|jobs|search|sort|reset)$", re.I),
    re.compile(r"(entry stage|focus area|saasactive|saasfocus)", re.I),
]

# Regex for what a GOOD company name looks like:
# - 2-60 chars
# - Has at least one proper word (capital first letter + lowercase)
# - Can have numbers (Grab, 91Squarefeet, BharatX)
GOOD_COMPANY_RE = re.compile(r"^[A-Z\d]")  # Must start with capital or digit

# Maximum word count for a company name
MAX_WORDS = 6

# Minimum length
MIN_LEN = 3

# Common noise single words that are never company names
SINGLE_WORD_JUNK = {
    "all", "active", "exited", "jobs", "filters", "search", "reset", "more",
    "less", "next", "back", "perspective", "archives", "insights", "email",
    "comment", "none", "other", "portfolio", "bangalore", "funding",
    "deep-tech", "fin-tech", "saas", "agritech", "healthtech",
}


def is_good_company(name: str) -> bool:
    """Return True only if name passes all quality checks (allowlist approach)."""
    n = name.strip()

    # Basic length
    if len(n) < MIN_LEN or len(n) > 70:
        return False

    # Too many words
    words = n.split()
    if len(words) > MAX_WORDS:
        return False

    # Single-word blacklist
    if len(words) == 1 and n.lower() in SINGLE_WORD_JUNK:
        return False

    # Hard junk word matches
    if HARD_JUNK_WORDS.search(n):
        return False

    # Junk pattern matches
    for pat in JUNK_PATTERNS:
        if pat.search(n):
            return False

    # Must start with capital letter or digit
    if not GOOD_COMPANY_RE.match(n):
        return False

    # Must have at least one word that looks like a proper noun
    # (either starts with capital + has lowercase, OR is a digit-containing word)
    proper_words = [
        w for w in words
        if (len(w) >= 2 and w[0].isupper() and any(c.islower() for c in w))
        or re.match(r"^\d+[A-Za-z]", w)  # like "91Squarefeet"
        or (len(w) >= 3 and w.isupper() and w.isalpha())  # acronyms like "AGNIT"
    ]
    if not proper_words:
        return False

    # Reject if it's clearly a category/filter label (2 generic words)
    if len(words) <= 3:
        lower_words = [w.lower() for w in words]
        generic = {"tech", "technology", "capital", "ventures", "fund", "ai",
                   "healthcare", "consumer", "enterprise", "deep", "frontier",
                   "industry", "digital", "global", "saas", "fintech"}
        if all(w in generic or w in {"&", "and", "-"} for w in lower_words):
            return False

    return True


def main():
    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Rows before nuclear clean: {total}")

    rows = conn.execute("SELECT id, company_name FROM vc_portfolios").fetchall()

    keep_ids = []
    delete_ids = []
    for row_id, name in rows:
        if is_good_company(name):
            keep_ids.append(row_id)
        else:
            delete_ids.append(row_id)

    print(f"Rows to DELETE: {len(delete_ids)}")
    print(f"Rows to KEEP:   {len(keep_ids)}")

    if delete_ids:
        # Delete in chunks to avoid SQLite limits
        chunk = 500
        for i in range(0, len(delete_ids), chunk):
            ids_str = ",".join(str(x) for x in delete_ids[i:i+chunk])
            conn.execute(f"DELETE FROM vc_portfolios WHERE id IN ({ids_str})")
        conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Rows remaining: {remaining}")

    # Stats per VC
    print("\nVC company counts after cleaning:")
    vc_counts = conn.execute(
        "SELECT vc_name, COUNT(*) as cnt FROM vc_portfolios GROUP BY vc_name ORDER BY cnt DESC"
    ).fetchall()
    kept_vcs = [(v, c) for v, c in vc_counts if c >= 3]
    wiped_vcs = [(v, c) for v, c in vc_counts if c < 3]
    print(f"  VCs with 3+ companies: {len(kept_vcs)}")
    print(f"  VCs with <3 companies (likely junk): {len(wiped_vcs)}")

    # Wipe VCs with <3 companies left (not enough signal)
    if wiped_vcs:
        wipe_names = [v for v, c in wiped_vcs]
        placeholders = ",".join("?" for _ in wipe_names)
        conn.execute(f"DELETE FROM vc_portfolios WHERE vc_name IN ({placeholders})", wipe_names)
        conn.commit()
        print(f"  Wiped {len(wiped_vcs)} VCs with <3 companies")

    final = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Final row count: {final}")

    # Sample good data
    print("\nSample of clean data per VC:")
    vcs = conn.execute(
        "SELECT DISTINCT vc_name FROM vc_portfolios ORDER BY vc_name LIMIT 20"
    ).fetchall()
    for (vc,) in vcs:
        cnt = conn.execute("SELECT COUNT(*) FROM vc_portfolios WHERE vc_name=?", (vc,)).fetchone()[0]
        sample = conn.execute(
            "SELECT company_name, company_website FROM vc_portfolios WHERE vc_name=? LIMIT 4", (vc,)
        ).fetchall()
        print(f"\n  [{vc}] ({cnt} companies)")
        for s in sample:
            print(f"    {s[0]}  ->  {s[1]}")

    # Rebuild FTS
    print("\nRebuilding FTS index...")
    try:
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
        cnt = conn.execute("SELECT COUNT(*) FROM vc_portfolios_fts").fetchone()[0]
        print(f"[OK] FTS rebuilt: {cnt} rows indexed.")
    except Exception as e:
        print(f"[ERROR] {e}")

    conn.close()
    print("\nDone! Restart datasette to see changes.")


if __name__ == "__main__":
    main()
