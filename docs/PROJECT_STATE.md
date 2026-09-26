# Auto_veo3 — PROJECT STATE

Cập nhật: 2026-09-19 (đêm, sau khi cấu hình `.env` VPS). Nguồn sự thật về tiến độ; mọi mốc ghi kèm bằng chứng. Không ghi bí mật vào đây.

## Tóm tắt một dòng
Phần máy nhà **xong và đã kiểm chứng THẬT**: G-Labs thật, Gateway thật, tunnel `veo.d100radar.com`, tải zip qua Cloudflare. Module thoai-dash **đã push lên GitHub** (`42a32dc`), chờ VPS deploy + cấu hình `.env` VPS + webhook SePay để đăng nhập/mua gói chạy thật.

## Bảng mốc

| Mốc | Trạng thái | Bằng chứng |
|---|---|---|
| M0.1 API Key G-Labs | **PASS** | webhook `:8765` OK; khóa dính ký tự lạ từng gây 401 → Gateway + script cài đã tự làm sạch |
| M0.2 5 mode qua G-Labs thật | **PASS 5/5** | Bạn chạy `test_m0_modes.ps1` + `test_m0_modes2.ps1`; tôi kiểm lại: ảnh, `text_to_video`, `start_image`, `start_end_image` (khung đầu khối gỗ phẳng → khung cuối nghiêng 45°, mượt), `components` (robot giữ nguyên thiết kế so với ảnh gốc). Video H.264 1280×720 24fps có âm thanh AAC |
| M0.3 số tài khoản/ULTRA/luồng | 1 phần | `video_length=6` bị bỏ qua (luôn 8 s) → tài khoản không có độ dài 4/6 s. 3 video song song chạy được |
| M0.4 Cloudflare Tunnel | **PASS** | `https://veo.d100radar.com/v1/health` → 200, `mock=false`, `glabs=up`, `glabs_key_set=true` |
| M0.5 tải file lớn qua tunnel | **PASS** | zip 96,7 MB, 5,2 s (18,7 MB/s), SHA256 khớp, Cloudflare `cf-cache-status: HIT`. Còn lưu ý điều khoản băng thông Cloudflare cho file lớn (chưa kiểm chứng) |
| M0.6 SePay/QR | D100 đã bật | webhook Veo riêng chưa cấu hình |
| M1 Gateway | **PASS (thật)** | 11 test + 5 mode thật qua Gateway + video thật qua tunnel công khai; đồng thời 2 video ~70 s; **1080p 9:16 → 1080×1920 thật**; job trùng khóa chống-trùng chạy đúng |
| M2–M4 App | **PASS** | 9 test toàn tuyến (có test âm thanh khi nối video), giao diện đối chiếu ảnh Veo3 Go |
| B1–B2 module thoai-dash | **PASS** | regression 27/27 trên Postgres/Redis thật (đúng requirements.txt); test trùng đồng thời, trần đơn chờ |
| B3 trang `/veo3` | PASS local | nginx thật phục vụ 4 trang |
| **Push lên GitHub** | **XONG** | `b24c754..42a32dc` (2 commit, chỉ file Veo) |
| **Deploy VPS** | **XONG** | Auto-Sync tự kéo ~9 phút sau push: `/api/veo/plans` 200 (3 gói, Pro 199.000đ, Ultra 399.000đ, Trial 3 video), `/veo3/` + `device.html` + `latest.json` 200, D100 vẫn 200 |
| **`.env` VPS (VEO_*)** | **XONG** | SSH bằng khóa deploy theo yêu cầu: backup `.env.bak.1789787292`, thêm đúng 4 dòng (phần cũ giữ nguyên từng byte), recreate backend/worker/beat; `/api/veo/public-key` → 200 EdDSA, khớp khóa Gateway. Khóa webhook đã ĐỔI 1 lần vì lộ trong log phiên (khóa cũ → 401). Log: `ops/reports/Bao_loi.md` |
| **Thanh toán thật + kích hoạt TỰ ĐỘNG (2.000đ ×2)** | **PASS** | đơn `AV3-Q2CX0F` và `AV3-8L2KK3` paid; đơn thứ 2 kích hoạt hoàn toàn tự động (giao dịch SePay thật `VN0012481FT26262XB3MW…` → `matched_paid`), gói cộng dồn 2026-10-19 → 2026-11-18. SePay chỉ gọi webhook D100 nên module có **bộ đối soát nền** đọc `payment_transactions` (commit `3f4739c`, `VEO_RECONCILE_SECONDS=20` trên VPS): ~20 giây sau khi D100 ghi giao dịch AV3- là kích hoạt. Không sửa file D100 nào; regression 29/29 |
| **Đăng nhập Google thật + tạo video thật từ app** | **PASS** (người dùng, 2026-09-19) | đăng nhập `ducthoai2013@gmail.com`, Trial còn 1/3; 2 video 1080p tạo trong ~104–117 s (tốc độ Veo). Lộ 2 lỗi thật, đã sửa và phát hành **1.0.1** |
| **1.0.1 (sửa lỗi từ dùng thật)** | **PASS test / chờ người dùng thử** | (1) nút MUA GÓI CƯỚC không mở: `setAlignment(0x84)` TypeError khi khởi tạo (chưa từng có test) → viết lại hộp thoại theo bố cục Veo3 Go (thẻ gói, giá thật từ máy chủ, QR trong cùng cửa sổ) + test bấm nút thật + bộ ghi lỗi toàn cục; (2) prompt tiếng Việt → tên file mã hóa `%C3%B3` → tải 404: Gateway dùng tên ASCII an toàn, URL mã hóa đúng, vẫn phục vụ file cũ (2 video của người dùng đã tải về); (3) "Tạo lại video" giờ TẢI LẠI kết quả cũ, không tạo job mới. Test 14 (Gateway) + 12 (toàn tuyến); zip `ac44b49b…`; `latest.json` 1.0.1 đã push (`ef08c4d`) |
| **Sự cố G-Labs "No active accounts available" (2026-09-19)** | **ĐÃ XỬ LÝ** | nguyên nhân: cầu nối tiện ích Chrome của G-Labs (cổng 18923) mất kết nối, không phải lỗi Gateway. Gateway nay chờ 20 s và thử lại tối đa 6 lần, hết lượt thì báo tiếng Việt "chưa có tài khoản Flow sẵn sàng", KHÔNG tính lượt; `/v1/health` có `glabs_accounts: ok/unavailable` để giám sát. Lỗi thứ hai: upscale 1080p bị Google 403 "PUBLIC ERROR MODEL ACCESS DENIED" → G-Labs báo failed kèm chữ "Hoàn thành": Gateway thử lại 3 lần cách 20 s rồi báo "Google đang tạm giới hạn tốc độ", không tính lượt. Test Gateway 14 → 17 |
| **1.0.2 → 1.0.7 (từ dùng thật, người dùng thử từng bản)** | **PASS test / đã phát hành 1.0.7** | 1.0.2: "Tạo lại video" / "Tạo lại video lỗi" ghi đè ĐÚNG DÒNG (trước đây đẻ dòng mới); 1.0.3: bấm thumbnail xem nhanh ngay trong ô (QtMultimedia, nút ▶), một ô phát một lúc, +9 MB; 1.0.4–1.0.5: nút bút chì màu sửa prompt trực tiếp rồi tạo lại đúng dòng (Ctrl+Enter / Esc); 1.0.6–1.0.7: nút "Hỗ trợ" mang biểu tượng Zalo, bấm mở nhóm Zalo hỗ trợ, chuột phải mở hộp thoại chẩn đoán. Test toàn bộ 43 (Gateway 17, module 10, client 12+, compile). Selftest `--selftest --play` phát thử H.264 trong bản đóng gói |
| **Phát hành 1.0.7** | **XONG** | zip 101,6 MB sha256 `04b1bd79…77ae9c` tại `D:\Auto_veo_Gateway\data\downloads` (công khai qua `veo.d100radar.com/downloads/...`); `latest.json` push `dc0d98c` |
| **1.0.8: tab Đồng bộ nhân vật giống Veo3 Go + giọng đọc** | **ĐÃ PHÁT HÀNH** (2026-09-20) | khảo sát Veo3 Go bằng UI Automation (chỉ đọc): cột phải gồm nút chọn ảnh (tối đa 10), thẻ ảnh 220×124 có × + ô đặt tên, ô chọn giọng `csGlobalVoiceCombo` (30 giọng có mô tả). App: mỗi ảnh BẮT BUỘC có tên; khớp tên chính xác trong prompt (hoặc `@tên`), tên có dấu → tag ASCII (`Bé Na` → `@Be_Na`); giọng gửi kèm job. Gateway: trường `voice` (30 tên chữ thường, chỉ chế độ components, giọng lạ → 422 `bad_voice`). Test 47/47. **Giọng đọc đã kiểm chứng THẬT (2026-09-20):** G-Labs nhận `voice: puck` ở chế độ components, video 8 s 720p xong sau 60 s, nhân vật giữ đúng, có đoạn thoại giây 4–6,5; người dùng nghe xác nhận đúng giọng. zip 101,6 MB sha256 `8d017c2d…f11d24`, `latest.json` push `fb103ad`, tải công khai khớp SHA256; zip 1.0.7 đã xóa. Production Smoke 20/21 (chỉ 'G-Labs up' FAIL vì G-Labs tắt) |
| M6 đóng gói | **PASS** | zip 92,3 MB, sha256 `2d39875e…` (có bản sửa âm thanh), selftest sạch PATH + HTTPS OK; `latest.json` đã cập nhật |
| Production Smoke | **21/21 PASS** | sau khi cấu hình `.env` VPS (public-key 200, webhook bật: không key → 401) |

