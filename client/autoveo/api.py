"""Gọi mạng: phiên đăng nhập (thoai-dash /api/veo) và Gateway (/v1). Đồng bộ, an toàn đa luồng."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import httpx

from . import config
from .secrets_store import load_secret, save_secret


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    @property
    def is_network(self) -> bool:
        return self.status == 0


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True,
                        headers={"User-Agent": f"{config.APP_NAME}/{config.VERSION}"})


def _check(resp: httpx.Response) -> dict | list:
    if resp.status_code >= 400:
        code, msg = "error", f"Lỗi máy chủ ({resp.status_code})"
        try:
            d = resp.json().get("detail")
            if isinstance(d, dict):
                code, msg = d.get("code", code), d.get("message", msg)
            elif isinstance(d, str):
                msg = d
        except ValueError:
            pass
        raise ApiError(resp.status_code, code, msg)
    try:
        return resp.json()
    except ValueError:
        raise ApiError(resp.status_code, "bad_json", "Máy chủ trả dữ liệu không hợp lệ")


def _net_error(e: Exception) -> ApiError:
    return ApiError(0, "network", "Không kết nối được máy chủ. Kiểm tra Internet.")


class Session:
    """Giữ refresh token (mã hóa DPAPI) và access token ngắn hạn; tự làm mới khi sắp hết hạn."""

    def __init__(self, settings: config.Settings):
        self.settings = settings
        self.http = _client()
        self._lock = threading.Lock()
        self._secret_file = config.data_dir() / "session.bin"
        self.refresh_token: str | None = load_secret(self._secret_file)
        self.access_token: str | None = None
        self.access_exp = 0.0
        self.on_signed_out: Callable[[], None] | None = None

    @property
    def account_url(self) -> str:
        return self.settings["account_url"].rstrip("/")

    @property
    def signed_in(self) -> bool:
        return bool(self.refresh_token)

    # ---- đăng nhập thiết bị ----
    def login_start(self) -> dict:
        try:
            r = self.http.post(f"{self.account_url}/api/veo/device/start",
                               json={"machine_hash": config.machine_hash(), "device_name": config.device_name()})
        except httpx.HTTPError as e:
            raise _net_error(e)
        return _check(r)

    def login_poll(self, device_code: str) -> dict:
        try:
            r = self.http.post(f"{self.account_url}/api/veo/device/poll", json={"device_code": device_code})
        except httpx.HTTPError as e:
            raise _net_error(e)
        d = _check(r)
        if d.get("status") == "approved":
            self._store(d["access_token"], d["expires_in"], d["refresh_token"])
        return d

    def _store(self, access: str, expires_in: int, refresh: str | None = None) -> None:
        self.access_token = access
        self.access_exp = time.time() + int(expires_in)
        if refresh:
            self.refresh_token = refresh
            save_secret(self._secret_file, refresh)

    def logout(self) -> None:
        with self._lock:
            self.refresh_token = self.access_token = None
            self.access_exp = 0
            self._secret_file.unlink(missing_ok=True)

    # ---- token ----
    def token(self, force: bool = False) -> str:
        with self._lock:
            if not self.refresh_token:
                raise ApiError(401, "not_signed_in", "Chưa đăng nhập")
            if force or not self.access_token or time.time() > self.access_exp - 120:
                try:
                    r = self.http.post(f"{self.account_url}/api/veo/token/refresh",
                                       json={"refresh_token": self.refresh_token, "machine_hash": config.machine_hash()})
                except httpx.HTTPError as e:
                    raise _net_error(e)
                try:
                    d = _check(r)
                except ApiError as e:
                    if e.status == 401:       # thiết bị bị gỡ / phiên hỏng: phải đăng nhập lại
                        self.refresh_token = self.access_token = None
                        self._secret_file.unlink(missing_ok=True)
                        if self.on_signed_out:
                            self.on_signed_out()
                    raise
                self._store(d["access_token"], d["expires_in"])
            return self.access_token  # type: ignore[return-value]

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        """Gửi kèm token; gặp token hết hạn thì làm mới và thử lại đúng một lần."""
        extra = kw.pop("headers", {})
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self.token(force=attempt == 1)}", **extra}
            try:
                r = self.http.request(method, url, headers=headers, **kw)
            except httpx.HTTPError as e:
                raise _net_error(e)
            if r.status_code == 401 and attempt == 0:
                continue
            return r
        return r  # pragma: no cover


class AccountApi:
    def __init__(self, session: Session):
        self.s = session

    def _u(self, path: str) -> str:
        return f"{self.s.account_url}/api/veo{path}"

    def plans(self) -> list:
        try:
            return _check(self.s.http.get(self._u("/plans")))
        except httpx.HTTPError as e:
            raise _net_error(e)

    def me(self) -> dict:
        return _check(self.s.request("GET", self._u("/me")))

    def create_order(self, plan_code: str, months: int) -> dict:
        return _check(self.s.request("POST", self._u("/orders"), json={"plan_code": plan_code, "months": months}))

    def get_order(self, code: str) -> dict:
        return _check(self.s.request("GET", self._u(f"/orders/{code}")))

    def fetch_bytes(self, url: str) -> bytes:
        try:
            r = self.s.http.get(url)
        except httpx.HTTPError as e:
            raise _net_error(e)
        if r.status_code != 200:
            raise ApiError(r.status_code, "fetch", "Không tải được ảnh QR")
        return r.content


class GatewayApi:
    def __init__(self, session: Session):
        self.s = session

    @property
    def base(self) -> str:
        return self.s.settings["gateway_url"].rstrip("/")

    def health(self) -> dict:
        try:
            return _check(self.s.http.get(f"{self.base}/v1/health", timeout=10))
        except httpx.HTTPError as e:
            raise _net_error(e)

    def me(self) -> dict:
        return _check(self.s.request("GET", f"{self.base}/v1/me"))

    def submit_batch(self, jobs: list[dict]) -> list[dict]:
        return _check(self.s.request("POST", f"{self.base}/v1/batches", json={"jobs": jobs}, timeout=300))["jobs"]

    def status(self, ids: list[str]) -> list[dict]:
        return _check(self.s.request("POST", f"{self.base}/v1/jobs/status", json={"ids": ids}))["jobs"]

    def cancel(self, job_id: str) -> dict:
        return _check(self.s.request("POST", f"{self.base}/v1/jobs/{job_id}/cancel"))

    def latest_version(self) -> dict:
        return _check(self.s.http.get(f"{self.base}/v1/client/latest", timeout=10))

    def download(self, url_path: str, dest: Path, progress: Callable[[int, int], None] | None = None) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self.s.token(force=attempt == 1)}"}
            try:
                with self.s.http.stream("GET", self.base + url_path, headers=headers,
                                        timeout=httpx.Timeout(120.0, connect=10.0)) as r:
                    if r.status_code == 401 and attempt == 0:
                        continue
                    if r.status_code != 200:
                        raise ApiError(r.status_code, "download", f"Tải file lỗi ({r.status_code})")
                    total = int(r.headers.get("content-length") or 0)
                    got = 0
                    with tmp.open("wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            f.write(chunk)
                            got += len(chunk)
                            if progress:
                                progress(got, total)
                tmp.replace(dest)
                return
            except httpx.HTTPError as e:
                raise _net_error(e)


def check_update(session: Session) -> dict | None:
    """Trả {'version','url'} nếu có bản mới hơn (đọc latest.json ở trang tải), lỗi mạng thì bỏ qua."""
    try:
        d = session.http.get(f"{session.account_url}/veo3/latest.json", timeout=8).json()
        ver = str(d.get("version", ""))
    except (httpx.HTTPError, ValueError):
        return None

    def key(v: str):
        return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))
    if ver and key(ver) > key(config.VERSION):
        return {"version": ver, "url": d.get("url") or config.DOWNLOAD_PAGE_URL}
    return None
