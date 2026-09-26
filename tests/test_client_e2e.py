"""E2E: app thật (JobManager + API + giao diện offscreen) ↔ Gateway (G-Labs giả) ↔ module Veo trên thoai-dash (bản sao)."""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtWidgets import QApplication  # noqa: E402

THOAI = Path(os.getenv("THOAI_BACKEND", r"D:\claude\app_b1\thoai-dash\backend"))
pytestmark = pytest.mark.skipif(not THOAI.is_dir(), reason="không có thoai-dash local")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def stack():
    from dev_stack import Stack
    s = Stack(mock_delay=0.4)
    yield s
    s.stop()


@pytest.fixture()
def client(stack, qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOVEO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOVEO_ACCOUNT_URL", stack.account_url)
    monkeypatch.setenv("AUTOVEO_GATEWAY_URL", stack.gateway_url)
    from autoveo import config
    from autoveo.api import AccountApi, GatewayApi, Session
    from autoveo.jobs import JobManager
    from autoveo.store import Store
    settings = config.Settings()
    session = Session(settings)
    d = session.login_start()
    assert d["verification_url"].endswith(d["user_code"])
    assert session.login_poll(d["device_code"])["status"] == "pending"
    user = stack.new_user()
    stack.approve(d["user_code"], user)
    assert session.login_poll(d["device_code"])["status"] == "approved"
    store = Store(config.data_dir() / "jobs.db")
    gw = GatewayApi(session)
    mgr = JobManager(gw, store)
    mgr.start()
    yield dict(session=session, gw=gw, store=store, mgr=mgr, account=AccountApi(session), settings=settings,
               out=str(tmp_path / "videos"), tmp=tmp_path)
    mgr.stop()
    store.close()


def pump(qapp, cond, timeout=25.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def statuses(c, ids):
    return [c["store"].get(i)["status"] for i in ids]


def make_image(path: Path, color=(200, 30, 30), size=(640, 480)):
    from PIL import Image
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_login_persisted_and_account_info(client, stack):
    me = client["gw"].me()
    assert me["email"].endswith("@congty.vn") and me["plan_code"] == "trial" and me["quota"] == 3
    acc = client["account"].me()
    assert acc["plan"]["code"] == "trial" and acc["expired"] is False
    # phiên lưu mã hóa, mở lại app không cần đăng nhập
    from autoveo.api import Session
    assert Session(client["settings"]).signed_in


def test_text_to_video_download_and_tools(client, qapp):
    from autoveo import ffmpeg_tools
    from autoveo.jobs import JobSpec
    c = client
    specs = [JobSpec("text_to_video", f"a cat number {i}", i, "16:9", ["720p"]) for i in (1, 2)]
    ids = c["mgr"].submit(specs, c["out"])
    assert pump(qapp, lambda: all(s == "completed" for s in statuses(c, ids))), statuses(c, ids)
    rows = [c["store"].get(i) for i in ids]
    files = [Path(__import__("json").loads(r["files_json"])[0]) for r in rows]
    assert all(f.is_file() and f.stat().st_size > 1000 and f.name.startswith(("001_", "002_")) for f in files)
    assert all(r["thumb"] and Path(r["thumb"]).is_file() for r in rows)      # ảnh đại diện từ ffmpeg
    # nối video + cắt ảnh cuối bằng ffmpeg
    merged = c["tmp"] / "merged.mp4"
    ffmpeg_tools.concat(files, merged)
    assert merged.stat().st_size > 1000
    last = c["tmp"] / "last.jpg"
    ffmpeg_tools.last_frame(files[0], last)
    assert last.stat().st_size > 500
    assert c["gw"].me()["used_total"] == 2


def test_image_modes_and_quota_and_retry(client, qapp):
    from autoveo.jobs import JobSpec
    c = client
    a, b = make_image(c["tmp"] / "a.png"), make_image(c["tmp"] / "b.png", (30, 30, 200), (500, 900))
    specs = [JobSpec("start_image", "make it move", 1, "16:9", ["720p"], [{"name": "a.png", "path": a}]),
             JobSpec("start_end_image", "transition", 2, "9:16", ["720p"],
                     [{"name": "a.png", "path": a}, {"name": "b.png", "path": b}])]
    ids = c["mgr"].submit(specs, c["out"])
    assert pump(qapp, lambda: all(s == "completed" for s in statuses(c, ids))), statuses(c, ids)   # 2/3 video của gói thử
    # ép lỗi: prompt FAIL → job lỗi, KHÔNG tính hạn mức
    bad = c["mgr"].submit([JobSpec("text_to_video", "FAIL now", 1, "16:9", ["720p"])], c["out"])
    assert pump(qapp, lambda: statuses(c, bad) == ["failed"]) and "Mock" in c["store"].get(bad[0])["error"]
    assert c["gw"].me()["used_total"] == 2
    # tạo lại video lỗi (đổi prompt để thành công) → vẫn còn 1 lượt trong gói thử
    ok = c["mgr"].submit([JobSpec("text_to_video", "one more", 1, "16:9", ["720p"])], c["out"])
    assert pump(qapp, lambda: statuses(c, ok) == ["completed"])
    # hết hạn mức (3/3): job kế bị từ chối với thông báo đúng
    notices = []
    c["mgr"].notice.connect(lambda code, msg: notices.append(code))
    over = c["mgr"].submit([JobSpec("text_to_video", "over quota", 1, "16:9", ["720p"])], c["out"])
    assert pump(qapp, lambda: statuses(c, over) == ["failed"])
    assert "quota_exceeded" in notices and "hạn mức" in c["store"].get(over[0])["error"]


def test_components_tab_logic():
    from autoveo.ui.tabs.tabs import find_characters, pair_by_line, tag_characters
    assert find_characters("Linhchi chào Baoquoc rồi đi", ["Baoquoc", "Linhchi", "Khac"]) == ["Linhchi", "Baoquoc"]
    assert tag_characters("linhchi nói chuyện với Baoquoc", ["Linhchi", "Baoquoc"]) == "@Linhchi nói chuyện với @Baoquoc"
    assert tag_characters("@Linhchi đã có @", ["Linhchi"]) == "@Linhchi đã có @"
    n, w = pair_by_line(["a", "b", "c"], ["1", "2"])
    assert n == 2 and "1 prompt cuối" in w[0]


def test_buy_plan_qr_flow(client, stack):
    c = client
    plans = c["account"].plans()
    assert {p["code"] for p in plans} == {"trial", "pro", "ultra"}
    o = c["account"].create_order("pro", 1)
    assert o["status"] == "pending" and "img.vietqr.io" in o["qr_url"]
    assert c["account"].get_order(o["order_code"])["status"] == "pending"
    assert stack.pay(o)["status"] == "matched_paid"
    assert c["account"].get_order(o["order_code"])["status"] == "paid"
    c["session"].token(force=True)              # app làm mới token, nhận gói mới
    me = c["gw"].me()
    assert me["plan_code"] == "pro" and me["quota"] is None and me["max_concurrent"] == 3 and not me["expired"]


def test_main_window_end_to_end(client, qapp, stack):
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    from PySide6.QtWidgets import QMessageBox
    qapp.setStyleSheet(QSS)
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.settings.set("out_dir", client["out"])
    win.show()
    win.tab_text.edit.setPlainText("first prompt\n\nsecond prompt\n")
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    win.on_start()
    assert pump(qapp, lambda: len(win.results.cards) == 2)
    assert pump(qapp, lambda: all(c.status.text() == "Hoàn thành" for c in win.results.cards.values()))
    assert pump(qapp, lambda: win.account_panel.info.get("used_total") is not None)
    assert "Không giới hạn" in win.account_panel.quota.format() or "video" in win.account_panel.quota.format()
    # tab ảnh: lệch số lượng cảnh báo, không tạo job
    win.tab_image.images.set_paths([make_image(client["tmp"] / f"i{n}.png") for n in (10, 2, 1)])
    assert [Path(p).name for p in win.tab_image.images.paths()] == ["i1.png", "i2.png", "i10.png"]   # thứ tự tự nhiên
    win.tab_image.edit.setPlainText("only one prompt")
    res = win.tab_image.build("16:9", ["720p"])
    assert len(res.specs) == 1 and "2 ảnh cuối" in res.warnings[0]
    win.close()


def test_after_payment_app_gets_new_plan_without_relogin(client, qapp, stack):
    """Lỗi từng có: sau khi trả tiền app vẫn giữ token cũ (gói dùng thử) tới 6 giờ."""
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    qapp.setStyleSheet(QSS)
    win = MainWindow(client["settings"], client["session"], client["store"])
    assert pump(qapp, lambda: win.info.get("plan_code") == "trial")
    o = client["account"].create_order("ultra", 1)
    stack.pay(o, txn="TXN-AFTERPAY")
    win._after_paid()                      # đúng đường đi khi hộp thoại mua báo 'paid'
    assert pump(qapp, lambda: win.info.get("plan_code") == "ultra" and win.info.get("allow_4k") is True)
    assert win.info["quota"] is None and not win.info["expired"]
    win.close()


def test_pending_order_cap(client):
    from autoveo.api import ApiError
    for _ in range(5):
        client["account"].create_order("pro", 1)
    try:
        client["account"].create_order("pro", 1)
        raise AssertionError("phải bị chặn ở đơn thứ 6")
    except ApiError as e:
        assert e.status == 429 and e.code == "too_many_orders"


def test_concat_keeps_audio_on_both_paths(tmp_path):
    """Video Veo có âm thanh AAC: nối phải giữ tiếng cả khi ghép nhanh lẫn khi phải mã hóa lại."""
    import subprocess
    from autoveo import ffmpeg_tools as ft
    ff = ft.ffmpeg_path()

    def clip(name, size, tone):
        f = tmp_path / name
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:d=1:r=24",
                        "-f", "lavfi", "-i", f"sine=frequency={tone}:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(f)], check=True)
        return f
    a, b = clip("a.mp4", "640x360", 440), clip("b.mp4", "640x360", 660)
    c = clip("c.mp4", "320x240", 880)                        # khác kích thước -> buộc đường mã hóa lại
    fast, slow = tmp_path / "fast.mp4", tmp_path / "slow.mp4"
    ft.concat([a, b], fast)
    ft.concat([a, c], slow)
    assert ft.has_audio(a) and ft.has_audio(fast) and ft.has_audio(slow)
    silent = tmp_path / "silent.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=1:r=24", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(silent)], check=True)
    assert not ft.has_audio(silent)