## Phát hiện khi test thật
1. **Độ dài video** luôn 8 s (tài khoản không ULTRA): không hứa độ dài khác.
2. **Video có âm thanh AAC**; đã sửa "Nối video" giữ tiếng ở cả 2 đường (ghép nhanh / mã hóa lại), có test.
3. **Watermark "Veo"** nhỏ ở góc phải dưới (đúng SOP, không tắt được).
4. Khóa API copy hay dính khoảng trắng/xuống dòng → đã xử lý; `/v1/health` có `glabs_key_set` để chẩn đoán.
5. Script cài Gateway từng lỗi vì vòng lặp `start_gateway.bat` tự bật lại → đã sửa (dừng hẳn + thử lại).

## NEXT TASK

0. ~~Xác nhận giọng đọc thật~~ **xong** (người dùng nghe đúng).
1. ~~Xác nhận 1.0.7 công khai~~ **xong**: `latest.json` = 1.0.7 trên d100radar.com, zip tải qua tunnel 106,5 MB SHA256 khớp, Production Smoke 21/21 PASS; zip 1.0.1 đã xóa khỏi downloads.
2. **[bạn/tôi]** vận hành trước khi mở cho khách: máy ở nhà phải luôn bật Gateway + cloudflared + G-Labs + Chrome (tab `labs.google/fx`); nên có cảnh báo tự động (Zalo/email) khi `glabs_accounts = unavailable` (chưa làm).
3. **[sau]** Windows sạch (Sandbox), ký số exe (SmartScreen), bản FFmpeg LGPL trước khi phát hành rộng, điều khoản Cloudflare/Google/G-Labs nếu bán ngoài, chống lạm dụng Trial bằng nhiều tài khoản Google, giới hạn gửi dồn (Google throttle upscale 1080p).
