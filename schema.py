"""
schema.py — SQLite schema for the Global Funding Intelligence Database
Run: python schema.py   (creates funding.db)
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "funding.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS funding_rounds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name    TEXT NOT NULL,
    company_domain  TEXT,
    description     TEXT,
    founded_year    INTEGER,

    -- Geography
    hq_country      TEXT,
    hq_city         TEXT,
    region          TEXT,   -- "South Asia", "North America", "Europe", etc.

    -- Round details
    round_type      TEXT,   -- "seed", "Series A", "Series B", "IPO", etc.
    amount_usd      REAL,   -- in USD
    amount_display  TEXT,   -- "$1.5M", "$200K"
    currency        TEXT DEFAULT 'USD',
    valuation_usd   REAL,

    -- Investors
    lead_investor   TEXT,
    investors_raw   TEXT,   -- comma-separated list

    -- Classification
    sector          TEXT,   -- "AI/ML", "Fintech", "SaaS", "Healthtech", etc.
    sub_sector      TEXT,   -- "LLM Infrastructure", "Payments", etc.
    stage           TEXT,   -- "early", "growth", "late"

    -- Source tracking
    source_name     TEXT,   -- "TechCrunch", "YourStory", "Sifted"
    source_url      TEXT,
    headline        TEXT,
    confidence      REAL DEFAULT 0.5,  -- 0.0-1.0 extraction confidence

    -- Timestamps
    announced_date  TEXT,   -- YYYY-MM-DD
    collected_at    TEXT DEFAULT (datetime('now')),

    -- Dedup
    content_hash    TEXT UNIQUE  -- SHA1 of (company_name + amount_usd + announced_date)
);

CREATE INDEX IF NOT EXISTS idx_country    ON funding_rounds(hq_country);
CREATE INDEX IF NOT EXISTS idx_sector     ON funding_rounds(sector);
CREATE INDEX IF NOT EXISTS idx_round_type ON funding_rounds(round_type);
CREATE INDEX IF NOT EXISTS idx_date       ON funding_rounds(announced_date DESC);
CREATE INDEX IF NOT EXISTS idx_amount     ON funding_rounds(amount_usd DESC);

CREATE TABLE IF NOT EXISTS collection_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT,
    started_at  TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    found       INTEGER DEFAULT 0,
    new         INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running',
    error       TEXT
);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"[OK] Database initialised at {DB_PATH}")


if __name__ == "__main__":
    init_db()
