"""Gom ads thành nhóm sản phẩm và chấm điểm mức độ "đang thắng".

Meta không công bố chi tiêu, nên điểm dựa trên các tín hiệu gián tiếp.
"""
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime

from .shopify import match_product

# Trọng số từng tín hiệu; tín hiệu không có dữ liệu thì bỏ ra và chia lại cho đủ 100.
WEIGHTS = {"longevity": 40, "variants": 30, "reach": 20, "momentum": 10}
LONGEVITY_FULL_DAYS = 45      # chạy từ 45 ngày trở lên được trọn điểm
VARIANTS_FULL = 10            # từ 10 ads cùng sản phẩm được trọn điểm
MOMENTUM_FULL = 5             # 5 ads mới trong 7 ngày được trọn điểm
MOMENTUM_MIN_AGE_DAYS = 14    # chỉ tính "bật thêm" khi sản phẩm đã chạy ít nhất 14 ngày
REACH_LOG_RANGE = (3, 6)      # reach 1.000 -> 0 điểm, 1.000.000 -> trọn điểm

SPACE_RE = re.compile(r"\s+")


def clamp(value):
    return max(0.0, min(1.0, value))


def score_group(max_days, n_active, new_7d, reach):
    """Trả về (điểm 0-100, chi tiết từng tín hiệu theo thang 0-1)."""
    parts = {
        "longevity": clamp(max_days / LONGEVITY_FULL_DAYS),
        "variants": clamp((n_active - 1) / (VARIANTS_FULL - 1)),
        "momentum": clamp(new_7d / MOMENTUM_FULL) if max_days >= MOMENTUM_MIN_AGE_DAYS else 0.0,
    }
    if reach:
        lo, hi = REACH_LOG_RANGE
        parts["reach"] = clamp((math.log10(reach) - lo) / (hi - lo))
    total_weight = sum(WEIGHTS[name] for name in parts)
    score = sum(WEIGHTS[name] * value for name, value in parts.items()) / total_weight * 100
    return round(score), {name: round(value, 2) for name, value in parts.items()}


def days_between(start_iso, end_iso):
    if not start_iso or not end_iso:
        return 0
    delta = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
    return max(0, delta.days)


def title_key(title, body):
    text = title or (body or "")[:60]
    return SPACE_RE.sub(" ", text).strip().lower()


