"""Kiểm tra một domain có phải store Shopify không, qua /products.json công khai."""
import json
import re
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; ads-finder/1.0)"
WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {"the", "and", "for", "with", "your", "you", "off", "new", "free", "now", "our", "from", "this", "that"}


def check_store(domain, timeout=12):
    """Trả về {'is_shopify', 'product_count', 'products', 'error'}."""
    url = f"https://{domain}/products.json?limit=250"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read(5_000_000).decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"is_shopify": False, "product_count": None, "products": [], "error": str(exc)[:200]}
    items = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {"is_shopify": False, "product_count": None, "products": [], "error": "không có danh sách products"}
    products = []
    for item in items:
        variants = item.get("variants") or [{}]
        products.append({
            "title": item.get("title") or "",
            "handle": item.get("handle") or "",
            "price": variants[0].get("price"),
            "created_at": item.get("created_at"),
        })
    return {"is_shopify": True, "product_count": len(products), "products": products, "error": None}


def tokens(text):
    return {w for w in WORD_RE.findall((text or "").lower()) if len(w) > 2 and w not in STOPWORDS}


def match_product(ad_title, products, threshold=0.25):
    """Tìm sản phẩm của store có tên giống tiêu đề ad nhất (Jaccard theo từ)."""
    want = tokens(ad_title)
    best, best_score = None, 0.0
    if not want:
        return None
    for product in products:
        have = tokens(product.get("title"))
        if not have:
            continue
        score = len(want & have) / len(want | have)
        if score > best_score:
            best, best_score = product, score
    return best if best_score >= threshold else None
