"""Dòng lệnh: python -m adsfinder <lệnh>."""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .config import load_config, load_env
from .meta_api import MetaApiError, search_ads
from .normalize import normalize_ad, to_iso
from .scoring import build_groups
from .capture import CaptureUnavailable, capture_ads
from .server import build_site, images_dir, serve
from .shopify import check_store

SAMPLE = Path(__file__).parent.parent / "samples" / "red-light-therapy-2026-11-11.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_collect(cfg, args):
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        sys.exit("Thiếu META_ACCESS_TOKEN. Sao chép .env.example thành .env rồi điền token.")
    keywords = args.keyword or cfg["keywords"]
    countries = args.country or cfg["countries"]
    if not keywords:
        sys.exit("Chưa có từ khóa. Thêm vào config.json hoặc dùng --keyword.")
    conn = db.connect(cfg["db_path"])
    run_at = now_iso()
    failed = 0
    for keyword in keywords:
        for country in countries:
            try:
                raw = list(search_ads(token, keyword, country, version=cfg["api_version"],
                                      page_size=cfg["page_size"], max_pages=cfg["max_pages_per_query"]))
            except MetaApiError as exc:
                failed += 1
                print(f"[lỗi] '{keyword}' / {country}: {exc}", file=sys.stderr)
                continue
            ads = [a for a in (normalize_ad(r, "meta_api") for r in raw) if a]
            new = db.save_ads(conn, ads, keyword, country, run_at)
            print(f"'{keyword}' / {country}: {len(ads)} ads, {new} mới")
    conn.close()
    if failed:
        sys.exit(f"{failed} truy vấn lỗi.")


def cmd_import(cfg, args):
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        payload = {"ads": payload}
    keyword = args.keyword or payload.get("keyword")
    countries = args.country or payload.get("countries") or ([payload["country"]] if payload.get("country") else [])
    if not keyword or not countries:
        sys.exit("File không ghi từ khóa/quốc gia. Thêm --keyword và --country.")
    run_at = to_iso(payload.get("collected_at")) or now_iso()
    source = payload.get("source") or "import"
    ads = [a for a in (normalize_ad(r, source) for r in payload.get("ads", [])) if a]
    conn = db.connect(cfg["db_path"])
    for country in countries:
        new = db.save_ads(conn, ads, keyword, country, run_at)
    conn.close()
    print(f"Đã nhập {len(ads)} ads cho '{keyword}' / {','.join(countries)} ({new} mới).")


def cmd_enrich(cfg, args):
    conn = db.connect(cfg["db_path"])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.max_age_days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT DISTINCT a.domain FROM ads a LEFT JOIN stores s ON s.domain = a.domain "
        "WHERE a.domain IS NOT NULL AND (s.domain IS NULL OR s.checked_at < ?) ORDER BY a.domain",
        (cutoff,),
    ).fetchall()
    domains = [r["domain"] for r in rows][: args.limit]
    if not domains:
        print("Không có domain nào cần kiểm tra.")
    for domain in domains:
        info = check_store(domain)
        db.save_store(conn, domain, info, now_iso())
        label = f"Shopify, {info['product_count']} sản phẩm" if info["is_shopify"] else "không phải Shopify"
        print(f"{domain}: {label}")
        time.sleep(args.delay)
    conn.close()


def cmd_export(cfg, args):
    conn = db.connect(cfg["db_path"])
    groups = [g for g in build_groups(conn, cfg["exclude_terms"]) if g["n_active"] and not g["excluded"]]
    conn.close()
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["score", "title", "page", "active_ads", "days_running", "new_7d", "eu_reach",
                         "countries", "keywords", "domain", "shopify", "product", "price", "example_ad"])
        for g in groups:
            store = g["store"] or {}
            product = store.get("product") or {}
            writer.writerow([g["score"], g["title"], g["page_name"], g["n_active"], g["max_days"], g["new_7d"],
                             g["reach"] or "", " ".join(g["countries"]), "; ".join(g["keywords"]),
                             g["domain"] or "", "yes" if store.get("is_shopify") else "",
                             product.get("title", ""), product.get("price", ""), g["ads"][0]["snapshot_url"]])
    print(f"Đã ghi {len(groups)} dòng vào {args.out}")


