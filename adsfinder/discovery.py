"""Tự tìm ads mà không cần nhập từ khóa.

Ba nguồn truy vấn, xoay vòng trong ngân sách số lượt gọi API mỗi lần chạy:
1. Cụm từ bán hàng chung cho mọi ngách, theo ngôn ngữ từng nước.
2. Các page đã xác định là store Shopify: lấy toàn bộ ads của page.
3. Từ khóa tự rút ra từ tên sản phẩm của các ads điểm cao.
"""
import re
import sys
from itertools import zip_longest

from . import db
from .meta_api import RATE_LIMIT_CODES, MetaApiError, search
from .normalize import normalize_ad
from .scoring import build_groups

ANY_COUNTRY = "EU"          # nhãn cho truy vấn gộp mọi nước trong config
PAGE_PREFIX = "@page:"      # từ khóa nội bộ cho truy vấn theo page
PAGE_BATCH = 10             # API nhận tối đa 10 page mỗi lượt

PHRASES = {
    "GB": ["free shipping", "50% off", "order now", "money back guarantee", "limited stock", "get yours today"],
    "DE": ["kostenloser versand", "50% rabatt", "jetzt bestellen", "geld-zurück-garantie",
           "solange der vorrat reicht", "heute bestellen"],
    "FR": ["livraison gratuite", "50% de réduction", "commandez maintenant", "satisfait ou remboursé",
           "stock limité", "offre limitée"],
    "NL": ["gratis verzending", "50% korting", "bestel nu", "niet goed geld terug", "beperkte voorraad", "op=op"],
    "IT": ["spedizione gratuita", "sconto 50%", "ordina ora", "soddisfatti o rimborsati", "scorte limitate",
           "offerta limitata"],
    "ES": ["envío gratis", "50% de descuento", "pide ahora", "garantía de devolución", "stock limitado",
           "oferta limitada"],
}
DEFAULT_PHRASES = PHRASES["GB"]

WORD_RE = re.compile(r"[^\W\d_]+")
# Từ quảng cáo và từ nối: không nói lên sản phẩm là gì.
FILLER = {
    "the", "and", "for", "with", "your", "you", "our", "from", "this", "that", "off", "sale", "free", "shipping",
    "new", "now", "shop", "buy", "get", "today", "only", "save", "deal", "best", "original", "official", "premium",
    "pro", "plus", "max", "set", "pack", "pcs", "der", "die", "das", "und", "für", "mit", "les", "des", "pour",
    "avec", "het", "een", "voor", "met", "per", "con", "para", "los", "las", "del", "gratis", "rabatt", "korting",
}


class Budget:
    """Đếm số lượt gọi API còn lại trong lần chạy này."""

    def __init__(self, calls):
        self.left = max(0, int(calls))

    def take(self):
        if self.left <= 0:
            return False
        self.left -= 1
        return True


def product_term(title):
    """Rút cụm 2-3 từ mô tả sản phẩm từ một tiêu đề, hoặc None nếu không đủ rõ."""
    words = [w for w in WORD_RE.findall((title or "").lower()) if len(w) > 2 and w not in FILLER]
    if len(words) < 2:
        return None
    return " ".join(words[:3])


def seed_phrases(conn, countries, added_at):
    for country in countries:
        for phrase in PHRASES.get(country, DEFAULT_PHRASES):
            db.add_term(conn, phrase, country, "phrase", added_at)


def expand_keywords(conn, groups, cfg, added_at):
    """Thêm từ khóa mới từ các sản phẩm điểm cao. Trả về danh sách vừa thêm."""
    total = conn.execute("SELECT COUNT(*) FROM terms WHERE source = 'auto'").fetchone()[0]
    room = min(cfg["auto_keywords_per_run"], cfg["max_auto_keywords"] - total)
    added = []
    for group in groups:
        if len(added) >= room:
            break
        if not group["n_active"] or group["excluded"] or group["big_brand"] or group["score"] < cfg["auto_keyword_min_score"]:
            continue
        product = (group["store"] or {}).get("product") or {}
        term = product_term(product.get("title") or group["title"])
        if term and db.add_term(conn, term, ANY_COUNTRY, "auto", added_at):
            added.append(term)
    return added


def refresh_tracked_pages(conn, groups, cfg, updated_at):
    """Chọn các page là store Shopify cỡ nhỏ để theo dõi toàn bộ ads. Trả về số page đang theo dõi."""
    best = {}
    for group in groups:
        store = group["store"] or {}
        if not group["page_id"] or not store.get("is_shopify") or group["big_brand"] or group["excluded"]:
            continue
        current = best.get(group["page_id"])
        if not current or group["score"] > current["score"]:
            best[group["page_id"]] = group
    ranked = sorted(best.values(), key=lambda g: g["score"], reverse=True)[: cfg["max_tracked_pages"]]
    conn.execute("UPDATE pages SET tracked = 0")
    for group in ranked:
        db.save_page(conn, group["page_id"], group["page_name"], group["domain"], True, updated_at)
    conn.commit()
    return len(ranked)


