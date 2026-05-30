"""
indianvcs_scraper.py — Scrape all Indian VC fund data from indianvcs.com
Uses Playwright to render JS-loaded Webflow CMS content.
Saves to indianvcs_funds.json and imports into funding.db as an investor reference table.
"""
import json
import re
import sqlite3
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DB_PATH = Path(__file__).parent / "funding.db"
OUTPUT_JSON = Path(__file__).parent / "indianvcs_funds.json"

# ── Schema for the new table ──────────────────────────────────────────────────
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS indian_vcs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_name     TEXT NOT NULL,
    stages        TEXT,
    sectors       TEXT,
    ticket_min_usd REAL,
    ticket_max_usd REAL,
    ticket_display TEXT,
    scraped_at    TEXT DEFAULT (datetime('now'))
);
"""

KNOWN_STAGES = {"PRE-SEED", "SEED", "SERIES A", "SERIES B", "SERIES C", "SERIES D", "DEBT", "GROWTH"}
KNOWN_SECTORS = {
    "SECTOR AGNOSTIC", "SEMICONDUCTORS", "B2B", "B2C / ECOMMERCE", "ENERGY",
    "AUTOMOTIVE / EV", "CYBER SECURITY", "ADVANCED MANUFACTURING", "TRAVEL / HOSPITALITY",
    "SUPPLY CHAIN / LOGISTICS", "SOCIAL IMPACT", "SAAS / DEVOPS / MARKETPLACE",
    "PROP TECH/REAL ESTATE", "MOBILITY", "LOGISTICS", "MEDIA & ENTERTAINMENT",
    "HEALTHCARE/MEDTECH", "INDUSTRIAL / IOT / ROBOTICS", "HEALTH AND WELLNESS",
    "GOVERNMENT / DEFENCE", "FINTECH", "GAMING", "ENTERPRISE", "DEEP TECH / HARD SCIENCE",
    "EDTECH", "EDUCATION", "DEEPTECH", "CONSUMER", "CLIMATE / SUSTAINABILITY",
    "B2B COMMERCE", "AGRITECH / FOOD", "BIOTECH / LIFE SCIENCES", "AR / VR", "AI / ML",
}

_TICKET_PATTERN = re.compile(
    r'\$\s*([\d,.]+)\s*([KMBkm]?)\s*[-–]\s*\$?\s*([\d,.]+)\s*([KMBkm]?)', re.I
)

def _parse_ticket(raw: str):
    """Parse ticket range like '$ 100K - $ 500K' → (100000, 500000)."""
    def to_usd(num_str, suffix):
        n = float(num_str.replace(',', ''))
        s = suffix.upper()
        if s == 'K': n *= 1_000
        elif s == 'M': n *= 1_000_000
        elif s == 'B': n *= 1_000_000_000
        return n
    m = _TICKET_PATTERN.search(raw)
    if m:
        try:
            lo = to_usd(m.group(1), m.group(2))
            hi = to_usd(m.group(3), m.group(4))
            return lo, hi
        except Exception:
            pass
    return None, None


def parse_fund_block(lines: list[str]) -> dict | None:
    """
    Given a block of text lines for one fund, extract structured data.
    Lines look like:
      ["2am VC", "PRE-SEED", "SEED", "SERIES A", "SECTOR AGNOSTIC", "$ 100K - $ 500K"]
    """
    if not lines:
        return None

    # First non-empty line that isn't a known stage/sector/ticket is the fund name
    fund_name = None
    stages = []
    sectors = []
    ticket_raw = None

    for line in lines:
        line_up = line.strip().upper()
        if not line_up:
            continue
        if line_up in KNOWN_STAGES:
            stages.append(line.strip().title())
        elif line_up in KNOWN_SECTORS:
            sectors.append(line.strip().title())
        elif re.search(r'\$', line):
            ticket_raw = line.strip()
        elif fund_name is None:
            fund_name = line.strip()

    if not fund_name:
        return None

    min_usd, max_usd = _parse_ticket(ticket_raw) if ticket_raw else (None, None)

    return {
        "fund_name": fund_name,
        "stages": ", ".join(stages) if stages else None,
        "sectors": ", ".join(sectors) if sectors else None,
        "ticket_display": ticket_raw,
        "ticket_min_usd": min_usd,
        "ticket_max_usd": max_usd,
    }


def scrape_all_pages() -> list[dict]:
    """Scrape all 21 pages of funds from indianvcs.com."""
    all_funds = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

        print("Loading indianvcs.com...")
        page.goto("https://www.indianvcs.com", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        page_num = 1
        while True:
            print(f"  Scraping page {page_num}...")

            # Wait for fund cards to render
            page.wait_for_timeout(2000)

            # Get the main fund list area text
            # Each fund card is a .table_content-row_item or similar
            # We'll grab all text from the table body
            try:
                # Try to find the fund list container
                fund_rows = page.query_selector_all(".table_content-row_item")
                if not fund_rows:
                    # Fallback: grab all w-dyn-item elements that are NOT filter checkboxes
                    fund_rows = page.query_selector_all(".funds-list .w-dyn-item, [fs-cmsload-element='list'] .w-dyn-item")
            except Exception:
                fund_rows = []

            if fund_rows:
                print(f"    Found {len(fund_rows)} fund rows via selector")
                for row in fund_rows:
                    text = row.inner_text().strip()
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    fund = parse_fund_block(lines)
                    if fund and fund["fund_name"] not in [f["fund_name"] for f in all_funds]:
                        all_funds.append(fund)
                        print(f"    + {fund['fund_name']} | {fund['stages']} | {fund['ticket_display']}")
            else:
                # Fallback: parse main text block
                print("    Using text fallback...")
                main_text = page.locator("main").inner_text()
                # Split into fund blocks by detecting fund name lines
                # (non-stage, non-sector, non-ticket lines)
                lines = main_text.split('\n')
                current_block = []
                in_funds = False
                for line in lines:
                    stripped = line.strip()
                    if "FUND NAME" in stripped.upper():
                        in_funds = True
                        continue
                    if not in_funds:
                        continue
                    if stripped in ["1", "2", "3", "4", "5", "....", "21"] or "Think we missed" in stripped:
                        break
                    # New fund starts when line isn't stage/sector/ticket and we have a block
                    line_up = stripped.upper()
                    is_meta = (line_up in KNOWN_STAGES or line_up in KNOWN_SECTORS or
                               re.search(r'\$', stripped))
                    if not is_meta and stripped and current_block:
                        # flush previous block
                        fund = parse_fund_block(current_block)
                        if fund and fund["fund_name"] not in [f["fund_name"] for f in all_funds]:
                            all_funds.append(fund)
                            print(f"    + {fund['fund_name']}")
                        current_block = [stripped]
                    elif stripped:
                        current_block.append(stripped)
                # flush last block
                if current_block:
                    fund = parse_fund_block(current_block)
                    if fund and fund["fund_name"] not in [f["fund_name"] for f in all_funds]:
                        all_funds.append(fund)

            # Try to go to next page
            next_btn = page.query_selector("[fs-cmsload-element='next-page']:not([disabled]), .w-pagination-next:not([disabled])")
            if not next_btn:
                # Try by text
                next_btn = page.get_by_role("button", name=str(page_num + 1)).first
                try:
                    next_btn.wait_for(timeout=2000)
                except Exception:
                    next_btn = None

            if next_btn:
                try:
                    next_btn.click()
                    page_num += 1
                    page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  Next page click failed: {e}")
                    break
            else:
                print(f"  No more pages after page {page_num}")
                break

        browser.close()

    return all_funds


def save_to_db(funds: list[dict]):
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(CREATE_TABLE)
    conn.execute("DELETE FROM indian_vcs")  # fresh import
    for f in funds:
        conn.execute("""
            INSERT INTO indian_vcs (fund_name, stages, sectors, ticket_display, ticket_min_usd, ticket_max_usd)
            VALUES (:fund_name, :stages, :sectors, :ticket_display, :ticket_min_usd, :ticket_max_usd)
        """, f)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM indian_vcs").fetchone()[0]
    conn.close()
    print(f"\n[DB] Saved {count} funds to indian_vcs table in funding.db")


if __name__ == "__main__":
    print("=== IndianVCs.com Scraper ===")
    funds = scrape_all_pages()
    print(f"\nTotal funds scraped: {len(funds)}")

    # Save JSON
    OUTPUT_JSON.write_text(json.dumps(funds, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON saved to {OUTPUT_JSON}")

    # Save to DB
    save_to_db(funds)
    print("\nDone! View at http://127.0.0.1:8001/funding/indian_vcs")
