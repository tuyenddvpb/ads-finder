"""Đọc config.json và .env."""
import json
import os
from pathlib import Path

DEFAULTS = {
    "keywords": [],
    "countries": ["DE", "FR", "NL", "GB"],
    "api_version": "v24.0",
    "page_size": 50,
    "max_pages_per_query": 4,
    "exclude_terms": ["med spa", "medspa", "spa", "clinic", "salon", "facial", "properties", "real estate", "appointment", "retreats"],
    "db_path": "data/ads.db",
    "port": 8765,
}


def load_config(path="config.json"):
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def load_env(path=".env"):
    """Nạp các dòng KEY=VALUE từ .env vào os.environ (không ghi đè biến đã có)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