def plan_tasks(conn, cfg):
    """Danh sách truy vấn theo thứ tự ưu tiên: từ khóa của người dùng, rồi xen kẽ page / cụm từ / từ khóa tự động."""
    last_run = {(r["keyword"], r["country"]): r["last_run"] for r in conn.execute("SELECT * FROM queries")}
    oldest_first = lambda key: last_run.get(key) or ""

    user = [{"kind": "keyword", "term": k, "country": c} for k in cfg["keywords"] for c in cfg["countries"]]

    page_ids = [r["page_id"] for r in conn.execute("SELECT page_id FROM pages WHERE tracked = 1 ORDER BY page_id")]
    page_ids.sort(key=lambda pid: oldest_first((PAGE_PREFIX + pid, ANY_COUNTRY)))
    pages = [{"kind": "pages", "page_ids": page_ids[i:i + PAGE_BATCH]} for i in range(0, len(page_ids), PAGE_BATCH)]

    def terms(source):
        rows = conn.execute("SELECT term, country FROM terms WHERE source = ? ORDER BY rowid", (source,)).fetchall()
        per_country = {}
        for r in rows:
            if r["country"] == ANY_COUNTRY or r["country"] in cfg["countries"]:
                per_country.setdefault(r["country"], []).append(r)
        # Xen kẽ các nước, rồi đưa truy vấn chưa chạy hoặc chạy lâu nhất lên trước (sắp xếp ổn định).
        mixed = [r for batch in zip_longest(*per_country.values()) for r in batch if r]
        mixed.sort(key=lambda r: oldest_first((r["term"], r["country"])))
        return [{"kind": "keyword", "term": r["term"], "country": r["country"]} for r in mixed]

    rotating = [t for trio in zip_longest(pages, terms("phrase"), terms("auto")) for t in trio if t]
    return user + rotating


def run(conn, cfg, token, run_at, fetch=None, log=print):
    """Chạy một lượt tự tìm. Trả về thống kê; ném MetaApiError nếu mọi truy vấn đầu đều hỏng."""
    groups = build_groups(conn, cfg["exclude_terms"])
    seed_phrases(conn, cfg["countries"], run_at)
    tracked = refresh_tracked_pages(conn, groups, cfg, run_at)
    added = expand_keywords(conn, groups, cfg, run_at)
    conn.commit()
    log(f"Đang theo dõi {tracked} page; thêm {len(added)} từ khóa tự động" + (f": {', '.join(added)}" if added else ""))

    budget = Budget(cfg["max_calls_per_run"])
    stats = {"queries": 0, "ads": 0, "new": 0, "failed": 0, "tracked_pages": tracked, "auto_keywords_added": added}
    options = {"version": cfg["api_version"], "page_size": cfg["page_size"], "max_pages": cfg["max_pages_per_query"],
               "budget": budget}
    if fetch:
        options["fetch"] = fetch
    for task in plan_tasks(conn, cfg):
        if budget.left <= 0:
            log("Hết ngân sách lượt gọi cho lần chạy này; phần còn lại để lượt sau.")
            break
        multi = task["kind"] == "pages" or task["country"] == ANY_COUNTRY
        countries = cfg["countries"] if multi else [task["country"]]
        label = f"{len(task['page_ids'])} page" if task["kind"] == "pages" else f"'{task['term']}' / {task['country']}"
        try:
            raw, truncated = search(token, countries=countries, keyword=task.get("term"),
                                    page_ids=task.get("page_ids"), **options)
        except MetaApiError as exc:
            if exc.code in RATE_LIMIT_CODES:
                log(f"Meta báo chạm giới hạn lượt gọi; dừng sớm. ({label})")
                break
            stats["failed"] += 1
            print(f"[lỗi] {label}: {exc}", file=sys.stderr)
            if stats["failed"] >= 3 and stats["queries"] == 0:
                raise
            continue
        ads = [a for a in (normalize_ad(r, "meta_api") for r in raw) if a]
        if task["kind"] == "pages":
            new = 0
            for page_id in task["page_ids"]:
                mine = [a for a in ads if a["page_id"] == page_id]
                # Kết quả bị cắt thì page không có ad nào chưa chắc đã dừng: không ghi lượt rỗng.
                if mine or not truncated:
                    new += db.save_ads(conn, mine, PAGE_PREFIX + page_id, ANY_COUNTRY, run_at)
        else:
            new = db.save_ads(conn, ads, task["term"], task["country"], run_at)
        stats["queries"] += 1
        stats["ads"] += len(ads)
        stats["new"] += new
        log(f"{label}: {len(ads)} ads, {new} mới")
    return stats
