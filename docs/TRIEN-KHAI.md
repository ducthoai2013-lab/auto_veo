# Auto_veo3 — Hướng dẫn triển khai

Mọi thứ nằm trong `D:\claude\app_b1\Auto_veo`. Tài liệu này là các bước **bạn** làm để đưa hệ thống lên chạy thật.
Những việc đã kiểm chứng bằng test tự động nằm ở mục G; việc **chưa** làm/kiểm chứng ở mục H.

## Sơ đồ

```
Máy Windows (Auto_veo3.exe) ──HTTPS──▶ d100radar.com  (thoai-dash + module Veo: tài khoản, gói, QR, thiết bị)
                            └─HTTPS──▶ veo.d100radar.com (Cloudflare Tunnel) ▶ Gateway ▶ G-Labs ▶ Google Flow/Veo
Trang tải: https://d100radar.com/veo3   (static, nằm trong frontend/public/veo3 của thoai-dash)
```

## A. Đưa module Veo vào thoai-dash (VPS)

Module nằm ở `thoai-dash-module\`. Nó chỉ THÊM file và sửa 2 dòng `app/main.py`; không đụng luồng D100
(`payments.py`, `billing.py`, `admin.py`, `deps.py`, `config.py`).

1. **Kiểm tra trên bản sao** (đã chạy PASS, chạy lại nếu sửa gì): `.venv\Scripts\python -m pytest tests\test_thoai_module.py`
2. **Áp vào repo local** (repo đang có thay đổi chưa commit của bạn; script không đụng chúng):
   ```
   .venv\Scripts\python thoai-dash-module\apply_to_thoai_dash.py D:\claude\app_b1\thoai-dash\backend
   ```
   Kết quả: thêm 3 file backend, 4 file trang tĩnh vào `frontend\public\veo3\`, 2 dòng vào `main.py`. Xem lại bằng `git diff` rồi commit theo quy trình của bạn.
3. **Sinh khóa ký thật** (một lần): `.venv\Scripts\python tools\gen_veo_keys.py D:\secrets\veo`
   - `veo_private.pem` chỉ đặt trên VPS. `veo_public.pem` chép sang máy nhà.
4. **Biến môi trường trên VPS** (`.env`, không gửi vào chat/repo). Đổi `.env` xong phải force-recreate backend + worker + beat (luật CLAUDE.md của bạn):
   ```
   VEO_JWT_PRIVATE_KEY=<nội dung veo_private.pem, xuống dòng viết thành \n>
   VEO_WEBHOOK_ENABLED=true
   VEO_SEPAY_WEBHOOK_API_KEY=<khóa mới, khác khóa D100 nếu cấu hình SePay riêng>
   ```
   Ngân hàng nhận tiền dùng lại `PAYMENT_BANK_*` sẵn có của D100.
5. **SePay**: thêm webhook thứ hai trỏ tới `https://d100radar.com/api/veo/webhook/sepay`, header `Authorization: Apikey <VEO_SEPAY_WEBHOOK_API_KEY>`.
   Nội dung chuyển khoản của Veo là `AUTOVEO3 AV3-XXXXXX` nên hai luồng không lẫn nhau: mỗi webhook bỏ qua giao dịch không thuộc mình.
   *Nếu SePay chỉ cho một webhook*: cần thêm một nhánh nhận diện `AV3-` trong `payments.py` gọi `veo_service.handle_sepay` (việc này sửa file D100, cần bạn duyệt riêng).
6. **Gói cước**: các gói mẫu (Dùng thử 3 video, Pro 199.000đ, Ultra 399.000đ) chỉ là GIÁ MẪU. Sửa bằng
   `PUT /api/veo/admin/plans/{code}` (đăng nhập super admin) trước khi bán.
7. Bảng `veo_*` tự tạo khi backend khởi động (không cần migration).

## B. Trang tải d100radar.com/veo3

