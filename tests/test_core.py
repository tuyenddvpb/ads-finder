import unittest

from adsfinder import db
from adsfinder.meta_api import search_ads
from adsfinder.normalize import extract_domain, normalize_ad, to_iso
from adsfinder.scoring import build_groups, score_group
from adsfinder.shopify import match_product

RUN1 = "2026-11-10T00:00:00+00:00"
RUN2 = "2026-11-11T00:00:00+00:00"


def ad(ad_id, title="Red Light Wrap", page="1", start="2026-10-01", **extra):
    return normalize_ad({"id": ad_id, "page_id": page, "page_name": "Shop", "ad_creative_link_titles": [title],
                         "ad_delivery_start_time": start, **extra}, "meta_api")


class NormalizeTest(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(to_iso(1794355200), "2026-11-11T00:00:00+00:00")
        self.assertEqual(to_iso("2026-11-11"), "2026-11-11T00:00:00+00:00")
        self.assertEqual(to_iso("2026-11-11T07:00:00+0700"), "2026-11-11T00:00:00+00:00")
        self.assertIsNone(to_iso("không phải ngày"))

    def test_domain(self):
        self.assertEqual(extract_domain("RUBYBEAM.COM"), "rubybeam.com")
        self.assertEqual(extract_domain("https://www.shop.example.co.uk/products/x"), "shop.example.co.uk")
        self.assertIsNone(extract_domain("fb.me"))
        self.assertIsNone(extract_domain("www.instagram.com"))
        self.assertIsNone(extract_domain("Shop now"))

    def test_official_and_connector_shapes(self):
        official = normalize_ad({"id": "1", "ad_creative_link_titles": ["A"], "ad_creative_bodies": ["B"],
                                 "ad_creative_link_captions": ["store.com"], "eu_total_reach": "1200",
                                 "ad_snapshot_url": "https://www.facebook.com/ads/archive/render_ad/?id=1&access_token=SECRET"},
                                "meta_api")
        self.assertEqual((official["title"], official["body"], official["domain"], official["reach"]),
                         ("A", "B", "store.com", 1200))
        self.assertNotIn("SECRET", official["snapshot_url"])
        connector = normalize_ad({"id": 2, "ad_creative_link_title": "X | X | Y", "ad_delivery_start_time": 1794355200},
                                 "import")
        self.assertEqual(connector["title"], "X")
        self.assertIsNone(normalize_ad({"page_name": "no id"}, "import"))


class ScoreTest(unittest.TestCase):
    def test_bounds_and_order(self):
        self.assertEqual(score_group(0, 1, 1, None)[0], 0)
        self.assertEqual(score_group(90, 12, 6, 2_000_000)[0], 100)
        self.assertGreater(score_group(60, 1, 0, None)[0], score_group(5, 1, 1, None)[0])
        self.assertGreater(score_group(5, 9, 9, None)[0], score_group(5, 2, 2, None)[0])

    def test_missing_reach_is_renormalised(self):
        score, parts = score_group(45, 10, 5, None)
        self.assertEqual(score, 100)
        self.assertNotIn("reach", parts)


class GroupTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_grouping_and_active_status(self):
        db.save_ads(self.conn, [ad("1"), ad("2"), ad("3", title="Other")], "kw", "DE", RUN1)
        # Lượt sau: ad 2 không còn xuất hiện, ad 4 mới bật.
        db.save_ads(self.conn, [ad("1"), ad("3", title="Other"), ad("4", start="2026-11-09")], "kw", "DE", RUN2)
        groups = {g["title"]: g for g in build_groups(self.conn)}
        wrap = groups["Red Light Wrap"]
        self.assertEqual((wrap["n_total"], wrap["n_active"], wrap["new_7d"]), (3, 2, 1))
        self.assertEqual(wrap["max_days"], 41)
        self.assertEqual(wrap["page_active_ads"], 3)
        self.assertEqual(wrap["countries"], ["DE"])
        self.assertEqual(wrap["history"], [{"day": "2026-11-10", "ads": 2, "reach": None},
                                           {"day": "2026-11-11", "ads": 2, "reach": None}])

    def test_history_sums_reach_per_day(self):
        db.save_ads(self.conn, [ad("1", eu_total_reach=1000), ad("2", eu_total_reach=500)], "kw", "DE", RUN1)
        db.save_ads(self.conn, [ad("1", eu_total_reach=1000), ad("2", eu_total_reach=500)], "kw", "FR", RUN1)
        db.save_ads(self.conn, [ad("1", eu_total_reach=1800)], "kw", "DE", RUN2)
        group = build_groups(self.conn)[0]
        self.assertEqual(group["history"], [{"day": "2026-11-10", "ads": 2, "reach": 1500},
                                            {"day": "2026-11-11", "ads": 1, "reach": 1800}])
        self.assertEqual(group["key"], "1|red light wrap")

    def test_stopped_group_scores_zero(self):
        db.save_ads(self.conn, [ad("1")], "kw", "DE", RUN1)
        db.save_ads(self.conn, [], "kw", "DE", RUN2)
        group = build_groups(self.conn)[0]
        self.assertEqual((group["n_active"], group["score"]), (0, 0))

    def test_exclude_terms_and_store_match(self):
        db.save_ads(self.conn, [ad("1", title="Red Light Waist Wrap", ad_creative_link_captions=["store.com"]),
                                ad("2", title="Med Spa Special", page="2")], "kw", "DE", RUN1)
        db.save_store(self.conn, "store.com", {"is_shopify": True, "product_count": 1, "products": [
            {"title": "Red Light Waist Wrap Pro", "handle": "wrap", "price": "59.00", "created_at": None}]}, RUN1)
        groups = {g["title"]: g for g in build_groups(self.conn, ["med spa"])}
        self.assertTrue(groups["Med Spa Special"]["excluded"])
        self.assertFalse(groups["Red Light Waist Wrap"]["excluded"])
        spacey = {g["title"]: g for g in build_groups(self.conn, ["spa", "wrap pro"])}
        self.assertTrue(spacey["Med Spa Special"]["excluded"])
        self.assertFalse(spacey["Red Light Waist Wrap"]["excluded"])
        self.assertEqual(groups["Red Light Waist Wrap"]["store"]["product"]["url"], "https://store.com/products/wrap")


class MiscTest(unittest.TestCase):
    def test_match_product_threshold(self):
        products = [{"title": "Garden Hose"}, {"title": "LED Face Mask"}]
        self.assertEqual(match_product("Red Light LED Face Mask", products)["title"], "LED Face Mask")
        self.assertIsNone(match_product("Posture Corrector", products))

    def test_search_follows_paging_up_to_max_pages(self):
        pages = [{"data": [{"id": "1"}], "paging": {"next": "next-1"}},
                 {"data": [{"id": "2"}], "paging": {"next": "next-2"}},
                 {"data": [{"id": "3"}]}]
        calls = []

        def fetch(url):
            calls.append(url)
            return pages[len(calls) - 1]

        got = list(search_ads("TOKEN", "kw", "DE", max_pages=2, fetch=fetch))
        self.assertEqual([a["id"] for a in got], ["1", "2"])
        self.assertIn("ad_reached_countries=%5B%22DE%22%5D", calls[0])
        self.assertEqual(calls[1], "next-1")



class SiteTest(unittest.TestCase):
    def test_build_site_copies_only_captured_images(self):
        import json
        import tempfile
        from pathlib import Path

        from adsfinder.server import build_site, images_dir

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "data" / "ads.db")
            conn = db.connect(db_path)
            db.save_ads(conn, [ad("1"), ad("2", title="Other")], "kw", "DE", RUN1)
            images_dir(db_path).mkdir()
            (images_dir(db_path) / "1.jpg").write_bytes(b"jpg")
            (images_dir(db_path) / "999.jpg").write_bytes(b"orphan")
            db.save_media(conn, "1", "1.jpg", True, RUN1)
            out = Path(tmp) / "site"
            self.assertEqual(build_site(conn, db_path, [], out), (2, 1))
            conn.close()
            self.assertEqual([p.name for p in (out / "images").iterdir()], ["1.jpg"])
            groups = {g["title"]: g for g in json.loads((out / "data.json").read_text())["groups"]}
            self.assertEqual((groups["Red Light Wrap"]["image"], groups["Red Light Wrap"]["is_video"]), ("1.jpg", True))
            self.assertIsNone(groups["Other"]["image"])
            self.assertTrue((out / "index.html").exists())


