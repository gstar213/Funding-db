"""
vc_portfolio_scraper.py
Phase 1: Find each VC's website via DuckDuckGo
Phase 2: Scrape their portfolio page with Playwright
Phase 3: Save to vc_portfolios table + match against funding_rounds

Run: python vc_portfolio_scraper.py
"""
import sqlite3
import re
import time
import json
import logging
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from ddgs import DDGS

logging.basicConfig(level=logging.WARNING)
DB_PATH = Path(__file__).parent / "funding.db"

# ── Schema ────────────────────────────────────────────────────────────────────
CREATE_PORTFOLIOS = """
CREATE TABLE IF NOT EXISTS vc_portfolios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vc_name         TEXT NOT NULL,
    vc_website      TEXT,
    portfolio_url   TEXT,
    company_name    TEXT NOT NULL,
    company_website TEXT,
    scraped_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(vc_name, company_name)
);
"""

CREATE_VC_ENRICHMENTS = """
CREATE TABLE IF NOT EXISTS vc_enrichments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    funding_round_id    INTEGER REFERENCES funding_rounds(id),
    vc_name             TEXT,
    match_score         REAL,
    source              TEXT DEFAULT 'vc_portfolio',
    enriched_at         TEXT DEFAULT (datetime('now'))
);
"""

# ── Common portfolio page paths to try ────────────────────────────────────────
PORTFOLIO_PATHS = [
    "/portfolio", "/companies", "/investments", "/our-portfolio",
    "/portfolio-companies", "/startups", "/our-companies", "/invested-companies",
    "/our-investments", "/portfolio/", "/companies/", "/investments/",
]

# ── Noise company names to skip ───────────────────────────────────────────────
COMPANY_NOISE = {
    "portfolio", "companies", "startups", "investments", "home", "about",
    "team", "contact", "blog", "news", "press", "careers", "resources",
    "login", "signup", "get in touch", "learn more", "view all", "see all",
    "apply", "apply now", "our portfolio", "exit", "menu", "search",
    "all", "none", "other", "filters", "sort", "reset", "load more",
    "show more", "read more", "next", "previous", "back", "subscribe",
    "newsletter", "privacy policy", "terms of service", "cookie policy",
    "follow us", "get in touch", "pitch to us", "know more", "discover more",
    "legal", "sitemap", "faq", "help", "support", "docs", "documentation",
    "founder club", "join the", "insights", "updates", "pitch", "overview",
    "mission", "vision", "values", "leadership", "people", "media",
    "fund i", "fund ii", "fund iii", "fund iv", "fund v",
    "agritech", "healthtech", "saas", "fintech", "edtech", "deeptech",
    "consumer tech", "enterprise tech", "frontier", "advanced materials",
    "biotech", "climate", "healthcare", "deep-tech", "fin-tech",
    "active", "exited", "seed", "growth", "early stage", "late stage",
    "by stage", "by sector", "name*", "email*", "website", "message",
    "recent posts", "previous post", "next post", "leave a reply",
    "cancel reply", "comment*", "archives", "categories", "tags",
}

# Regex for junk detection during scraping
import re as _re
_SCRAPE_JUNK_RE = _re.compile(
    r"(Home|About\s*[Uu]s|Our\s*Team|Knowledge\s*Hub|Pitch\s*[Tt]o\s*Us|"
    r"newsletter|subscribe|investor\s*relations|online\s*trading|"
    r"entry\s*stage|focus\s*area|by\s+[A-Z]\w+|"
    r"^\d{4}$|April\s+\d|May\s+\d|June\s+\d|July\s+\d|"
    r"leave\s+a\s+reply|cancel\s+reply|acquired\s+by|"
    r"exited\s+in\s+\d{4}|co-investors?:|add\s+another\s+company|"
    r"create\s+free\s+account|discover\s+companies|competitive\s+data|"
    r"Companies\(\d+\)|see\s+details|start\s+a\s+conversation|"
    r"founder-first|straight\s+to\s+your\s+inbox|"
    r"get\s+featured|industries|life\s+sciences$|geographic\s+reference|"
    r"geopolitics\s+essays|government\s+policy|editorial\s+writing)",
    _re.I
)


