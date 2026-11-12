"""Gọi Meta Ad Library API chính thức (endpoint ads_archive).

Với quảng cáo thương mại, API này chỉ trả về ads đã phân phối ở EU hoặc UK.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

FIELDS = [
    "id", "page_id", "page_name", "ad_creation_time", "ad_delivery_start_time",
    "ad_delivery_stop_time", "ad_creative_bodies", "ad_creative_link_titles",
    "ad_creative_link_captions", "ad_snapshot_url", "publisher_platforms",
    "eu_total_reach", "currency",
]

HINTS = {
    190: "Token hết hạn hoặc không hợp lệ. Tạo token mới rồi cập nhật file .env.",
    10: "Tài khoản chưa được cấp quyền Ad Library API. Xác minh danh tính tại facebook.com/ID và chấp nhận điều khoản tại facebook.com/ads/library/api.",
    200: "App chưa có quyền truy cập Ad Library API.",
    17: "Chạm giới hạn số lượt gọi. Chờ khoảng một giờ rồi chạy lại.",
    4: "Chạm giới hạn số lượt gọi. Chờ khoảng một giờ rồi chạy lại.",
    613: "Chạm giới hạn số lượt gọi. Chờ khoảng một giờ rồi chạy lại.",
}


RATE_LIMIT_CODES = {4, 17, 613}


class MetaApiError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Không in URL ra lỗi vì URL chứa token.
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", {})
        except (ValueError, UnicodeDecodeError):
            err = {}
        code = err.get("code")
        message = err.get("message") or f"HTTP {exc.code}"
        hint = HINTS.get(code)
        raise MetaApiError(f"Meta API lỗi {code or exc.code}: {message}" + (f"\n→ {hint}" if hint else ""),
                           code) from None
    except urllib.error.URLError as exc:
        raise MetaApiError(f"Không kết nối được tới Meta API: {exc.reason}") from None


def search(token, *, countries, keyword=None, page_ids=None, version="v24.0", page_size=50, max_pages=4,
           fetch=_get_json, budget=None):
    """Lấy ads đang chạy theo từ khóa hoặc theo danh sách page (tối đa 10).

    Trả về (danh sách ads, truncated). truncated là True khi còn trang kết quả chưa đọc.
    """
    params = {
        "ad_reached_countries": json.dumps(list(countries)),
        "ad_active_status": "ACTIVE",
        "ad_type": "ALL",
        "fields": ",".join(FIELDS),
        "limit": page_size,
        "access_token": token,
    }
    if page_ids:
        params["search_page_ids"] = ",".join(str(p) for p in page_ids)
    else:
        params["search_terms"] = keyword
    url = f"https://graph.facebook.com/{version}/ads_archive?" + urllib.parse.urlencode(params)
    ads = []
    for _ in range(max_pages):
        if budget is not None and not budget.take():
            return ads, True
        data = fetch(url)
        ads.extend(data.get("data", []))
        url = (data.get("paging") or {}).get("next")
        if not url:
            return ads, False
    return ads, True


def search_ads(token, keyword, country, *, version="v24.0", page_size=50, max_pages=4, fetch=_get_json):
    """Trả lần lượt từng ad đang chạy khớp từ khóa ở một quốc gia."""
    ads, _ = search(token, countries=[country], keyword=keyword, version=version, page_size=page_size,
                    max_pages=max_pages, fetch=fetch)
    yield from ads
