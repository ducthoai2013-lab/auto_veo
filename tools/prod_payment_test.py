"""Test thanh toán THẬT trên production: dựng thiết bị thử + gói thử 2.000đ, tạo đơn AV3-…, lấy QR, chờ SePay báo tiền.

  python tools/prod_payment_test.py create   # tạo đơn, lưu QR ra secrets/backups/qr_test.png, in thông tin chuyển khoản
  python tools/prod_payment_test.py wait     # chờ đơn thành 'paid', rồi kiểm tra gói/kích hoạt/D100
  python tools/prod_payment_test.py cleanup  # gỡ thiết bị thử, tắt gói thử (giữ đơn/giao dịch làm bằng chứng)

Chỉ ghi vào bảng veo_* (team giả 'smoke-test-team'), KHÔNG đụng bảng D100. Tiền chuyển là THẬT (2.000đ).
Bí mật (khóa ký) chỉ đọc cục bộ; token thử sống 1 giờ; không in ra.
"""
import json
import pathlib
import subprocess
import sys
import time
import uuid

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from gateway.admin import sign_token  # noqa: E402

BASE = "https://d100radar.com"
STATE = ROOT / "secrets" / "backups" / "prod_pay_state.json"
SSH = ["ssh", "-i", str(pathlib.Path.home() / ".ssh" / "khop_deploy_key"), "-p", "24201", "-o", "BatchMode=yes", "root@104.36.21.215"]
PSQL = "docker exec -i thoai-postgres sh -c 'psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -v ON_ERROR_STOP=1 -At'"
TEAM, USER, PLAN, AMOUNT = "smoke-test-team", "smoke-test-user", "smoke_test", 2000


def sql(text: str) -> str:
    p = subprocess.run(SSH + [PSQL], input=text, capture_output=True, text=True, timeout=90)
    if p.returncode != 0:
        sys.exit("SQL lỗi: " + p.stderr[-300:])
    return p.stdout.strip()


def token(state) -> dict:
    priv = (ROOT / "secrets" / "veo" / "veo_private.pem").read_text()
    t = sign_token(priv, team=TEAM, email="smoke-test@d100radar.local", device=state["device_id"], plan="trial", plan_name="Test",
                   cc=1, ttl=3600)
    return {"Authorization": "Bearer " + t}


def create():
    if sql(f"select count(*) from veo_devices where team_id='{TEAM}' and status='active';") != "0":
        sys.exit("Đã có thiết bị thử đang hoạt động, chạy cleanup trước")
    dev = "smoketest-" + uuid.uuid4().hex[:12]
    sql(f"""
insert into veo_plans(id,code,name,price_month,max_concurrent,max_devices,video_quota,quota_period,allow_4k,is_active,sort_order,created_at)
values ('{uuid.uuid4().hex}','{PLAN}','TEST thanh toán 2.000đ',{AMOUNT},1,1,NULL,'total',false,true,99,now() at time zone 'utc')
on conflict (code) do update set price_month={AMOUNT}, is_active=true;
insert into veo_devices(id,team_id,user_id,machine_hash,name,status,refresh_hash,created_at,last_seen)
values ('{dev}','{TEAM}','{USER}','smoke-test-machine-0001','SMOKE-TEST','active','{uuid.uuid4().hex}{uuid.uuid4().hex}',now() at time zone 'utc',now() at time zone 'utc');
""")
    state = {"device_id": dev}
    r = httpx.post(f"{BASE}/api/veo/orders", json={"plan_code": PLAN, "months": 1}, headers=token(state), timeout=30)
    # tắt gói thử NGAY (đơn đã giữ plan_id; kích hoạt không cần gói đang bật) để người dùng thật không thấy nó
    sql(f"update veo_plans set is_active=false where code='{PLAN}';")
    if r.status_code != 200:
        sys.exit(f"Tạo đơn lỗi HTTP {r.status_code}: {r.text[:200]}")
    o = r.json()
    state.update(order_code=o["order_code"], amount=o["amount"])
    STATE.write_text(json.dumps(state), encoding="utf-8")
    png = ROOT / "secrets" / "backups" / "qr_test.png"
    png.write_bytes(httpx.get(o["qr_url"], timeout=30, follow_redirects=True).content)
    print(json.dumps({k: o[k] for k in ("order_code", "amount", "transfer_content", "bank_short_name", "bank_account_no",
                                         "bank_account_name", "expires_at", "status")}, ensure_ascii=False, indent=2))
    print("QR:", png, png.stat().st_size, "bytes")


def wait(minutes: int = 12):
    st = json.loads(STATE.read_text(encoding="utf-8"))
    end = time.time() + minutes * 60
    status = "pending"
    while time.time() < end:
        r = httpx.get(f"{BASE}/api/veo/orders/{st['order_code']}", headers=token(st), timeout=30)
        status = r.json().get("status") if r.status_code == 200 else f"HTTP {r.status_code}"
        if status != "pending":
            break
        time.sleep(5)
    print("trạng thái đơn:", status)
    if status == "paid":
        print(sql(f"select 'giao dịch SePay: '||gateway||' '||status||' '||amount from veo_payment_txns where order_code='{st['order_code']}';"))
        print(sql(f"select 'subscription: plan='||p.code||' status='||s.status||' hết hạn '||to_char(s.expires_at,'YYYY-MM-DD') "
                  f"from veo_subscriptions s join veo_plans p on p.id=s.plan_id where s.team_id='{TEAM}';"))
        print(sql("select 'D100 subscriptions active: '||count(*) from subscriptions where status='active';"))
    sys.exit(0 if status == "paid" else 1)


def cleanup():
    st = json.loads(STATE.read_text(encoding="utf-8"))
    print(sql(f"update veo_devices set status='revoked' where team_id='{TEAM}'; update veo_plans set is_active=false where code='{PLAN}'; "
              f"select 'thiết bị thử đã gỡ, gói thử đã tắt';"))
    print("Đơn/giao dịch/subscription của team thử được GIỮ lại làm bằng chứng:", st["order_code"])


{"create": create, "wait": wait, "cleanup": cleanup}[sys.argv[1]]()
