# Ads Finder

Tìm quảng cáo Meta đang được scale để chọn sản phẩm dropship. Chạy trên máy local, chỉ cần Python 3.10+, không phải cài thêm thư viện nào.

## Chạy thử với dữ liệu mẫu

```bash
git clone https://github.com/tuyenddvpb/ads-finder.git
cd ads-finder
python -m adsfinder demo
```

Mở http://127.0.0.1:8765. Dữ liệu mẫu là 50 ads thật cho từ khóa "red light therapy" (US và DE/FR/NL), lấy ngày 11/11/2026.

## Dùng thật

1. Sao chép cấu hình rồi sửa từ khóa và quốc gia:
   ```bash
   cp config.example.json config.json
   cp .env.example .env
   ```
2. Lấy token Meta và điền vào `.env` (xem mục dưới).
3. Chạy:
   ```bash
   python -m adsfinder collect    # lấy ads đang chạy
   python -m adsfinder enrich     # kiểm tra store nào là Shopify
   python -m adsfinder capture    # chụp ảnh ad (tùy chọn, xem mục "Ảnh ad")
   python -m adsfinder serve      # mở giao diện web
   python -m adsfinder export     # xuất data/ranking.csv
   ```

Chạy `collect` mỗi ngày một lần. Tool so sánh các lượt quét để biết ad nào còn sống và page nào đang bật thêm ads, nên dữ liệu càng nhiều ngày thì điểm càng đáng tin.

Đặt lịch trên macOS/Linux (9 giờ sáng hằng ngày):

```
0 9 * * * cd /đường/dẫn/ads-finder && python -m adsfinder collect && python -m adsfinder enrich
```

Trên Windows dùng Task Scheduler với cùng hai lệnh.

## Ảnh ad

`capture` mở trang xem trước của từng ad bằng trình duyệt không giao diện và chụp lại. Với ad video, ảnh là khung hình hiển thị của video và được gắn nhãn "▶ video". Mỗi lượt chỉ chụp một ad (ad chạy lâu nhất) cho các sản phẩm điểm cao nhất; số lượng đặt ở `images_top_groups` trong config.

Phần này cần cài thêm Playwright:

```bash
pip install playwright
playwright install chromium
```

## Chạy tự động miễn phí trên GitHub

File `.github/workflows/daily-scan.yml` chạy `collect`, `enrich`, `capture` mỗi ngày trên GitHub Actions rồi đăng trang web lên GitHub Pages. Repo công khai thì cả hai đều miễn phí.

Cài đặt một lần trong repo này:

1. **Settings → Secrets and variables → Actions → New repository secret**: tên `META_ACCESS_TOKEN`, giá trị là token Meta.
2. **Settings → Pages → Source**: chọn **GitHub Actions**.
3. **Actions → Daily ads scan → Run workflow** để chạy lượt đầu. Sau đó workflow tự chạy lúc 09:17 hằng ngày (giờ Việt Nam).

Trang kết quả nằm ở https://tuyenddvpb.github.io/ads-finder/.

Dữ liệu giữa các lượt được lưu ở nhánh `ads-data`. Để đổi từ khóa, commit một file `config.json` vào repo (bỏ dòng `config.json` trong `.gitignore`).

Lưu ý: trang GitHub Pages của repo công khai ai có link cũng xem được. Token dài hạn của Meta hết hạn sau khoảng 60 ngày; khi đó workflow báo lỗi qua email và bạn cần cập nhật secret.

## Lấy token Meta

1. Xác minh danh tính tại https://www.facebook.com/ID (Meta duyệt trong vài ngày).
2. Tạo app tại https://developers.facebook.com/apps.
3. Chấp nhận điều khoản tại https://www.facebook.com/ads/library/api.
4. Tạo token trong Graph API Explorer, đổi sang token dài hạn (60 ngày), rồi điền vào `.env`.

## Thị trường

| Thị trường | Nguồn | Ghi chú |
|---|---|---|
| EU, UK | `collect` (API chính thức) | Có nội dung ad, domain và reach EU |
| US | `import` từ file JSON | API chính thức không trả ads thương mại chỉ chạy ở US |

Ads của store US có chạy sang EU vẫn xuất hiện qua `collect`.

Với US, xuất dữ liệu từ một dịch vụ bên thứ ba ra JSON rồi nhập:

```bash
python -m adsfinder import file.json --keyword "heated gloves" --country US
```

File là một danh sách ads, hoặc `{"keyword", "countries", "collected_at", "ads": [...]}`. Mỗi ad cần `id`; các trường nhận được: `page_id`, `page_name`, `ad_creative_link_titles` (hoặc `title`), `ad_creative_bodies` (hoặc `body`), `ad_creative_link_captions` (hoặc `link_url`), `ad_delivery_start_time`, `ad_delivery_stop_time`, `eu_total_reach`, `currency`. Xem ví dụ trong `samples/`.

## Cách chấm điểm

Meta không công bố chi tiêu, nên điểm (0–100) dựa trên tín hiệu gián tiếp. Các ads cùng page và cùng tiêu đề được gom thành một sản phẩm.

| Tín hiệu | Trọng số | Trọn điểm khi |
|---|---|---|
| Chạy lâu | 40 | ad lâu nhất chạy từ 45 ngày |
| Nhiều biến thể | 30 | từ 10 ads đang chạy cho cùng sản phẩm |
| Reach EU | 20 | tổng reach từ 1.000.000 (thang log, bắt đầu từ 1.000) |
| Đang bật thêm | 10 | 5 ads mới trong 7 ngày, với sản phẩm đã chạy từ 14 ngày |

Nguồn nào không có reach thì bỏ tín hiệu đó và chia lại trọng số cho đủ 100. Sửa trọng số ở đầu file `adsfinder/scoring.py`.

## Giới hạn cần biết

- Một ad bị coi là "đã dừng" khi nó không còn xuất hiện trong lượt quét mới nhất. Nếu từ khóa có nhiều ads hơn `page_size × max_pages_per_query`, ad nằm ngoài phần đã quét cũng bị coi là dừng. Tăng `max_pages_per_query` nếu gặp.
- `exclude_terms` trong config lọc nhiễu (spa, phòng khám, bất động sản) theo nguyên từ. Mục bị lọc vẫn xem được bằng ô "Hiện mục bị lọc nhiễu".
- `enrich` gọi `/products.json` của từng store, mỗi store một lần mỗi 7 ngày.
- Token nằm trong `.env`, dữ liệu nằm trong `data/`; cả hai đã được `.gitignore`.

## Kiểm thử

```bash
python -m unittest discover -s tests
```
