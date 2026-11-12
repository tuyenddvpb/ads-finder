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
   python -m adsfinder discover   # tự tìm ads, không cần từ khóa (xem mục "Tự tìm ads")
   python -m adsfinder enrich     # kiểm tra store nào là Shopify
   python -m adsfinder capture    # chụp ảnh ad (tùy chọn, xem mục "Ảnh ad")
   python -m adsfinder serve      # mở giao diện web
   python -m adsfinder export     # xuất data/ranking.csv
   ```

Chạy `discover` mỗi ngày một lần. Tool so sánh các lượt quét để biết ad nào còn sống và page nào đang bật thêm ads, nên dữ liệu càng nhiều ngày thì điểm càng đáng tin.

Đặt lịch trên macOS/Linux (9 giờ sáng hằng ngày):

```
0 9 * * * cd /đường/dẫn/ads-finder && python -m adsfinder discover && python -m adsfinder enrich
```

Trên Windows dùng Task Scheduler với cùng hai lệnh.

## Tự tìm ads

API của Meta bắt buộc mỗi lượt tìm phải có từ khóa hoặc ID page. `discover` tự tạo các truy vấn đó từ ba nguồn và xoay vòng chúng qua các ngày:

1. **Cụm từ bán hàng** dùng chung cho mọi ngách ("free shipping", "kostenloser versand", "livraison gratuite"...), theo ngôn ngữ từng nước trong `countries`. Danh sách nằm ở đầu file `adsfinder/discovery.py`.
2. **Page đã biết**: page nào dẫn về một store Shopify cỡ nhỏ thì được theo dõi, và mỗi lượt tool lấy toàn bộ ads của page đó. Cần `enrich` chạy trước một lượt để biết store nào là Shopify.
3. **Từ khóa tự sinh**: cụm 2–3 từ rút từ tên sản phẩm của các ads điểm cao, dùng làm từ khóa cho lượt sau.

Từ khóa trong `keywords` của config (nếu có) luôn được chạy trước. Lệnh `collect` cũ vẫn dùng được khi chỉ muốn tìm theo từ khóa tự nhập.

| Cấu hình | Mặc định | Ý nghĩa |
|---|---|---|
| `max_calls_per_run` | 120 | Số lượt gọi API tối đa mỗi lần chạy; phần chưa chạy để lượt sau |
| `max_tracked_pages` | 300 | Số page Shopify được theo dõi |
| `auto_keywords_per_run` | 10 | Số từ khóa tự sinh thêm mỗi lượt |
| `max_auto_keywords` | 300 | Tổng số từ khóa tự sinh |
| `auto_keyword_min_score` | 30 | Điểm tối thiểu của sản phẩm để rút từ khóa |

Kết quả tìm theo page hoặc theo từ khóa tự sinh gộp mọi nước trong config, nên thị trường hiển thị là `EU`.

Mỗi sản phẩm được gắn một **ngách** (sức khỏe, làm đẹp, thú cưng...) theo từ trong tiêu đề, và bị đánh dấu **thương hiệu lớn** khi page chạy hơn 100 ads hoặc store có từ 250 sản phẩm. Thương hiệu lớn bị ẩn mặc định trên giao diện. Danh sách từ của từng ngách và hai ngưỡng này nằm ở đầu file `adsfinder/scoring.py`.

## Ảnh ad

`capture` mở trang xem trước của từng ad bằng trình duyệt không giao diện và chụp lại. Với ad video, ảnh là khung hình hiển thị của video và được gắn nhãn "▶ video". Mỗi lượt chỉ chụp một ad (ad chạy lâu nhất) cho các sản phẩm điểm cao nhất; số lượng đặt ở `images_top_groups` trong config.

Phần này cần cài thêm Playwright:

```bash
pip install playwright
playwright install chromium
```

## Chạy tự động miễn phí trên GitHub

File `.github/workflows/daily-scan.yml` chạy `discover`, `enrich`, `capture` mỗi ngày trên GitHub Actions rồi đăng trang web lên GitHub Pages. Repo công khai thì cả hai đều miễn phí.

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

## Giao diện

- **Lưới thẻ** (mặc định) hoặc **bảng**: mỗi thẻ là một sản phẩm, có ảnh ad, điểm, số ads, số ngày chạy và reach EU.
- **Bộ lọc**: từ khóa, thị trường, số ngày chạy, số ads, reach EU, store Shopify, có ảnh, video. Sắp xếp theo điểm, ngày chạy, số ads, reach, số ads mới bật, hoặc mới xuất hiện.
- **Chi tiết**: bấm vào thẻ để xem cách tính điểm, biểu đồ số ads và reach theo ngày, nội dung quảng cáo, store và link từng ad.
- **Trang theo page**: bấm tên page để xem mọi sản phẩm page đó đang chạy, kèm sản phẩm mới nhất của store nếu là Shopify.
- **Lưu sản phẩm**: bấm ☆ để lưu. Danh sách lưu nằm trong trình duyệt của bạn (localStorage), nên không đồng bộ giữa các máy.

Biểu đồ theo ngày cần ít nhất 2 lượt quét ở 2 ngày khác nhau.

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