class FakeMeta:
    """Meta API giả: trả ads theo search_terms hoặc search_page_ids, ghi lại các lượt gọi."""

    def __init__(self, by_term=None, by_page=None, fail_code=None):
        self.by_term, self.by_page, self.fail_code, self.calls = by_term or {}, by_page or {}, fail_code, []

    def __call__(self, url):
        from urllib.parse import parse_qs, urlparse

        from adsfinder.meta_api import MetaApiError
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.calls.append(q)
        if self.fail_code:
            raise MetaApiError("lỗi giả", self.fail_code)
        if "search_page_ids" in q:
            return {"data": [a for pid in q["search_page_ids"].split(",") for a in self.by_page.get(pid, [])]}
        return {"data": self.by_term.get(q["search_terms"], [])}


def raw(ad_id, title, page, domain=None, start="2026-09-01"):
    return {"id": ad_id, "page_id": page, "page_name": "Page " + page, "ad_creative_link_titles": [title],
            "ad_creative_link_captions": [domain] if domain else [], "ad_delivery_start_time": start}


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        from adsfinder.config import DEFAULTS
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.cfg = {**DEFAULTS, "countries": ["DE", "FR"], "max_pages_per_query": 1}

    def run_day(self, fake, run_at, **cfg):
        from adsfinder import discovery
        return discovery.run(self.conn, {**self.cfg, **cfg}, "TOKEN", run_at, fetch=fake, log=lambda *_: None)

    def test_product_term(self):
        from adsfinder.discovery import product_term
        self.assertEqual(product_term("30% OFF — Red Light Waist Wrap Pro"), "red light waist")
        self.assertEqual(product_term("Kostenloser Versand für das Nackenkissen Deluxe"), "kostenloser versand nackenkissen")
        self.assertIsNone(product_term("50% OFF Sale"))

    def test_phrases_rotate_within_budget(self):
        fake = FakeMeta()
        stats = self.run_day(fake, RUN1, max_calls_per_run=4)
        self.assertEqual(stats["queries"], 4)
        first = [(c["search_terms"], c["ad_reached_countries"]) for c in fake.calls]
        self.assertEqual(first[:2], [("kostenloser versand", '["DE"]'), ("livraison gratuite", '["FR"]')])
        fake2 = FakeMeta()
        self.run_day(fake2, RUN2, max_calls_per_run=4)
        second = [(c["search_terms"], c["ad_reached_countries"]) for c in fake2.calls]
        self.assertFalse(set(first) & set(second), "lượt sau phải chạy các cụm từ chưa chạy")

    def test_shopify_pages_get_tracked_and_keywords_expand(self):
        wrap = raw("1", "Red Light Waist Wrap", "77", "store.com")
        fake = FakeMeta(by_term={"kostenloser versand": [wrap, raw("2", "Big Brand Shoe", "88", "big.com")]})
        self.run_day(fake, RUN1)
        db.save_store(self.conn, "store.com", {"is_shopify": True, "product_count": 12, "products": [
            {"title": "Red Light Waist Wrap", "handle": "wrap", "price": "59", "created_at": None}]}, RUN1)
        db.save_store(self.conn, "big.com", {"is_shopify": True, "product_count": 250, "products": []}, RUN1)

        # Ngày 2: page 77 được theo dõi và lộ ra một sản phẩm không khớp cụm từ nào.
        fake2 = FakeMeta(by_page={"77": [wrap, raw("3", "Infrared Knee Pad", "77", "store.com", start="2026-11-09")]})
        stats = self.run_day(fake2, RUN2)
        self.assertEqual(stats["tracked_pages"], 1)
        self.assertEqual(stats["auto_keywords_added"], ["red light waist"])
        page_calls = [c for c in fake2.calls if "search_page_ids" in c]
        self.assertEqual([(c["search_page_ids"], c["ad_reached_countries"]) for c in page_calls], [("77", '["DE", "FR"]')])
        self.assertIn("red light waist", [c.get("search_terms") for c in fake2.calls])
        groups = {g["title"]: g for g in build_groups(self.conn)}
        knee = groups["Infrared Knee Pad"]
        self.assertEqual((knee["n_active"], knee["countries"], knee["keywords"], knee["tracked_page"]), (1, ["EU"], [], True))
        self.assertEqual((knee["niche"], groups["Big Brand Shoe"]["big_brand"], knee["big_brand"]), ("Sức khỏe", True, False))

        # Ngày 3: page không còn chạy ad "Knee Pad" nữa thì ad đó chuyển sang đã dừng.
        self.run_day(FakeMeta(by_page={"77": [wrap]}), "2026-11-12T00:00:00+00:00")
        groups = {g["title"]: g for g in build_groups(self.conn)}
        self.assertEqual((groups["Infrared Knee Pad"]["n_active"], groups["Red Light Waist Wrap"]["n_active"]), (0, 1))

    def test_rate_limit_stops_early_and_bad_token_raises(self):
        from adsfinder.meta_api import MetaApiError
        fake = FakeMeta(fail_code=613)
        self.assertEqual(self.run_day(fake, RUN1)["queries"], 0)
        self.assertEqual(len(fake.calls), 1)
        bad = FakeMeta(fail_code=190)
        with self.assertRaises(MetaApiError):
            self.run_day(bad, RUN1)
        self.assertEqual(len(bad.calls), 3)

    def test_truncated_page_batch_does_not_mark_pages_stopped(self):
        from adsfinder.meta_api import search
        pages = [{"data": [{"id": "1"}], "paging": {"next": "n"}}]
        ads, truncated = search("T", countries=["DE"], page_ids=["77", "78"], max_pages=1, fetch=lambda url: pages[0])
        self.assertEqual((len(ads), truncated), (1, True))


if __name__ == "__main__":
    unittest.main()