# ── Extract company names from a portfolio page ───────────────────────────────
def extract_companies_from_html(html: str, base_url: str) -> list[dict]:
    """Parse portfolio page HTML and extract company name + website.
    
    Uses a targeted approach:
    1. Strip all non-content elements (nav, footer, forms, scripts)
    2. Look for a portfolio-specific section first
    3. Fall back to scanning external links only if no section found
    4. Apply strict company-name validation
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── Step 1: Remove noise elements ────────────────────────────────────────
    for tag in soup.find_all(["nav", "footer", "header", "form", "script",
                               "style", "aside", "noscript", "iframe"]):
        tag.decompose()

    # Remove common sidebar/cookie/newsletter divs by class/id patterns
    _noise_classes = re.compile(
        r"(nav|footer|header|sidebar|cookie|banner|newsletter|subscribe|"
        r"social|share|comment|search|breadcrumb|pagination|widget|"
        r"menu|toolbar|modal|overlay|popup|toast|notification)", re.I
    )
    for tag in soup.find_all(True, {"class": _noise_classes}):
        tag.decompose()
    for tag in soup.find_all(True, {"id": _noise_classes}):
        tag.decompose()

    # ── Step 2: Find portfolio section ────────────────────────────────────────
    _portfolio_patterns = re.compile(
        r"(portfolio|companies|startups|investments|our.companies|"
        r"invested|founders|ecosystem|cohort|batch)", re.I
    )
    portfolio_section = None
    for tag in soup.find_all(True, {"class": _portfolio_patterns}):
        # Must be a substantial section (not a single link)
        if len(tag.get_text(strip=True)) > 100:
            portfolio_section = tag
            break
    if not portfolio_section:
        for tag in soup.find_all(True, {"id": _portfolio_patterns}):
            if len(tag.get_text(strip=True)) > 100:
                portfolio_section = tag
                break

    # Use portfolio section if found, otherwise full cleaned page
    search_root = portfolio_section if portfolio_section else soup

    companies = []
    seen = set()
    base_netloc = urlparse(base_url).netloc

    # ── Strategy A: External links (most reliable signal) ─────────────────────
    for a in search_root.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text(strip=True)

        if not text or len(text) < 2 or len(text) > 60:
            continue
        if len(text.split()) > 6:
            continue
        if text.lower() in COMPANY_NOISE:
            continue
        if _SCRAPE_JUNK_RE.search(text):
            continue
        # Must be an external link (different domain)
        if not href.startswith("http"):
            continue
        link_netloc = urlparse(href).netloc
        if not link_netloc or link_netloc == base_netloc:
            continue
        # Skip known aggregator/news domains
        if any(s in link_netloc for s in SKIP_DOMAINS):
            continue

        key = text.lower().strip()
        if key not in seen:
            seen.add(key)
            companies.append({"company_name": text.strip(), "company_website": href})

    # ── Strategy B: Heading tags in portfolio section ─────────────────────────
    # Only run if we found a portfolio-specific section
    if portfolio_section and len(companies) < 5:
        for tag in portfolio_section.find_all(["h2", "h3", "h4", "strong", "b"]):
            text = tag.get_text(strip=True)
            if not text or len(text) < 2 or len(text) > 60:
                continue
            if len(text.split()) > 5:
                continue
            if text.lower() in COMPANY_NOISE:
                continue
            if _SCRAPE_JUNK_RE.search(text):
                continue
            # Must look like a proper noun (capital first letter + lowercase)
            words = text.split()
            has_proper = any(
                len(w) >= 2 and w[0].isupper() and any(c.islower() for c in w[1:])
                for w in words
            )
            if not has_proper:
                continue
            # Skip if all lowercase
            if text == text.lower():
                continue

            # Try to find associated external link
            company_url = None
            a_parent = tag.find_parent("a")
            if a_parent:
                href = a_parent.get("href", "")
                if href.startswith("http") and urlparse(href).netloc != base_netloc:
                    company_url = href

            key = text.lower().strip()
            if key not in seen:
                seen.add(key)
                companies.append({"company_name": text.strip(), "company_website": company_url})

    return companies[:150]  # cap at 150 per VC

# ── DuckDuckGo search for VC website ─────────────────────────────────────────
SKIP_DOMAINS = {
    "crunchbase", "linkedin", "tracxn", "twitter", "yourstory",
    "inc42", "techcrunch", "wikipedia", "glassdoor", "ambitionbox",
    "angellist", "wellfound", "indianvcs", "moneycontrol", "livemint",
    "economictimes", "business-standard", "entrackr", "theKen", "vccircle",
    "slideshare", "facebook", "instagram", "youtube", "medium", "substack",
}

def ddg_find_website(vc_name: str) -> str | None:
    """Use ddgs library to find the VC's official website."""
    query = f"{vc_name} venture capital india official website"
    try:
        results = list(DDGS().text(query, max_results=10))
        for r in results:
            href = r.get("href", "")
            if not href:
                continue
            parsed = urlparse(href)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                if not any(s in parsed.netloc for s in SKIP_DOMAINS):
                    return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass

    # Fallback: guess common domain patterns from the VC name
    slug = re.sub(r"[^a-z0-9]", "", vc_name.lower())
    for tld in [".com", ".in", ".vc", ".fund"]:
        candidate = f"https://www.{slug}{tld}"
        try:
            r = requests.head(candidate, timeout=5, allow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code < 400:
                return candidate
        except Exception:
            pass
    return None


# ── Extract company names from a portfolio page ───────────────────────────────
def extract_companies_from_html(html: str, base_url: str) -> list[dict]:
    """Parse portfolio page HTML and extract company name + website."""
    soup = BeautifulSoup(html, "html.parser")
    companies = []
    seen = set()

    # Strategy 1: Look for cards/items with company name + link
    # Common patterns: grid of logos, list of company names
    for tag in soup.find_all(["h2", "h3", "h4", "strong", "b", "p", "span", "div"]):
        text = tag.get_text(strip=True)
        if not text or len(text) < 2 or len(text) > 60:
            continue
        if text.lower() in COMPANY_NOISE:
            continue
        # Must look like a company name (not a sentence)
        if len(text.split()) > 6:
            continue
        # Skip if it's all lowercase words (likely nav/menu)
        if text == text.lower() and " " in text:
            continue

        # Look for associated link
        company_url = None
        parent = tag.parent
        if parent and parent.name == "a":
            href = parent.get("href", "")
            if href and href.startswith("http") and base_url not in href:
                company_url = href
        elif tag.name != "a":
            a = tag.find_parent("a")
            if a:
                href = a.get("href", "")
                if href and href.startswith("http") and urlparse(base_url).netloc not in href:
                    company_url = href

        key = text.lower().strip()
        if key not in seen and len(key) > 1:
            seen.add(key)
            companies.append({"company_name": text.strip(), "company_website": company_url})

    # Strategy 2: Explicit "portfolio" or "companies" section links
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 2 or len(text) > 60 or len(text.split()) > 6:
            continue
        if text.lower() in COMPANY_NOISE:
            continue
        # External link = likely a portfolio company
        if href.startswith("http") and urlparse(base_url).netloc not in href:
            key = text.lower().strip()
            if key not in seen:
                seen.add(key)
                companies.append({"company_name": text.strip(), "company_website": href})

    return companies[:150]  # cap at 150 per VC


def scrape_portfolio_playwright(url: str, pw_browser) -> tuple[str | None, list[dict]]:
    """Use Playwright to render a portfolio page and extract companies."""
    page = pw_browser.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(2000)
        html = page.content()
        final_url = page.url
        companies = extract_companies_from_html(html, final_url)
        return final_url, companies
    except PwTimeout:
        try:
            html = page.content()
            return url, extract_companies_from_html(html, url)
        except Exception:
            return None, []
    except Exception:
        return None, []
    finally:
        page.close()


def find_portfolio_url(base_url: str, pw_browser) -> tuple[str | None, list[dict]]:
    """Try common portfolio paths on the VC's website."""
    for path in PORTFOLIO_PATHS:
        candidate = base_url.rstrip("/") + path
        try:
            resp = requests.head(candidate, timeout=5, allow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                # Found a valid page — render it properly
                final_url, companies = scrape_portfolio_playwright(candidate, pw_browser)
                if companies:
                    return final_url or candidate, companies
        except Exception:
            continue

    # Fallback: try homepage itself
    try:
        final_url, companies = scrape_portfolio_playwright(base_url, pw_browser)
        if companies:
            return final_url, companies
    except Exception:
        pass
    return None, []


# ── Fuzzy matching against funding_rounds ────────────────────────────────────
def fuzzy_match(name_a: str, name_b: str) -> float:
    a = re.sub(r"\b(pvt|ltd|private|limited|inc|corp|technologies|technology|"
               r"solutions|ventures|capital|ai|labs?)\b", "", name_a.lower()).strip()
    b = re.sub(r"\b(pvt|ltd|private|limited|inc|corp|technologies|technology|"
               r"solutions|ventures|capital|ai|labs?)\b", "", name_b.lower()).strip()
    return SequenceMatcher(None, a, b).ratio()


def match_and_enrich(conn: sqlite3.Connection):
    """Match vc_portfolios against funding_rounds and enrich investor data."""
    portfolio_rows = conn.execute(
        "SELECT vc_name, company_name FROM vc_portfolios"
    ).fetchall()
    funding_rows = conn.execute(
        "SELECT id, company_name, investors_raw, lead_investor FROM funding_rounds"
    ).fetchall()

    matched = 0
    for vc_name, portfolio_company in portfolio_rows:
        best_id = None
        best_score = 0.0
        for f_id, f_company, investors_raw, lead in funding_rows:
            if not f_company:
                continue
            score = fuzzy_match(portfolio_company, f_company)
            if score > best_score:
                best_score = score
                best_id = f_id

        if best_id and best_score >= 0.82:
            # Enrich investors_raw
            row = conn.execute(
                "SELECT investors_raw, lead_investor FROM funding_rounds WHERE id=?", (best_id,)
            ).fetchone()
            if row:
                existing = row[0] or ""
                if vc_name.lower() not in existing.lower():
                    new_investors = f"{existing}, {vc_name}".strip(", ")
                    conn.execute(
                        "UPDATE funding_rounds SET investors_raw=? WHERE id=?",
                        (new_investors, best_id)
                    )
                # Log the enrichment
                try:
                    conn.execute(
                        "INSERT INTO vc_enrichments (funding_round_id, vc_name, match_score) VALUES (?,?,?)",
                        (best_id, vc_name, round(best_score, 3))
                    )
                except sqlite3.IntegrityError:
                    pass
                matched += 1

    conn.commit()
    return matched


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(CREATE_PORTFOLIOS + CREATE_VC_ENRICHMENTS)
    conn.commit()

    # Load VCs from our scraped table
    vcs = conn.execute("SELECT fund_name FROM indian_vcs ORDER BY fund_name").fetchall()
    print(f"Processing {len(vcs)} Indian VCs...\n")

    total_companies = 0
    total_vcs_with_portfolio = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        for i, (vc_name,) in enumerate(vcs, 1):
            print(f"[{i}/{len(vcs)}] {vc_name}")

            # Resume check: skip if already scraped
            already = conn.execute(
                "SELECT COUNT(*) FROM vc_portfolios WHERE vc_name = ?", (vc_name,)
            ).fetchone()[0]
            if already > 0:
                print(f"  Already scraped ({already} companies), skipping")
                total_vcs_with_portfolio += 1
                total_companies += already
                continue

            # Step 1: Find website
            website = ddg_find_website(vc_name)
            if not website:
                print(f"  No website found, skipping")
                time.sleep(0.5)
                continue
            print(f"  Website: {website}")

            # Step 2: Find portfolio page + scrape companies
            portfolio_url, companies = find_portfolio_url(website, browser)
            if not companies:
                print(f"  No portfolio page found")
                time.sleep(1)
                continue

            # Filter: must look like real company names
            valid = [c for c in companies if
                     len(c["company_name"]) > 2 and
                     c["company_name"].lower() not in COMPANY_NOISE and
                     not c["company_name"].startswith(("©", "http", "@"))]

            if not valid:
                print(f"  Portfolio found but no valid company names extracted")
                time.sleep(1)
                continue

            print(f"  Portfolio: {portfolio_url}")
            print(f"  Companies: {len(valid)} extracted")

            # Step 3: Save to DB
            saved = 0
            for c in valid:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO vc_portfolios
                            (vc_name, vc_website, portfolio_url, company_name, company_website)
                        VALUES (?, ?, ?, ?, ?)
                    """, (vc_name, website, portfolio_url, c["company_name"], c["company_website"]))
                    saved += 1
                except Exception:
                    pass
            conn.commit()

            total_companies += saved
            total_vcs_with_portfolio += 1
            print(f"  Saved {saved} companies")
            time.sleep(2)  # polite delay

        browser.close()

    print(f"\n{'='*50}")
    print(f"VCs with portfolio data: {total_vcs_with_portfolio}/{len(vcs)}")
    print(f"Total portfolio companies: {total_companies}")

    # Phase 3: Match & enrich funding_rounds
    print(f"\nMatching against funding_rounds...")
    enriched = match_and_enrich(conn)
    print(f"Enriched {enriched} funding rounds with VC-confirmed investor data")

    # Final counts
    total_rounds = conn.execute("SELECT COUNT(*) FROM funding_rounds").fetchone()[0]
    total_portfolio = conn.execute("SELECT COUNT(*) FROM vc_portfolios").fetchone()[0]
    conn.close()

    print(f"\nDone!")
    print(f"  vc_portfolios table: {total_portfolio} rows")
    print(f"  funding_rounds enriched: {enriched}")
    print(f"  Total funding rounds: {total_rounds}")
    print(f"\nView portfolio data at: http://127.0.0.1:8001/funding/vc_portfolios")
    print(f"View enrichments at:    http://127.0.0.1:8001/funding/vc_enrichments")