def _png_bytes():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (300, 300), (30, 30, 30)).save(b, "PNG")
    return b.getvalue()


def test_all_dialogs_construct_and_buy_button_opens(client, qapp, stack, monkeypatch):
    """Lỗi thật 2026-09-19: nút MUA GÓI CƯỚC không mở vì BuyDialog ném TypeError khi khởi tạo (chưa từng có test)."""
    from autoveo.ui.dialogs.dialogs import BuyDialog, LoginDialog, SupportDialog
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    qapp.setStyleSheet(QSS)
    LoginDialog(client["session"])
    SupportDialog(client["session"], client["gw"])
    opened = []
    monkeypatch.setattr(BuyDialog, "exec", lambda self: opened.append(self) or 0)
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.buy_btn.click()                                       # đúng thao tác của người dùng
    assert len(opened) == 1
    assert pump(qapp, lambda: len(opened[0].cards) == 2)      # thẻ gói dựng từ máy chủ
    win.close()


def test_buy_dialog_full_flow_cards_qr_and_auto_activation(client, qapp, stack, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from autoveo.ui.dialogs.dialogs import BuyDialog
    from autoveo.ui.theme import QSS
    qapp.setStyleSheet(QSS)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    acc = client["account"]
    monkeypatch.setattr(acc, "fetch_bytes", lambda url: _png_bytes())           # không gọi img.vietqr.io thật
    dlg = BuyDialog(acc)
    assert pump(qapp, lambda: set(dlg.cards) == {"pro", "ultra"})
    assert "199,000 VNĐ" in dlg.cards["pro"].price.text() and "399,000 VNĐ" in dlg.cards["ultra"].price.text()
    assert "30 ngày" in dlg.cards["pro"].duration.text()
    dlg.cycle_box.setCurrentIndex(1)                                             # 3 tháng, giảm 5%
    assert "90 ngày" in dlg.cards["pro"].duration.text() and "567,150" in dlg.cards["pro"].price.text()
    dlg.cycle_box.setCurrentIndex(0)
    paid = []
    dlg.paid.connect(lambda: paid.append(1))
    dlg.cards["pro"].button.click()                                              # "Chọn gói này"
    assert pump(qapp, lambda: dlg.order is not None and dlg.stack.currentIndex() == 1)
    assert pump(qapp, lambda: dlg.qr.pixmap() is not None and not dlg.qr.pixmap().isNull())
    assert dlg.order["order_code"] in dlg.info.text() and "199,000 VNĐ" in dlg.info.text()
    stack.pay(dlg.order, txn="TXN-DIALOG-1")
    dlg._check()
    assert pump(qapp, lambda: paid == [1])                                       # thanh toán xong → báo 'paid' + đóng
    assert client["gw"].me()["plan_code"] == "trial"                             # token chưa làm mới: app làm ở _after_paid


def test_vietnamese_prompt_downloads_and_retry_redownloads_without_new_job(client, qapp):
    """Lỗi thật: prompt tiếng Việt → tên file mã hóa → tải 404 → job báo lỗi dù đã tốn hạn mức. Nay phải tải được,
    và 'Tạo lại' job lỗi tải phải TẢI LẠI kết quả cũ thay vì tạo job mới."""
    from autoveo.jobs import JobSpec
    c = client
    ids = c["mgr"].submit([JobSpec("text_to_video", "con chó chạy trên đồng cỏ", 1, "16:9", ["720p"])], c["out"])
    assert pump(qapp, lambda: statuses(c, ids) == ["completed"]), statuses(c, ids)
    f = Path(__import__("json").loads(c["store"].get(ids[0])["files_json"])[0])
    assert f.is_file() and f.stat().st_size > 1000
    used = c["gw"].me()["used_total"]
    f.unlink()
    c["store"].update(ids[0], status="failed", error="File kết quả đã bị dọn khỏi máy chủ (quá hạn lưu)", files_json=None)
    c["mgr"].retry(ids)
    assert pump(qapp, lambda: statuses(c, ids) == ["completed"]), statuses(c, ids)
    assert c["gw"].me()["used_total"] == used                                    # KHÔNG tạo job mới, không tốn hạn mức
    assert len(c["store"].all()) == 1


def _select_only(win, ids):
    for i, card in win.results.cards.items():
        card.check.setChecked(i in ids)


def _patch_prompt(store, jid, prompt):
    """Giả lập 'lỗi tạm thời đã qua': đổi prompt FAIL (lỗi cố ý của mock) thành prompt chạy được."""
    import json as _j
    row = store.get(jid)
    spec = _j.loads(row["spec_json"])
    spec["prompt"] = prompt
    store.update(jid, prompt=prompt, spec_json=_j.dumps(spec, ensure_ascii=False))


def test_retry_buttons_reuse_the_same_row_and_never_add_rows(client, qapp, stack):
    """Lỗi UI thật: mỗi lần bấm 'Tạo lại' đẻ thêm dòng mới ở cuối. Nay phải ghi đè đúng dòng đó."""
    import json as _j
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    from PySide6.QtWidgets import QMessageBox
    qapp.setStyleSheet(QSS)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    client["mgr"].stop()                                   # chỉ để MainWindow.manager theo dõi store này
    stack.pay(client["account"].create_order("pro", 1), txn="TXN-RETRY-UI")   # gói Pro: không giới hạn lượt
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.settings.set("out_dir", client["out"])
    win.show()
    assert pump(qapp, lambda: win.info.get("plan_code") == "trial")
    client["session"].token(force=True)
    win.refresh_account()
    assert pump(qapp, lambda: win.info.get("plan_code") == "pro")
    store, cards = client["store"], win.results.cards

    win.tab_text.edit.setPlainText("good one\n\nFAIL two\n\nFAIL three\n")
    win.on_start()
    assert pump(qapp, lambda: len(cards) == 3 and all(
        store.get(i)["status"] in ("completed", "failed") for i in cards))
    ids = list(cards)
    ok_id, bad2, bad3 = ids
    assert [store.get(i)["status"] for i in ids] == ["completed", "failed", "failed"]
    old_files = _j.loads(store.get(ok_id)["files_json"])
    old_gw = {i: store.get(i)["gw_id"] for i in ids}

    # 1) tick 1 dòng LỖI → 'Tạo lại video' → chính dòng đó thành Hoàn thành, không thêm dòng
    _patch_prompt(store, bad2, "fixed two")
    _select_only(win, {bad2})
    win.results.b_retry.click()
    assert pump(qapp, lambda: store.get(bad2)["status"] == "completed"), store.get(bad2)["status"]
    assert len(store.all()) == 3 and len(cards) == 3 and list(cards) == ids
    assert store.get(bad2)["gw_id"] != old_gw[bad2] and store.get(bad2)["error"] is None
    assert pump(qapp, lambda: cards[bad2].status.text() == "Hoàn thành")
    assert store.get(bad3)["status"] == "failed" and store.get(ok_id)["gw_id"] == old_gw[ok_id]   # dòng không tick: y nguyên

    # 2) tick 1 dòng ĐÃ HOÀN THÀNH → tạo lại đè lên chính dòng đó (file mới thay file cũ)
    _select_only(win, {ok_id})
    win.results.b_retry.click()
    assert pump(qapp, lambda: store.get(ok_id)["gw_id"] != old_gw[ok_id] and store.get(ok_id)["status"] == "completed")
    assert len(store.all()) == 3 and len(cards) == 3
    new_files = _j.loads(store.get(ok_id)["files_json"])
    assert new_files and Path(new_files[0]).is_file() and Path(new_files[0]).stat().st_size > 1000
    assert all(not Path(f).exists() for f in old_files if f not in new_files)             # kết quả cũ được thay

    # 3) 'Tạo lại video lỗi': tự quét, không cần tick, nhiều dòng lỗi cùng lúc
    win.tab_text.edit.setPlainText("FAIL a\n\nFAIL b\n\nFAIL c\n")
    win.on_start()
    assert pump(qapp, lambda: len(cards) == 6 and all(
        store.get(i)["status"] in ("completed", "failed") for i in cards))
    bad = [i for i in cards if store.get(i)["status"] == "failed"]
    assert len(bad) == 4 and bad3 in bad                                                   # 3 dòng mới + dòng lỗi cũ còn lại
    for n, i in enumerate(bad):
        _patch_prompt(store, i, f"recovered {n}")
    good_before = {i: store.get(i)["gw_id"] for i in cards if i not in bad}
    _select_only(win, set())                                                              # không tick gì cả
    win.results.b_retry_err.click()
    assert pump(qapp, lambda: all(store.get(i)["status"] == "completed" for i in bad)), [store.get(i)["status"] for i in bad]
    assert len(store.all()) == 6 and len(cards) == 6 and list(cards)[:3] == ids            # KHÔNG sinh dòng mới, thứ tự giữ nguyên
    assert all(store.get(i)["gw_id"] == g for i, g in good_before.items())                # dòng tốt không bị đụng
    assert pump(qapp, lambda: all(cards[i].status.text() == "Hoàn thành" for i in cards))   # thẻ cập nhật qua tín hiệu
    win.close()


def test_thumbnail_plays_inline_with_play_badge(client, qapp):
    """Bấm vào ảnh nhỏ: xem ngay trong ô đó (không mở cửa sổ ngoài); có nút ▶ ở giữa; một ô phát tại một thời điểm."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from autoveo.jobs import JobSpec
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    from PySide6.QtWidgets import QMessageBox
    qapp.setStyleSheet(QSS)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    client["mgr"].stop()
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.settings.set("out_dir", client["out"])
    win.show()
    win.tab_text.edit.setPlainText("clip one\n\nclip two\n")
    win.on_start()
    cards = win.results.cards
    assert pump(qapp, lambda: len(cards) == 2 and all(c.status.text() == "Hoàn thành" for c in cards.values()))
    a, b = (c.thumb for c in cards.values())
    assert a.playable and b.playable and a.badge.isVisible() and b.badge.isVisible()     # nút ▶ báo có thể xem
    QTest.mouseClick(a, Qt.LeftButton)
    assert pump(qapp, lambda: a.video is not None and a.video.isVisible() and a.player.position() > 200), "không phát trong ô"
    assert not a.badge.isVisible() and a.size().width() == 112 and a.video.size() == a.size()   # vẫn trong đúng ô nhỏ
    assert b.video is None or not b.video.isVisible()
    QTest.mouseClick(a, Qt.LeftButton)                                                   # bấm lại → tạm dừng, hiện ▶
    assert pump(qapp, lambda: a.badge.isVisible())
    QTest.mouseClick(b, Qt.LeftButton)                                                   # ô khác phát → ô cũ dừng lại
    assert pump(qapp, lambda: b.video is not None and b.video.isVisible() and b.player.position() > 200)
    assert not a.video.isVisible() and a.badge.isVisible()
    assert pump(qapp, lambda: not b.video.isVisible() and b.badge.isVisible(), timeout=15)   # phát hết → về ảnh đại diện
    win.close()


def test_pencil_edits_prompt_in_place_and_regenerates_same_row(client, qapp):
    """Nút bút ✎: sửa lệnh ngay trong thẻ rồi tạo lại đúng dòng đó (không thêm dòng)."""
    import json as _j
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    from PySide6.QtWidgets import QMessageBox
    qapp.setStyleSheet(QSS)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    client["mgr"].stop()
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.settings.set("out_dir", client["out"])
    win.show()
    win.tab_text.edit.setPlainText("con chó\n\nFAIL con mèo\n")
    win.on_start()
    store, cards = client["store"], win.results.cards
    assert pump(qapp, lambda: len(cards) == 2 and all(store.get(i)["status"] in ("completed", "failed") for i in cards))
    ok_id, bad_id = list(cards)
    assert pump(qapp, lambda: cards[ok_id].pen.isVisible() and cards[bad_id].pen.isVisible())   # bút hiện ở dòng đã xong/lỗi
    old_gw = store.get(bad_id)["gw_id"]

    card = cards[bad_id]
    QTest.mouseClick(card.pen, Qt.LeftButton)                                    # mở ô sửa ngay trong thẻ
    assert card.editor.isVisible() and card.editor.toPlainText() == "FAIL con mèo" and not card.pen.isVisible()
    QTest.mouseClick(card.cancel_btn, Qt.LeftButton)                             # Hủy: không đổi gì
    assert not card.editor.isVisible() and card.pen.isVisible() and store.get(bad_id)["prompt"] == "FAIL con mèo"

    QTest.mouseClick(card.pen, Qt.LeftButton)
    card.editor.setPlainText("con mèo ngủ trên ghế")
    QTest.mouseClick(card.ok_btn, Qt.LeftButton)                                 # Tạo lại với lệnh mới
    assert pump(qapp, lambda: store.get(bad_id)["status"] == "completed" and store.get(bad_id)["gw_id"] != old_gw)
    row = store.get(bad_id)
    assert row["prompt"] == "con mèo ngủ trên ghế" and _j.loads(row["spec_json"])["prompt"] == "con mèo ngủ trên ghế"
    assert len(store.all()) == 2 and list(cards) == [ok_id, bad_id]              # không sinh dòng mới, giữ thứ tự
    assert pump(qapp, lambda: "ngủ" in card.prompt.toolTip() and card.status.text() == "Hoàn thành")

    # sửa ở dòng ĐÃ HOÀN THÀNH cũng được; ô trống thì không gửi
    c2 = cards[ok_id]
    old_ok_gw = store.get(ok_id)["gw_id"]
    QTest.mouseClick(c2.pen, Qt.LeftButton)
    c2.editor.setPlainText("   ")
    QTest.mouseClick(c2.ok_btn, Qt.LeftButton)
    assert c2.editor.isVisible() and store.get(ok_id)["gw_id"] == old_ok_gw       # trống → giữ ô sửa, không gửi
    c2.editor.setPlainText("con chó chạy nhanh hơn")
    QTest.mouseClick(c2.ok_btn, Qt.LeftButton)
    assert pump(qapp, lambda: store.get(ok_id)["gw_id"] != old_ok_gw and store.get(ok_id)["status"] == "completed")
    assert store.get(ok_id)["prompt"] == "con chó chạy nhanh hơn" and len(store.all()) == 2
    win.close()


def test_zalo_group_button_opens_support_group(client, qapp, monkeypatch):
    """Nút Zalo trên thanh công cụ (cạnh Hỗ trợ) và trong hộp thoại Hỗ trợ đều mở đúng nhóm Zalo."""
    from PySide6.QtGui import QDesktopServices
    from autoveo import config
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    qapp.setStyleSheet(QSS)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toString()) or True))
    client["mgr"].stop()
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.show()
    assert config.ZALO_GROUP_URL == "https://zalo.me/g/tw23yenusdo9iezutcww"
    assert not win.results.b_help.icon().isNull() and win.results.b_help.text().strip() == "Hỗ trợ"   # biểu tượng Zalo + chữ
    assert "❓" not in win.results.b_help.text() and not hasattr(win.results, "b_zalo")
    win.results.b_help.click()
    assert opened == [config.ZALO_GROUP_URL]
    win.close()


def test_character_name_matching_is_exact_and_tags_with_at():
    """Tên trong prompt (hoặc @tên) phải khớp CHÍNH XÁC tên đã đặt mới đồng nhất; có dấu/khoảng trắng vẫn ra tag ASCII đúng."""
    from autoveo.ui.tabs.tabs import find_characters, name_slug, tag_characters
    assert find_characters("Lanh đi chợ", ["Lan"]) == []                                  # 'Lan' không được khớp trong 'Lanh'
    assert find_characters("Cô Lan đi chợ", ["Lan"]) == ["Lan"]
    assert tag_characters("Cô Lan và @Baoquoc đi chợ", ["Lan", "Baoquoc"]) == "Cô @Lan và @Baoquoc đi chợ"
    assert tag_characters("@baoquoc chạy, Baoquoc nhảy", ["Baoquoc"]) == "@Baoquoc chạy, @Baoquoc nhảy"   # không thành @@
    assert name_slug("Bé Na") == "Be_Na" and name_slug("Đức Thoại") == "Duc_Thoai" and name_slug("###") == ""
    assert tag_characters("Bé Na ăn kem, bé_na cười", ["Bé Na"]) == "@Be_Na ăn kem, @Be_Na cười"
    assert find_characters("be na ăn kem", ["Bé Na"]) == []                               # thiếu dấu thì KHÔNG khớp (tên chính xác)


def test_characters_tab_rules_names_voice_and_layout(client, qapp):
    """Tab Đồng bộ nhân vật giống Veo3 Go: mỗi ảnh phải có tên, tối đa 10, chọn giọng đọc, × để bỏ."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from autoveo.ui.tabs.tabs import CharactersTab, MAX_CHARACTERS
    from autoveo.ui.theme import QSS
    from autoveo.voices import VOICES
    qapp.setStyleSheet(QSS)
    t = CharactersTab()
    t.resize(700, 600)
    t.show()
    imgs = [make_image(client["tmp"] / f"c{n}.png", (20 * n % 255, 90, 160)) for n in range(12)]
    assert t.add.text() == "📷 Chọn ảnh nhân vật (tối đa 10)" and t.voice.itemText(0) == "🔊 Chọn giọng đọc"
    assert t.voice.count() == 31 and len(VOICES) == 30 and t.voice.itemData(1) == "achernar"
    assert all(" - " in t.voice.itemText(i) for i in range(1, 31))                        # có mô tả nam/nữ, cao độ
    t.add_files(imgs)
    assert len(t.rows) == MAX_CHARACTERS == 10 and t.add.text() == "📷 Chọn ảnh nhân vật (10/10)"   # tối đa 10
    assert t.rows[0].name.placeholderText() == "Đặt tên nhân vật cho ảnh này..."
    res = t.build("16:9", ["720p"])                                                       # chưa đặt tên → báo lỗi rõ
    assert res.errors and "chưa có tên" in res.errors[0] or "chưa có tên" in " ".join(res.errors)
    for row in t.rows[3:]:
        QTest.mouseClick(row.x, Qt.LeftButton)                                            # × bỏ nhân vật
    qapp.processEvents()
    assert len(t.rows) == 3 and t.add.text() == "📷 Chọn ảnh nhân vật (3/10)"
    for row, nm in zip(t.rows, ("Linhchi", "Bé Na", "Baoquoc")):
        row.name.setText(nm)
    t.edit.setPlainText("Linhchi chào Bé Na ở công viên\n\n@Baoquoc chạy nhanh\n\nKhông ai cả")
    t.voice.setCurrentIndex(t.voice.findData("aoede"))
    res = t.build("16:9", ["1080p"])
    assert not res.errors and len(res.specs) == 2
    a, b = res.specs
    assert a.mode == "components" and a.voice == "aoede" and b.voice == "aoede"
    assert a.prompt.startswith("@Linhchi chào @Be_Na") and [i["name"] for i in a.images] == ["Linhchi", "Be_Na"]
    assert b.prompt == "@Baoquoc chạy nhanh" and any("Prompt 3" in w for w in res.warnings)
    t.rows[0].name.setText("Bé  na")                                                      # trùng tên (sau chuẩn hóa) → lỗi
    t.rows[1].name.setText("be na")
    assert any("trùng tên" in e for e in t.build("16:9", ["720p"]).errors)
    t.voice.setCurrentIndex(0)                                                            # không chọn giọng → rỗng
    t.rows[1].name.setText("Bé Nam")
    assert t.build("16:9", ["720p"]).specs[0].voice == ""
    t.close()


def test_characters_end_to_end_sends_voice_and_named_refs(client, qapp, monkeypatch):
    """Từ cửa sổ chính: tab nhân vật + giọng đọc → Gateway (mock) nhận đúng voice + tên @tag → video xong."""
    from autoveo.ui.main_window import MainWindow
    from autoveo.ui.theme import QSS
    from PySide6.QtWidgets import QMessageBox
    from gateway.glabs import MockGLabs
    seen = []
    orig = MockGLabs.submit

    async def rec(self, kind, payload):
        seen.append(payload)
        return await orig(self, kind, payload)
    monkeypatch.setattr(MockGLabs, "submit", rec)
    qapp.setStyleSheet(QSS)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    client["mgr"].stop()
    win = MainWindow(client["settings"], client["session"], client["store"])
    win.settings.set("out_dir", client["out"])
    win.show()
    win.tabs.setCurrentWidget(win.tab_chars)
    t = win.tab_chars
    t.add_files([make_image(client["tmp"] / "hero.png")])
    t.rows[0].name.setText("Linhchi")
    t.edit.setPlainText("Linhchi waves at the camera")
    t.voice.setCurrentIndex(t.voice.findData("kore"))
    win.on_start()
    assert pump(qapp, lambda: len(win.results.cards) == 1 and all(c.status.text() == "Hoàn thành" for c in win.results.cards.values()))
    p = seen[-1]
    assert p["mode"] == "components" and p["voice"] == "kore" and p["prompt"].startswith("@Linhchi waves")
    assert p["reference_images"][0]["name"] == "Linhchi.jpg"
    win.close()
