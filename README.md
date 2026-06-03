# 💰 Funding Intelligence Database

A **self-updating, searchable database of global startup funding rounds** — built entirely on free RSS sources, with zero API costs.

Tracks 4,700+ rounds across 2022–2026 from **20 RSS feeds** (TechCrunch, Inc42, Sifted, Entrackr, EU-Startups, KrASIA, and more) + 14 Google News queries. Searchable and filterable via a local Datasette web UI.

---

## ✨ Features

- 📡 **20 RSS sources** covering India, Southeast Asia, Europe, Africa, LatAm, and Global
- 🔍 **Full-text search** across company, investor, sector, geography, and founder fields
- 🏷️ **Auto-extracted fields** — amount, round type, sector, geography, founder name, LinkedIn link
- 🔄 **Auto-collection** — runs on boot and every 6 hours via Windows Task Scheduler
- 📊 **Browser UI** via Datasette — filter by country, sector, round type, stage, year, month
- 💾 **CSV / JSON export** built in
- 🔁 **Deduplication** — fuzzy merge of same company+round from multiple sources

---

## 🚀 Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/gstar213/funding-db.git
cd funding-db
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Open the browser UI

```bash
python -X utf8 main.py serve
```

Visit **http://localhost:8001/funding/funding_rounds** to explore.

> **That's it!** `funding.db` ships with the repo — you get 4,700+ historical rounds (2022–2026) immediately on clone, no backfill needed.

### 5. (Optional) Run a fresh collection to get the latest rounds

```bash
python -X utf8 main.py collect
```

---

## 📟 All CLI Commands

| Command | Description |
|---|---|
| `python main.py init` | Create `funding.db` (run once) |
| `python main.py collect` | Run one collection cycle across all sources |
| `python main.py run` | Run forever, collecting every 6 hours |
| `python main.py run --interval 60` | Collect every 60 minutes |
| `python main.py serve` | Open Datasette browser UI at port 8001 |
| `python main.py status` | Show DB stats: total rounds, by country, by sector |
| `python main.py export --format csv` | Export to CSV |
| `python main.py export --country India --sector "AI/ML"` | Filtered export |

> **Windows users:** Always use `python -X utf8` prefix, or set `PYTHONIOENCODING=utf-8` in your environment to avoid CP1252 encoding errors.

---

## 🔄 Auto-Collection Setup (Windows Task Scheduler)

Run this **once** to schedule automatic collection at every system startup and every 6 hours:

```bash
python setup_scheduler.py
```

> **Note:** Run from an elevated (Administrator) terminal for best results.  
> If UAC prevents it, the tasks will still be created but will run under your user account.

### Other scheduler commands

```bash
# Check if tasks are active
python setup_scheduler.py --status

# Remove both scheduled tasks
python setup_scheduler.py --remove
```

This creates two Windows Task Scheduler tasks:

| Task Name | Trigger |
|---|---|
| `FundingDB-OnBoot` | 2 minutes after every system startup |
| `FundingDB-Every6h` | Every 6 hours while the PC is running |

To manage tasks manually: open **Task Scheduler** → *Task Scheduler Library* → look for `FundingDB-*`.

---

## 🌐 Data Sources (all free, no API keys)

| Source | Region |
|---|---|
| TechCrunch | Global |
| VentureBeat | Global (tech) |
| Crunchbase News | Global (confirmed rounds) |
| Forbes Startups | Global |
| The Information | Global |
| Hacker News | Global |
| YourStory | India |
| Inc42 | India |
| Entrackr | India |
| Sifted | Europe |
| EU-Startups | Europe |
| e27 | Southeast Asia |
| Tech in Asia | Southeast Asia |
| Deal Street Asia | Southeast Asia |
| KrASIA | Southeast Asia |
| Disrupt Africa | Africa |
| African Business | Africa |
| Contxto | Latin America |
| Startup Story | South Asia |
| Business Insider VC | Global |
| **Google News** (14 queries) | Global — all regions |

**Expected yield per collection:** 50–200 new funding rounds.

---

## 🗄️ Database Schema

The main table `funding_rounds` has these columns:

