"""
clean_portfolios_v2.py
More aggressive pass to remove remaining junk from vc_portfolios.

Run: python clean_portfolios_v2.py
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).parent / "funding.db"

# ── Nav / UI words that appear in concatenated scrapes ────────────────────────
NAV_WORDS = {
    "home", "about", "team", "portfolio", "contact", "blog", "news",
    "press", "careers", "resources", "login", "signup", "menu", "search",
    "filter", "updates", "pitch", "newsletter", "subscribe", "investors",
    "founders", "programs", "knowledge", "hub", "gallery", "events",
    "services", "solutions", "products", "platform", "overview", "mission",
    "vision", "values", "leadership", "people", "media", "faq", "support",
    "help", "docs", "documentation", "privacy", "terms", "cookies", "exit",
    "back", "next", "previous", "more", "less", "all", "none", "other",
}

# Generic single words that are NOT company names
SINGLE_WORD_BLACKLIST = {
    "all", "none", "other", "more", "less", "updates", "pitch", "portfolio",
    "consumer", "enterprise", "frontier", "industry", "technology", "tech",
    "capital", "ventures", "fund", "investments", "startups", "companies",
    "illustrated", "unicorn", "transformation", "innovation", "digital",
    "global", "india", "indian", "network", "group", "partners", "partners",
    "accelerator", "incubator", "ecosystem", "community", "mentors",
}

# Patterns for junk
JUNK_RE = [
    # Nav text concatenated (contains nav words separated by camelCase or spaces)
    re.compile(r"(Home|About|Team|Portfolio|Contact|Blog|News|Careers|Updates|Pitch|Newsletter|Subscribe|Login|Signup)", re.I),
    # Ends with punctuation typical of sentences (not abbreviations)
    re.compile(r"\.$"),
    # Pure numbers or numbers with suffixes
    re.compile(r"^\d[\d,.\s+KMBkmbcr%]*$", re.I),
    # Starts with USD/INR/Rs amounts
    re.compile(r"^(USD|INR|Rs\.?|\$)\s*[\d,]", re.I),
    # Copyright/social/legal
    re.compile(r"©|@|All Rights|Privacy|Terms|Cookie|Sign Up|Log In", re.I),
    # URLs
    re.compile(r"^https?://|^www\.", re.I),
    # Contains 3+ uppercase word-starts (CamelCase concatenation of multiple company names)
    # e.g. "AttrybGoldsetuAnahadApnamart"
    re.compile(r"([A-Z][a-z]+){4,}"),
    # Category labels ending with "Tech", "Capital", "Ventures" as standalone
    re.compile(r"^(Consumer|Enterprise|Frontier|Deep|Industry|B2B|B2C|SaaS|Fintech|Healthtech|Edtech)\s+(Tech|Technology|5\.0)$", re.I),
    # Thanks/notification messages
    re.compile(r"thank|joining|newsletter|subscri", re.I),
    # Very common UI labels
    re.compile(r"^(Our\s*Portfolio|Pitch\s*To\s*Us|Know\s*More|View\s*All|See\s*All|Read\s*More|Load\s*More|Get\s*In\s*Touch)$", re.I),
    # "Fund I", "Fund II" etc.
    re.compile(r"^Fund\s+(I{1,3}|IV|V|VI|VII|VIII|IX|X|\d+)$", re.I),
    # Contains "Number of" or "Start-ups reviewed"
    re.compile(r"Number of|Start-ups reviewed|Investments$|AUM", re.I),
    # All words are common nav/UI words
]


def count_nav_words(name: str) -> int:
    """Count how many nav-like words appear in the name."""
    words = re.findall(r"[a-zA-Z]+", name.lower())
    return sum(1 for w in words if w in NAV_WORDS)


def is_camelcase_concat(name: str) -> bool:
    """Detect concatenated company names like AttrybGoldsetuAnahadApnamart."""
    # Find all CamelCase word boundaries
    parts = re.findall(r"[A-Z][a-z0-9]+", name)
    # If the whole name is composed of 4+ CamelCase parts and no spaces → concat
    reconstructed = "".join(parts)
    if len(parts) >= 4 and reconstructed == name.replace(" ", ""):
        return True
    return False


def is_junk(name: str) -> bool:
    n = name.strip()

    # Empty / too short
    if len(n) < 3:
        return True

    # Too long — likely nav text concatenation
    if len(n) > 70:
        return True

    # Single word checks
    words = n.split()
    if len(words) == 1:
        lower = n.lower()
        if lower in SINGLE_WORD_BLACKLIST:
            return True
        # Pure number
        if re.match(r"^\d[\d+%,\.Kk]*$", n):
            return True

    # Too many nav words (concatenated navigation text)
    nav_count = count_nav_words(n)
    if nav_count >= 2:
        return True

    # CamelCase concatenation of multiple company names
    if is_camelcase_concat(n):
        return True

    # Junk regex patterns
    for pattern in JUNK_RE:
        if pattern.search(n):
            return True

    # No proper noun (capital letter + lowercase letters)
    has_proper_noun = any(
        len(w) >= 3 and w[0].isupper() and any(c.islower() for c in w[1:])
        for w in words
    )
    if not has_proper_noun:
        return True

    return False


def main():
    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Rows before this pass: {total}")

    rows = conn.execute(
        "SELECT id, company_name FROM vc_portfolios"
    ).fetchall()

    junk_ids = [row_id for row_id, name in rows if is_junk(name)]
    print(f"Additional junk rows found: {len(junk_ids)}")

    if junk_ids:
        ids_str = ",".join(str(i) for i in junk_ids)
        conn.execute(f"DELETE FROM vc_portfolios WHERE id IN ({ids_str})")
        conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    print(f"Rows after this pass: {remaining}")

    # Show some samples per VC
    print("\nSample rows per VC (first 5 each):")
    vcs = conn.execute(
        "SELECT DISTINCT vc_name FROM vc_portfolios ORDER BY vc_name LIMIT 20"
    ).fetchall()
    for (vc,) in vcs:
        sample = conn.execute(
            "SELECT company_name, company_website FROM vc_portfolios WHERE vc_name=? LIMIT 5",
            (vc,)
        ).fetchall()
        count = conn.execute(
            "SELECT COUNT(*) FROM vc_portfolios WHERE vc_name=?", (vc,)
        ).fetchone()[0]
        print(f"\n  [{vc}] ({count} companies)")
        for s in sample:
            print(f"    - {s[0]} | {s[1]}")

    # Rebuild FTS index after deletion
    print("\nRebuilding FTS index for vc_portfolios...")
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
        print(f"[OK] FTS rebuilt with {cnt} rows.")
    except Exception as e:
        print(f"[ERROR] FTS rebuild: {e}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
