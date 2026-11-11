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


if __name__ == "__main__":
    unittest.main()