| Column | Description |
|---|---|
| `company_name` | Extracted startup name |
| `company_domain` | Startup website (not the news site) |
| `round_type` | pre-seed / seed / Series A–F / IPO / acquisition |
| `stage` | early / growth / late |
| `amount_usd` | Amount in USD (numeric, for sorting/filtering) |
| `amount_display` | Human-readable: "$5M", "₹50 crore", "Undisclosed" |
| `hq_country` | Country of HQ |
| `hq_city` | City of HQ |
| `region` | South Asia / Europe / Southeast Asia / etc. |
| `sector` | AI/ML / Fintech / Healthtech / SaaS / etc. |
| `sub_sector` | More specific classification |
| `lead_investor` | First-named investor |
| `investors_raw` | All investors, comma-separated |
| `founder_name` | Extracted CEO/founder name |
| `founder_linkedin` | LinkedIn search URL for the founder |
| `announced_date` | Date of the article (YYYY-MM-DD) |
| `announced_year` | Year (for faceting) |
| `announced_month` | Month 1–12 (for faceting) |
| `source_name` | News outlet name |
| `source_url` | Original article link |
| `headline` | Article headline |
| `confidence` | 0.0–1.0 extraction quality score |

---

## 🔍 Datasette Filter Examples

```
# All Indian AI/ML startups
/funding/funding_rounds?hq_country=India&sector=AI%2FML

# Series A rounds above $5M
/funding/funding_rounds?round_type=Series+A&amount_usd__gte=5000000

# 2026 rounds, sorted by amount (largest first)
/funding/funding_rounds?announced_year=2026&_sort_desc=amount_usd

# All European seed rounds
/funding/funding_rounds?region=Europe&round_type=seed
```

---

## 🛠️ Utility Scripts

| Script | Purpose |
|---|---|
| `enrich_missing.py` | Fill NULL `hq_country`/`sector` on existing rows |
| `dedup.py` | Remove near-duplicate rounds (same company + round + year) |
| `export_csv.py` | Export all rows to `funding_rounds_export.csv` |
| `enable_fts.py` | Rebuild the FTS5 full-text search index |
| `reprocess_unknowns.py` | Re-extract rows where `company_name = 'Unknown'` |
| `indianvcs_scraper.py` | Scrape 204 Indian VC fund profiles from indianvcs.com |
| `vc_portfolio_scraper.py` | Scrape VC portfolio pages, fuzzy-match against DB |
| `backfill.py` | Historical collection 2022–2024 |
| `_backfill_2025.py` | Historical collection 2025–2026 |

Run utility scripts from the project directory:

```bash
python -X utf8 enrich_missing.py
python -X utf8 dedup.py
python -X utf8 export_csv.py
```

---

## 📁 Project Structure

```
funding-db/
├── main.py                  # CLI (init, collect, run, serve, status, export)
├── schema.py                # SQLite schema definition
├── collector.py             # RSS + Google News fetcher (20 sources)
├── extractor.py             # NLP: amount, round, geography, sector, investors, founder
├── setup_scheduler.py       # Windows Task Scheduler auto-setup
├── datasette_metadata.json  # Datasette UI config: facets, labels, FTS
├── requirements.txt
│
├── enrich_missing.py        # Fill NULL country/sector fields
├── dedup.py                 # Fuzzy dedup of same-company rounds
├── export_csv.py            # CSV export utility
├── enable_fts.py            # Rebuild FTS5 index
├── reprocess_unknowns.py    # Re-extract Unknown company rows
│
├── indianvcs_scraper.py     # Scrape Indian VC fund directory
├── vc_portfolio_scraper.py  # Scrape VC portfolio pages
├── indianvcs_funds.json     # 204 Indian VC funds (static export)
│
├── backfill.py              # Historical backfill 2022–2024
├── _backfill_2025.py        # Historical backfill 2025–2026
├── _migrate.py              # DB migration: adds year/month columns
│
├── funding.db               # The database (4,700+ rounds, committed to git)
└── exports/                 # JSON/CSV exports (created on demand)
```

---

## ⚠️ Known Issues & Tips

1. **Windows terminal encoding** — always run with `python -X utf8` to avoid CP1252 errors with Unicode symbols (₹, →, etc.)
2. **Datasette metadata** — `datasette_metadata.json` uses `sort_desc`, not `sort` — don't use both simultaneously
3. **FTS index** — if you add rows manually via SQL (not through `main.py collect`), re-run `enable_fts.py` to update the search index
4. **DuckDuckGo rate limiting** — `vc_portfolio_scraper.py` has a 2-second delay per VC; removing it causes bans
5. **CSV export** — `funding_rounds_export.csv` is not auto-generated; run `export_csv.py` after major DB changes

---

## 📜 License

MIT — free to use, modify, and distribute.
