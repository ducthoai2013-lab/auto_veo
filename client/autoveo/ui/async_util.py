"""Chạy hàm chậm (gọi mạng) ở luồng nền và trả kết quả về luồng giao diện."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_alive: set = set()


class _Sig(QObject):
    done = Signal(object)
    error = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable, sig: _Sig):
        super().__init__()
        self.fn, self.sig = fn, sig
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            res = self.fn()
        except Exception as e:  # noqa: BLE001 - trả lỗi về giao diện
            self._emit(self.sig.error, e)
        else:
            self._emit(self.sig.done, res)

    @staticmethod
    def _emit(signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:   # cửa sổ đã đóng, đối tượng nhận đã bị hủy
            pass


def run_async(fn: Callable, on_done: Callable | None = None, on_error: Callable | None = None) -> None:
    sig = _Sig()
    task = _Task(fn, sig)
    _alive.add(task)

    def cleanup(*_):
        _alive.discard(task)

    if on_done:
        sig.done.connect(on_done)
    if on_error:
        sig.error.connect(on_error)
    sig.done.connect(cleanup)
    sig.error.connect(cleanup)
    task.sig = sig  # giữ tham chiếu
    QThreadPool.globalInstance().start(task)