def cmd_capture(cfg, args):
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        sys.exit("Thiếu META_ACCESS_TOKEN. Sao chép .env.example thành .env rồi điền token.")
    conn = db.connect(cfg["db_path"])
    groups = [g for g in build_groups(conn, cfg["exclude_terms"]) if g["n_active"] and not g["excluded"]]
    limit = args.limit or cfg["images_top_groups"]
    # Mỗi sản phẩm chụp một ad: ad đang chạy lâu nhất.
    wanted = [next(a for a in g["ads"] if a["active"])["id"] for g in groups[:limit] if not g["image"]]
    if not wanted:
        print("Không có ad nào cần chụp.")
        return
    try:
        done = capture_ads(wanted, token, images_dir(cfg["db_path"]),
                           executable_path=os.environ.get("CHROMIUM_PATH"),
                           **({"render_url": args.render_url} if args.render_url else {}))
    except CaptureUnavailable as exc:
        sys.exit(str(exc))
    for ad_id, info in done.items():
        db.save_media(conn, ad_id, info["file"], info["is_video"], now_iso())
    conn.close()
    print(f"Đã chụp {len(done)}/{len(wanted)} ads.")
    if not done:
        # Chỉ cảnh báo: thiếu ảnh không nên làm hỏng cả lượt quét hằng ngày.
        print("Không chụp được ad nào. Nếu lặp lại nhiều ngày, kiểm tra token.", file=sys.stderr)


def cmd_build(cfg, args):
    conn = db.connect(cfg["db_path"])
    n_groups, n_images = build_site(conn, cfg["db_path"], cfg["exclude_terms"], args.out)
    conn.close()
    print(f"Đã xuất {n_groups} sản phẩm và {n_images} ảnh vào {args.out}/")


def cmd_serve(cfg, args):
    serve(cfg["db_path"], cfg["exclude_terms"], args.port or cfg["port"])


def cmd_demo(cfg, args):
    cfg = {**cfg, "db_path": "data/demo.db"}
    Path(cfg["db_path"]).unlink(missing_ok=True)
    cmd_import(cfg, argparse.Namespace(file=str(SAMPLE), keyword=None, country=None))
    for extra in sorted(SAMPLE.parent.glob("*.json")):
        if extra != SAMPLE:
            cmd_import(cfg, argparse.Namespace(file=str(extra), keyword=None, country=None))
    cmd_serve(cfg, args)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="adsfinder", description=__doc__)
    parser.add_argument("--config", default="config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="Lấy ads đang chạy từ Meta Ad Library API (EU/UK)")
    p.add_argument("--keyword", action="append", help="Ghi đè từ khóa trong config; dùng nhiều lần được")
    p.add_argument("--country", action="append", help="Mã quốc gia ISO-2; dùng nhiều lần được")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("import", help="Nhập ads từ file JSON (dùng cho nguồn US hoặc bên thứ ba)")
    p.add_argument("file")
    p.add_argument("--keyword")
    p.add_argument("--country", action="append")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("enrich", help="Kiểm tra domain trong ads có phải store Shopify không")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--delay", type=float, default=1.0, help="Số giây nghỉ giữa hai store")
    p.add_argument("--max-age-days", type=int, default=7, help="Kiểm tra lại store sau số ngày này")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("export", help="Xuất bảng xếp hạng ra CSV")
    p.add_argument("--out", default="data/ranking.csv")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("capture", help="Chụp ảnh ad cho các sản phẩm điểm cao nhất (cần Playwright)")
    p.add_argument("--limit", type=int, help="Số sản phẩm cần có ảnh; mặc định lấy từ config")
    p.add_argument("--render-url", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("build", help="Xuất trang web tĩnh để đưa lên hosting")
    p.add_argument("--out", default="site")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("serve", help="Mở giao diện web")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="Mở giao diện web với dữ liệu mẫu")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    load_env()
    args.func(load_config(args.config), args)


if __name__ == "__main__":
    main()