- Bước A2 đã đặt `index.html`, `device.html`, `devices.html`, `latest.json` vào `frontend\public\veo3\`; Vite copy vào bản build, nginx trong thoai-dash phục vụ trực tiếp (`try_files $uri $uri/`).
- **File zip** không nên nằm trong repo. Chọn một nơi lưu rồi ghi địa chỉ vào `latest.json` (`url`, `sha256`, `size_mb`):
  thư mục nginx mount riêng (`/veo3/files/`), GitHub Release, hoặc Cloudflare R2. App cũng đọc `latest.json` để báo "Có bản mới".
- Phát hành bản mới: chạy `installer\build_client.ps1` → lấy `dist\Auto_veo3-<ver>-win64.zip` và `SHA256.txt` → cập nhật `latest.json`.

## C. Máy nhà (Gateway + G-Labs)

1. G-Labs Automation chạy như hiện nay, Webhook Server bật, **giữ bind 127.0.0.1** (không cần bản MAX). Lấy API Key ở tab "Webhook API".
2. `installer\build_gateway.ps1` → `dist\glabs-gateway\`. Chép sang máy nhà, đổi `.env.example` thành `.env`, điền `GW_GLABS_KEY`, `GW_JWT_PUBKEY_FILE`, `GW_DATA_DIR`.
3. Chạy `start_gateway.bat` (tự chạy lại nếu dừng). Tự khởi động cùng Windows: Task Scheduler → "At log on" → chạy `start_gateway.bat`. G-Labs là ứng dụng có cửa sổ nên máy cần đăng nhập Windows tự động.
4. **Cloudflare Tunnel**: Zero Trust → Networks → Tunnels → tạo tunnel `glabs-home` → cài `cloudflared` làm dịch vụ trên máy nhà → Public hostname `veo.d100radar.com` → `http://localhost:8080`. Token tunnel dán thẳng vào máy, không gửi vào chat/repo.
5. Kiểm tra: `https://veo.d100radar.com/v1/health` phải trả `{"ok":true,"glabs":"up",...}`.
6. Trần luồng (`GW_MAX_INFLIGHT_*`) bắt đầu thấp, tăng dần sau khi đo RAM/CPU khi nhiều máy cùng tạo.

## D. Phát hành app cho người dùng

`installer\build_client.ps1` → `dist\Auto_veo3-1.0.0-win64.zip`. Người dùng: tải từ d100radar.com/veo3 → giải nén → mở `Auto_veo3.exe` → đăng nhập Google → dùng (xem `installer\HUONG-DAN.txt`).

## E. Chạy thử toàn tuyến trên máy dev (không đụng thật)

```
.venv\Scripts\python tools\dev_stack.py     # bản sao thoai-dash + module Veo + Gateway (G-Labs giả)
```
In ra 2 địa chỉ; đặt `AUTOVEO_ACCOUNT_URL` và `AUTOVEO_GATEWAY_URL` rồi chạy `client\run_dev.py`.
Prompt chứa `FAIL` sẽ báo lỗi, chứa `FLAKY` sẽ lỗi lần đầu rồi tự thử lại.

## F. Vận hành

- Thu hồi máy: người dùng vào `d100radar.com/veo3/devices.html` (chủ/admin workspace). Máy bị gỡ mất hiệu lực khi token hết hạn (tối đa 6 giờ, `VEO_ACCESS_TOKEN_HOURS`).
- Tiền về sau hạn đơn (`matched_expired`) hoặc lệch số tiền: xử lý tay bằng `POST /api/veo/admin/orders/{code}/mark-paid`.
- Nhật ký Gateway/số job: `glabs-gateway.exe admin jobs`.
- Kết quả video ở máy nhà giữ 7 ngày rồi tự dọn.

## G. Đã kiểm chứng bằng test tự động

| Bộ test | Nội dung | Kết quả |
|---|---|---|
| `tests\test_gateway.py` (9) | token Ed25519, 4 mode + ảnh, chống trùng, hạn mức, hết hạn, thử lại, hàng đợi công bằng, cách ly team | PASS |
| `tests\test_thoai_module.py` (7) | áp module lên bản sao thoai-dash, đăng nhập thiết bị, giới hạn máy, gỡ máy, mua QR + webhook, chống trùng, **gói D100 không bị ảnh hưởng** | PASS |
| `tests\test_compile.py` (2) | mọi file biên dịch được, app import được (bắt lỗi cú pháp trước khi đóng gói) | PASS |
| `tests\test_client_e2e.py` (6) | app thật ↔ Gateway ↔ module: đăng nhập, tạo/tải video, nối, cắt ảnh cuối, hết hạn mức, mua gói, cửa sổ chính | PASS |

## H. Chưa làm / chưa kiểm chứng (cần lưu ý)

- **G-Labs thật**: mọi test dùng G-Labs giả lập. Chưa chạy qua G-Labs và Google Flow thật, chưa đo tốc độ/luồng thật.
- **Cloudflare Tunnel** và điều khoản băng thông video lớn: chưa thử.
- **SePay/QR thật**: webhook được test bằng payload giả theo định dạng SePay trong mã D100; chưa quét QR thật cho đơn Veo.
- **Trang web** `device.html`/`devices.html`: chưa chạy trên d100radar.com thật; chưa kiểm tra với đăng nhập Google thật.
- **Windows Sandbox / máy sạch**: đã tự kiểm tra bản đóng gói chạy khi không có Python/ffmpeg trong PATH (xem README); chưa thử trên máy Windows khác.
- **Gói đóng gói chưa ký số**: SmartScreen sẽ cảnh báo lần đầu; Defender chưa được thử.
- **FFmpeg GPL**: bản đang đóng kèm là bản GPL (xem `installer\THIRD-PARTY.txt`); đổi sang bản LGPL trước khi phát hành rộng.
- Giá gói, số luồng, hạn mức là **giá trị mẫu**.
- Bản Inno Setup, cập nhật tự động, macOS: chưa làm (bản zip là bản chính).