def build_groups(conn, exclude_terms=()):
    """Đọc DB và trả về danh sách nhóm sản phẩm đã chấm điểm, điểm cao trước."""
    last_run = {(r["keyword"], r["country"]): r["last_run"] for r in conn.execute("SELECT * FROM queries")}
    hits = defaultdict(list)
    for r in conn.execute("SELECT ad_id, keyword, country FROM ad_hits"):
        hits[r["ad_id"]].append((r["keyword"], r["country"]))
    stores = {r["domain"]: r for r in conn.execute("SELECT * FROM stores")}
    media = {r["ad_id"]: r for r in conn.execute("SELECT * FROM media")}
    snapshots = defaultdict(dict)
    for r in conn.execute("SELECT ad_id, day, reach FROM snapshots"):
        snapshots[r["ad_id"]][r["day"]] = r["reach"]
    # Khớp theo nguyên từ để "spa" không dính "space".
    terms = [re.escape(t.strip().lower()) for t in exclude_terms if t.strip()]
    exclude = re.compile(r"\b(?:" + "|".join(terms) + r")\b") if terms else None

    buckets = defaultdict(list)
    page_active = Counter()
    for row in conn.execute("SELECT * FROM ads"):
        ad = dict(row)
        ad["hits"] = hits.get(ad["id"], [])
        # Còn chạy nếu xuất hiện trong lượt quét mới nhất của ít nhất một truy vấn đã tìm ra nó.
        seen_latest = any(last_run.get(hit) == ad["last_seen"] for hit in ad["hits"])
        stopped = bool(ad["stop_at"]) and ad["stop_at"] <= ad["last_seen"]
        ad["active"] = seen_latest and not stopped
        ad["days"] = days_between(ad["start_at"], ad["stop_at"] if stopped else ad["last_seen"])
        page = ad["page_id"] or ad["page_name"]
        if ad["active"]:
            page_active[page] += 1
        buckets[(page, title_key(ad["title"], ad["body"]))].append(ad)

    groups = []
    for (page, _), ads in buckets.items():
        active = [a for a in ads if a["active"]]
        scored = active or ads
        max_days = max(a["days"] for a in scored)
        new_7d = sum(1 for a in active if a["days"] < 7)
        reaches = [a["reach"] for a in active if a["reach"]]
        reach = sum(reaches) if reaches else None
        if active:
            score, parts = score_group(max_days, len(active), new_7d, reach)
        else:
            score, parts = 0, {}
        title = Counter(a["title"] for a in ads if a["title"]).most_common(1)
        body = next((a["body"] for a in ads if a["body"]), "")
        domains = Counter(a["domain"] for a in ads if a["domain"]).most_common(1)
        domain = domains[0][0] if domains else None
        page_name = ads[0]["page_name"]
        haystack = " ".join([title[0][0] if title else "", page_name, body]).lower()
        days = defaultdict(lambda: {"ads": 0, "reach": 0, "has_reach": False})
        for a in ads:
            for day, day_reach in snapshots.get(a["id"], {}).items():
                days[day]["ads"] += 1
                if day_reach:
                    days[day]["reach"] += day_reach
                    days[day]["has_reach"] = True
        group = {
            "id": ads[0]["id"],
            "key": f"{page}|{title_key(ads[0]['title'], ads[0]['body'])}",
            "page_key": page,
            "history": [{"day": day, "ads": v["ads"], "reach": v["reach"] if v["has_reach"] else None}
                        for day, v in sorted(days.items())],
            "first_start": min((a["start_at"] for a in ads if a["start_at"]), default=None),
            "title": title[0][0] if title else "",
            "body": body[:400],
            "page_id": ads[0]["page_id"],
            "page_name": page_name,
            "page_active_ads": page_active[page],
            "n_active": len(active),
            "n_total": len(ads),
            "max_days": max_days,
            "new_7d": new_7d,
            "reach": reach,
            "score": score,
            "parts": parts,
            "countries": sorted({c for a in ads for _, c in a["hits"]}),
            "keywords": sorted({k for a in ads for k, _ in a["hits"]}),
            "currency": Counter(a["currency"] for a in ads if a["currency"]).most_common(1)[0][0]
            if any(a["currency"] for a in ads) else "",
            "domain": domain,
            "store": None,
            "excluded": bool(exclude and exclude.search(haystack)),
            "ads": [
                {"id": a["id"], "start_at": a["start_at"], "days": a["days"], "active": a["active"],
                 "reach": a["reach"], "snapshot_url": a["snapshot_url"],
                 "image": media[a["id"]]["file"] if a["id"] in media else None,
                 "is_video": bool(media[a["id"]]["is_video"]) if a["id"] in media else False}
                for a in sorted(ads, key=lambda a: a["start_at"] or "")
            ],
        }
        shot = next((a for a in group["ads"] if a["image"]), None)
        group["image"] = shot and shot["image"]
        group["is_video"] = bool(shot and shot["is_video"])
        store = stores.get(domain) if domain else None
        if store:
            products = json.loads(store["products"] or "[]")
            match = match_product(group["title"], products) if store["is_shopify"] else None
            newest = sorted(products, key=lambda p: p.get("created_at") or "", reverse=True)[:6]
            group["store"] = {
                "is_shopify": bool(store["is_shopify"]),
                "product_count": store["product_count"],
                "recent_products": [
                    {"title": p["title"], "price": p["price"], "created_at": p["created_at"],
                     "url": f"https://{domain}/products/{p['handle']}"} for p in newest
                ],
                "product": match and {
                    "title": match["title"], "price": match["price"], "created_at": match["created_at"],
                    "url": f"https://{domain}/products/{match['handle']}",
                },
            }
        groups.append(group)
    groups.sort(key=lambda g: (g["score"], g["n_active"], g["max_days"]), reverse=True)
    return groups
