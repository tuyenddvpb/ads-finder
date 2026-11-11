"""Chụp ảnh ad từ trang xem trước của Meta (kể cả khung hình của video).

Cần cài thêm: pip install playwright && playwright install chromium
"""
import urllib.parse
from pathlib import Path

RENDER_URL = "https://www.facebook.com/ads/archive/render_ad/?id={id}&access_token={token}"
MIN_MEDIA_WIDTH = 150  # nhỏ hơn mức này coi như logo/icon, không phải nội dung ad

# Tìm ảnh hoặc video đủ lớn; trả về null nếu trang không có nội dung ad (ví dụ trang đăng nhập).
FIND_MEDIA_JS = """
(minWidth) => {
  const big = (el) => el.getBoundingClientRect().width >= minWidth;
  const video = [...document.querySelectorAll('video')].find(big);
  const image = [...document.querySelectorAll('img')].find((el) => big(el) && el.naturalWidth >= minWidth);
  if (!video && !image) return null;
  return { is_video: Boolean(video) };
}
"""


class CaptureUnavailable(Exception):
    pass


def capture_ads(ad_ids, token, out_dir, *, render_url=RENDER_URL, executable_path=None, timeout_ms=30000, log=print):
    """Chụp từng ad vào out_dir/<id>.jpg. Trả về {ad_id: {'file', 'is_video'}} cho ad chụp được."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise CaptureUnavailable(
            "Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium") from None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable_path or None)
        context = browser.new_context(viewport={"width": 520, "height": 760}, device_scale_factor=1.5, locale="en-US")
        page = context.new_page()
        for ad_id in ad_ids:
            url = render_url.format(id=urllib.parse.quote(str(ad_id)), token=urllib.parse.quote(token))
            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
                try:
                    page.wait_for_function(FIND_MEDIA_JS, arg=MIN_MEDIA_WIDTH, timeout=8000)
                except PlaywrightError:
                    pass
                media = page.evaluate(FIND_MEDIA_JS, MIN_MEDIA_WIDTH)
                if not media:
                    log(f"[bỏ qua] {ad_id}: trang không có ảnh hoặc video của ad")
                    continue
                name = f"{ad_id}.jpg"
                page.screenshot(path=str(out_dir / name), type="jpeg", quality=78)
                done[str(ad_id)] = {"file": name, "is_video": media["is_video"]}
            except PlaywrightError as exc:
                # Không in URL vì URL chứa token.
                log(f"[lỗi] {ad_id}: {str(exc).splitlines()[0].replace(token, '***')[:160]}")
        browser.close()
    return done
