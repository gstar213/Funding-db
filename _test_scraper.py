"""Quick test: run scraper on first 3 VCs only, verbose output."""
import sqlite3, re, time, requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urlparse
from difflib import SequenceMatcher
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

DB_PATH = Path(__file__).parent / "funding.db"

PORTFOLIO_PATHS = [
    "/portfolio", "/companies", "/investments", "/our-portfolio",
    "/portfolio-companies", "/startups", "/our-companies",
]

COMPANY_NOISE = {
    "portfolio","companies","startups","investments","home","about",
    "team","contact","blog","news","press","careers","resources",
    "login","signup","get in touch","learn more","view all","see all",
    "apply","apply now","our portfolio","exit",
}

def ddg_find_website(vc_name):
    query = f"{vc_name} venture capital india official site"
    print(f"    DDG query: {query}")
    try:
        resp = requests.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10
        )
        print(f"    DDG status: {resp.status_code}, len={len(resp.text)}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a.result-link, td.result-snippet a, a[href*='http']"):
            href = a.get("href", "")
            if not href or "duckduckgo.com" in href or "google.com" in href:
                continue
            parsed = urlparse(href)
            if parsed.scheme in ("http","https") and parsed.netloc:
                skip = {"crunchbase","linkedin","tracxn","twitter","yourstory",
                        "inc42","techcrunch","wikipedia","glassdoor","ambitionbox",
                        "angellist","wellfound","indianvcs"}
                if not any(s in parsed.netloc for s in skip):
                    return f"{parsed.scheme}://{parsed.netloc}"
    except Exception as e:
        print(f"    DDG error: {e}")
    return None

conn = sqlite3.connect(DB_PATH)
vcs = conn.execute("SELECT fund_name FROM indian_vcs ORDER BY fund_name LIMIT 3").fetchall()
conn.close()

print(f"Testing on first 3 VCs: {[v[0] for v in vcs]}\n")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    print("Playwright browser launched OK\n")

    for (vc_name,) in vcs:
        print(f"\n{'='*50}")
        print(f"VC: {vc_name}")
        website = ddg_find_website(vc_name)
        print(f"  Website found: {website}")

        if website:
            for path in PORTFOLIO_PATHS[:3]:
                url = website.rstrip("/") + path
                try:
                    resp = requests.head(url, timeout=5, allow_redirects=True,
                                        headers={"User-Agent": "Mozilla/5.0"})
                    print(f"  HEAD {url} -> {resp.status_code}")
                    if resp.status_code == 200:
                        page = browser.new_page()
                        try:
                            page.goto(url, wait_until="networkidle", timeout=15000)
                            html = page.content()
                            print(f"  Page loaded, HTML len={len(html)}")
                            page.close()
                        except Exception as e:
                            print(f"  Playwright error: {e}")
                            page.close()
                        break
                except Exception as e:
                    print(f"  HEAD error {url}: {e}")
        time.sleep(1)

    browser.close()

print("\nTest done.")
