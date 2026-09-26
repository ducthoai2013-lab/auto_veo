# Việc CHỈ bạn làm được (tôi không có quyền truy cập)

Mọi thứ khác đã làm/kiểm tra xong. Làm theo thứ tự; xong mỗi mục, quay lại chat báo "xong mục N" để tôi kiểm tra và chạy tiếp.
**Không gửi token/khóa vào chat**: mọi bí mật đều nhập vào ô ẩn của script hoặc dán thẳng vào máy/VPS.

## Mục 1 — Cloudflare Tunnel `veo.d100radar.com` (máy nhà, ~5 phút)

1. Vào https://one.dash.cloudflare.com → **Networks → Tunnels → Create a tunnel** → chọn **Cloudflared** → đặt tên `glabs-home` → Save.
   (Đây là tunnel MỚI, không đụng tunnel của VPS d100radar.com.)
2. Ở bước "Install and run a connector" chọn **Windows**. Trang hiện một lệnh dài chứa **token** (chuỗi bắt đầu bằng `eyJ`). Chưa cần chạy lệnh đó. Giữ trang này mở để copy token.
3. Bấm **Next** → **Public Hostname**: Subdomain `veo`, Domain `d100radar.com`, Type **HTTP**, URL `localhost:8080` → Save.
4. Chạy (sẽ hiện hộp UAC, bấm Yes):
   ```
   powershell -ExecutionPolicy Bypass -File D:\claude\app_b1\Auto_veo\installer\setup_tunnel.ps1
   ```
   Khi hỏi `Tunnel Token`, dán token (ô ẩn, không thấy ký tự) rồi Enter.
5. Báo "xong mục 1". Tôi kiểm tra `https://veo.d100radar.com/v1/health`.

## Mục 2 — API Key của G-Labs (máy nhà, ~1 phút)

1. Mở G-Labs → tab **Webhook API** → copy API Key.
2. Chạy:
   ```
   powershell -ExecutionPolicy Bypass -File D:\claude\app_b1\Auto_veo\installer\setup_gateway.ps1 -ChangeKey
   ```
   Dán khóa vào ô `G-Labs API Key` (ô ẩn). Script ghi vào `D:\Auto_veo_Gateway\.env` (chỉ tài khoản của bạn đọc được) và khởi động lại Gateway.
3. Báo "xong mục 2". Tôi chạy test tạo video thật (mỗi video thật tốn credit Google Flow/Veo của bạn).

## Mục 3 — Đưa module lên VPS (theo quy trình n8n của bạn)

Tôi đã commit sẵn trong `D:\claude\app_b1\thoai-dash` (nhánh `main`, chỉ file Veo, chưa push).

1. `git push` từ PowerShell như mọi lần.
2. Chạy workflow n8n `[D100][OPS03][STAGING] Deploy VPS` (hoặc để `OPS04 Auto-Sync` tự kéo). Đối chiếu commit trong output Step 1 với commit vừa push.
3. Health check phải `PASS`. Module Veo tự tạo 6 bảng `veo_*`, không đụng bảng D100. Trước khi cấu hình mục 4, `/api/veo/*` chỉ trả lỗi "chưa cấu hình khóa" (an toàn).

## Mục 4 — Biến môi trường trên VPS

1. Mở file `D:\claude\app_b1\Auto_veo\secrets\veo\vps_env_snippet.txt` (bí mật, chỉ nằm ở máy này).
2. Dán các dòng `VEO_*` vào `.env` của thoai-dash **trên VPS** (bằng cách bạn vẫn dùng, ví dụ workflow SSH của n8n).
3. Force-recreate **backend + worker + beat** (luật CLAUDE.md: đổi `.env` phải recreate cả ba).
4. Kiểm tra: `https://d100radar.com/api/veo/public-key` phải trả `{"algorithm":"EdDSA","pem":"-----BEGIN PUBLIC KEY..."}` và khóa công khai này phải **trùng** `D:\claude\app_b1\Auto_veo\secrets\veo\veo_public.pem`.

## Mục 5 — SePay: thêm webhook thứ hai

1. SePay → Cấu hình webhook → **Thêm webhook mới** (giữ nguyên webhook D100 cũ).
2. URL: `https://d100radar.com/api/veo/webhook/sepay`. Xác thực **API Key** = giá trị `VEO_SEPAY_WEBHOOK_API_KEY` trong file snippet.
3. Nếu SePay chỉ cho MỘT webhook: báo tôi, cần thêm nhánh nhận diện `AV3-` vào `payments.py` (sửa file D100, tôi làm khi bạn đồng ý).

## Sau đó (tôi làm)

Kiểm tra tunnel → test tạo video thật → đưa zip vào Gateway để tải tại `https://veo.d100radar.com/downloads/...` → cập nhật `latest.json` → smoke test cuối (đăng nhập thật, mua gói bằng QR thật, quota).
Lần mua QR thật: bạn sẽ được nhờ chuyển tiền thật đúng 1 lần cho gói rẻ nhất (hoặc đặt tạm giá thấp) để xác nhận SePay tự kích hoạt.
