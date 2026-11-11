"""Đưa dữ liệu ads từ nhiều nguồn về một dạng chung."""
import re
from datetime import datetime, timezone

# Các domain không phải là store của người bán.
NOT_A_STORE = {
    "facebook.com", "fb.com", "fb.me", "instagram.com", "m.me", "wa.me",
    "whatsapp.com", "messenger.com", "linktr.ee", "youtube.com", "youtu.be",
    "tiktok.com", "bit.ly", "amazon.com", "amzn.to", "apple.com", "google.com",
}
DOMAIN_RE = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)


def to_iso(value):
    """Nhận epoch (giây), 'YYYY-MM-DD' hoặc ISO datetime; trả về ISO UTC hoặc None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat(timespec="seconds")
    text = str(value).strip().replace("Z", "+00:00")
    # Meta đôi khi trả offset dạng +0000.
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def extract_domain(text):
    """Lấy domain store từ caption của ad, ví dụ 'RUBYBEAM.COM' -> 'rubybeam.com'."""
    if not text:
        return None
    m = DOMAIN_RE.search(text.strip())
    if not m:
        return None
    domain = m.group(1).lower()
    base = ".".join(domain.split(".")[-2:])
    if domain in NOT_A_STORE or base in NOT_A_STORE:
        return None
    return domain


def _first(value):
    """Lấy phần tử đầu khác rỗng của list, hoặc chính chuỗi."""
    if isinstance(value, (list, tuple)):
        for item in value:
            if item and str(item).strip():
                return str(item).strip()
        return ""
    return str(value).strip() if value else ""


def _first_title(raw):
    title = _first(raw.get("ad_creative_link_titles"))
    if title:
        return title
    # Một số nguồn nối các tiêu đề bằng ' | ' trong một chuỗi.
    joined = raw.get("ad_creative_link_title") or raw.get("title") or ""
    for part in str(joined).split(" | "):
        if part.strip():
            return part.strip()
    return ""


def _reach(raw):
    value = raw.get("eu_total_reach", raw.get("reach"))
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_ad(raw, source):
    """Trả về dict theo cột của bảng ads, hoặc None nếu thiếu id."""
    ad_id = raw.get("id") or raw.get("ad_archive_id")
    if not ad_id:
        return None
    caption = _first(raw.get("ad_creative_link_captions")) or raw.get("link_caption") or raw.get("link_url") or ""
    platforms = raw.get("publisher_platforms") or []
    if isinstance(platforms, str):
        platforms = [platforms]
    snapshot = raw.get("ad_snapshot_url") or ""
    if "access_token=" in snapshot or not snapshot.startswith("https://"):
        # Link từ API chính thức có kèm token; dùng link công khai để không lưu token.
        snapshot = f"https://www.facebook.com/ads/library/?id={ad_id}"
    return {
        "id": str(ad_id),
        "page_id": str(raw.get("page_id") or ""),
        "page_name": (raw.get("page_name") or "").strip(),
        "title": _first_title(raw),
        "body": _first(raw.get("ad_creative_bodies")) or (raw.get("body") or "").strip(),
        "domain": extract_domain(caption),
        "snapshot_url": snapshot,
        "currency": raw.get("currency") or "",
        "created_at": to_iso(raw.get("ad_creation_time")),
        "start_at": to_iso(raw.get("ad_delivery_start_time")),
        "stop_at": to_iso(raw.get("ad_delivery_stop_time")),
        "reach": _reach(raw),
        "platforms": ",".join(sorted(str(p).lower() for p in platforms)),
        "source": source,
    }
