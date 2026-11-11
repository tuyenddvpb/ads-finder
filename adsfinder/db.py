"""Lưu trữ SQLite."""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ads (
    id TEXT PRIMARY KEY,
    page_id TEXT, page_name TEXT, title TEXT, body TEXT, domain TEXT,
    snapshot_url TEXT, currency TEXT,
    created_at TEXT, start_at TEXT, stop_at TEXT,
    reach INTEGER, platforms TEXT, source TEXT,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ad_hits (
    ad_id TEXT NOT NULL, keyword TEXT NOT NULL, country TEXT NOT NULL,
    PRIMARY KEY (ad_id, keyword, country)
);
CREATE TABLE IF NOT EXISTS queries (
    keyword TEXT NOT NULL, country TEXT NOT NULL, last_run TEXT NOT NULL,
    PRIMARY KEY (keyword, country)
);
CREATE TABLE IF NOT EXISTS stores (
    domain TEXT PRIMARY KEY, is_shopify INTEGER NOT NULL,
    product_count INTEGER, products TEXT, error TEXT, checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ads_page ON ads(page_id);
"""

UPSERT_AD = """
INSERT INTO ads (id, page_id, page_name, title, body, domain, snapshot_url, currency,
                 created_at, start_at, stop_at, reach, platforms, source, first_seen, last_seen)
VALUES (:id, :page_id, :page_name, :title, :body, :domain, :snapshot_url, :currency,
        :created_at, :start_at, :stop_at, :reach, :platforms, :source, :run_at, :run_at)
ON CONFLICT(id) DO UPDATE SET
    page_name = CASE WHEN excluded.page_name != '' THEN excluded.page_name ELSE ads.page_name END,
    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE ads.title END,
    body = CASE WHEN excluded.body != '' THEN excluded.body ELSE ads.body END,
    domain = COALESCE(excluded.domain, ads.domain),
    currency = CASE WHEN excluded.currency != '' THEN excluded.currency ELSE ads.currency END,
    start_at = COALESCE(excluded.start_at, ads.start_at),
    stop_at = excluded.stop_at,
    reach = COALESCE(excluded.reach, ads.reach),
    platforms = CASE WHEN excluded.platforms != '' THEN excluded.platforms ELSE ads.platforms END,
    first_seen = MIN(ads.first_seen, excluded.first_seen),
    last_seen = MAX(ads.last_seen, excluded.last_seen)
"""


def connect(path):
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_ads(conn, ads, keyword, country, run_at):
    """Ghi một lượt kết quả của (keyword, country). Trả về số ads mới."""
    new = 0
    for ad in ads:
        exists = conn.execute("SELECT 1 FROM ads WHERE id = ?", (ad["id"],)).fetchone()
        new += 0 if exists else 1
        conn.execute(UPSERT_AD, {**ad, "run_at": run_at})
        conn.execute(
            "INSERT OR IGNORE INTO ad_hits (ad_id, keyword, country) VALUES (?, ?, ?)",
            (ad["id"], keyword, country),
        )
    conn.execute(
        "INSERT INTO queries (keyword, country, last_run) VALUES (?, ?, ?) "
        "ON CONFLICT(keyword, country) DO UPDATE SET last_run = MAX(last_run, excluded.last_run)",
        (keyword, country, run_at),
    )
    conn.commit()
    return new


def save_store(conn, domain, info, checked_at):
    conn.execute(
        "INSERT OR REPLACE INTO stores (domain, is_shopify, product_count, products, error, checked_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (domain, int(info["is_shopify"]), info.get("product_count"),
         json.dumps(info.get("products") or []), info.get("error"), checked_at),
    )
    conn.commit()
