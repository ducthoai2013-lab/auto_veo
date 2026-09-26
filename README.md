# Auto_veo3

Bản sao chức năng và giao diện Veo3 Go (đổi tên/logo thành Auto_veo3): tạo video hàng loạt từ prompt/ảnh,
kết nối G-Labs Automation ở máy nhà, tài khoản + mua gói bằng QR trên thoai-dash (d100radar.com).

| Thư mục | Nội dung |
|---|---|
| `client\` | App Windows (Python + PySide6), gói `autoveo`. Chạy thử: `.venv\Scripts\python client\run_dev.py` |
| `gateway\` | Gateway chạy ở máy nhà: hàng đợi công bằng, gọi G-Labs, giữ/tải kết quả, kiểm token |
| `thoai-dash-module\` | Module Veo cho thoai-dash (bảng riêng, API, trang tĩnh `/veo3`) + `apply_to_thoai_dash.py` |
| `installer\` | Script đóng gói (`build_client.ps1`, `build_gateway.ps1`), hướng dẫn người dùng |
| `tools\` | `dev_stack.py` (môi trường thử toàn tuyến), `gen_veo_keys.py`, `make_logo.py`, `screenshot.py` |
| `tests\` | 24 test tự động (`.venv\Scripts\python -m pytest tests -q`; chạy `test_thoai_module` riêng nếu xung đột `app`) |
| `docs\` | `TRIEN-KHAI.md` (các bước đưa lên chạy thật, việc chưa làm), kế hoạch v2/v3 (docx) |

**Bắt đầu:** đọc `docs\TRIEN-KHAI.md`. Logo hiện là biểu tượng tạm (`client\resources\logo.png`, `app.ico`), thay bằng logo thật rồi build lại.

Cài môi trường dev: `python -m venv .venv` rồi
`.venv\Scripts\pip install PySide6 httpx pillow fastapi "uvicorn[standard]" pytest "pyjwt[crypto]" pyinstaller sqlalchemy psycopg2-binary pydantic-settings google-auth redis requests python-multipart`.
