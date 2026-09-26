"""Chuỗi giao diện VI/EN. Thiếu bản dịch EN thì dùng VI."""
from __future__ import annotations

VI = {
    "title": "Auto_veo3 v{ver} - Lưu ý: 1 Tài khoản / {n} máy (Không đổi máy được)",
    "tab_text": "Text to Video", "tab_image": "Image to Video", "tab_startend": "Start-End",
    "tab_chars": "Đồng bộ nhân vật",
    "ph_text": "Dán danh sách prompt vào đây\n\nXuống dòng sẽ tính là một prompt mới…\n\n"
               "NÊN DÙNG PROMPT BẰNG TIẾNG ANH\n\nNgười dùng miễn phí được tạo 1 prompt 1 lần",
    "ph_prompts": "Dán danh sách prompt vào đây (mỗi dòng một prompt, tương ứng từng ảnh từ trên xuống)…",
    "btn_start": "BẮT ĐẦU TẠO VIDEO", "btn_stop": "DỪNG", "btn_buy": "MUA GÓI CƯỚC",
    "ratio": "Tỷ lệ khung hình", "ratio_land": "16:9 (Ngang)", "ratio_port": "9:16 (Dọc)",
    "outdir": "Chọn thư mục lưu video",
    "tb_merge": "Nối video", "tb_retry": "Tạo lại video", "tb_retry_err": "Tạo lại video lỗi",
    "tb_lastframe": "Cắt ảnh cuối", "tb_clear": "Xóa kết quả", "tb_help": "Hỗ trợ", "tb_zalo": "Nhóm Zalo", "tb_zalo_tip": "Vào nhóm Zalo để được hỗ trợ (chuột phải: thông tin chẩn đoán)",
    "empty": "Chưa có video nào được tạo",
    "guide_title": "Hướng dẫn sử dụng",
    "g1_title": "1) Tạo video từ ảnh hàng loạt",
    "g1": ["• Bước 1: Chọn TẤT CẢ ảnh bạn muốn tạo video (ứng dụng sẽ tự sắp xếp theo TÊN FILE ẢNH).",
           "• Bước 2: Dán HÀNG LOẠT prompt (mỗi dòng một prompt). Ứng dụng sẽ tự gán prompt vào ảnh tương ứng từ trên xuống.",
           "• LƯU Ý: Bạn có thể click vào mỗi ảnh để chọn ảnh thay thế"],
    "g2_title": "2) Tạo video từ ảnh nhân vật",
    "g2": ["• Bước 1: Thêm ảnh nhân vật, tối đa 10 nhân vật. Đặt tên nhân vật (nên > 4 ký tự)",
           "• Bước 2: Nhập hàng loạt prompt, mỗi dòng một prompt. Trong prompt nhắc tên nhân vật kèm hành động, bối cảnh",
           "• LƯU Ý: Nên chọn ảnh nền trắng hoặc png ko nền."],
    "g3_title": "3) Tạo video từ ảnh đầu–cuối (Start–End)",
    "g3": ["• Bước 1: Chọn ảnh bắt đầu (ứng dụng sẽ crop chuẩn tỷ lệ).",
           "• Bước 2: Chọn ảnh kết thúc (số lượng phải bằng số lượng ảnh bắt đầu).",
           "• Bước 3: Nhập prompt cho từng cặp ảnh bắt đầu và kết thúc. Mỗi dòng một prompt.",
           "• LƯU Ý: Bạn có thể click vào từng ảnh để thay thế"],
    "acc_title": "Thông tin tài khoản", "acc_email": "Email:", "acc_type": "Loại tài khoản:",
    "acc_exp": "Ngày hết hạn:", "acc_used": "Đã sử dụng:", "acc_quota": "Hạn mức video:",
    "acc_type_val": "Tạo {n} video cùng lúc", "acc_unlimited": "Không giới hạn",
    "acc_quota_left": "còn {left}/{quota} video", "acc_quota_free": "Không giới hạn số video",
    "ready": "Sẵn sàng", "offline": "Mất kết nối máy chủ — việc của bạn vẫn được giữ, sẽ tự tiếp tục",
    "login_title": "Đăng nhập Auto_veo3",
    "login_intro": "Đăng nhập bằng tài khoản Google của bạn trên trình duyệt để kích hoạt máy này.",
    "login_btn": "Đăng nhập bằng Google", "login_wait": "Đang chờ bạn cho phép thiết bị này trên trình duyệt…",
    "login_code": "Mã xác nhận: {code}", "login_open": "Mở lại trang đăng nhập",
    "buy_title": "Mua gói cước", "buy_make_qr": "Tạo mã QR thanh toán", "buy_waiting": "Đang chờ thanh toán…",
    "buy_paid": "Thanh toán thành công! Gói của bạn đã được kích hoạt.",
    "buy_scan": "Quét mã QR bằng app ngân hàng. Hệ thống tự kích hoạt sau khi nhận được tiền.",
    "buy_expired": "Đơn đã hết hạn, hãy tạo đơn mới.",
    "support_title": "Hỗ trợ",
}

EN = {
    "tab_chars": "Character sync", "btn_start": "START CREATING VIDEOS", "btn_buy": "BUY A PLAN",
    "ratio": "Aspect ratio", "ratio_land": "16:9 (Landscape)", "ratio_port": "9:16 (Portrait)",
    "outdir": "Output folder", "tb_merge": "Merge videos", "tb_retry": "Regenerate", "tb_retry_err": "Regenerate failed",
    "tb_lastframe": "Cut last frame", "tb_clear": "Clear results", "tb_help": "Support", "tb_zalo": "Zalo group", "tb_zalo_tip": "Join the Zalo group for support (right-click: diagnostics)",
    "empty": "No videos yet", "guide_title": "How to use", "acc_title": "Account information",
    "acc_type": "Account type:", "acc_exp": "Expires:", "acc_used": "Used:", "acc_quota": "Video quota:",
    "acc_type_val": "Create {n} videos at once", "acc_unlimited": "Unlimited", "ready": "Ready",
    "login_btn": "Sign in with Google", "buy_title": "Buy a plan", "support_title": "Support",
}

_lang = "vi"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in ("vi", "en") else "vi"


def lang() -> str:
    return _lang


def tr(key: str, **kw) -> str:
    text = (EN.get(key) if _lang == "en" else None) or VI.get(key) or key
    return text.format(**kw) if kw and isinstance(text, str) else text
