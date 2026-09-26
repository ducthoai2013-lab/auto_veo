"""ffmpeg đóng gói kèm app: nối video, cắt khung hình cuối, lấy ảnh đại diện."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(Exception):
    pass


def ffmpeg_path() -> str | None:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for cand in (config.app_root() / "ffmpeg" / exe, config.resource_path(f"ffmpeg/{exe}"),
                 config.app_root() / "_internal" / "ffmpeg" / exe):
        if cand.is_file():
            return str(cand)
    return os.getenv("AUTOVEO_FFMPEG") or shutil.which("ffmpeg")


def _run(args: list[str]) -> None:
    exe = ffmpeg_path()
    if not exe:
        raise FFmpegError("Không tìm thấy ffmpeg")
    p = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True,
                       text=True, creationflags=_NOWIN)
    if p.returncode != 0:
        raise FFmpegError((p.stderr or "ffmpeg lỗi").strip()[-300:])


def first_frame(video: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(["-i", str(video), "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", str(out)])


def last_frame(video: Path, out: Path) -> None:
    """Khung hình cuối (dùng làm ảnh đầu cho cảnh kế: 'nối cảnh' của G-Labs)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(["-sseof", "-0.2", "-i", str(video), "-update", "1", "-frames:v", "1", "-q:v", "2", str(out)])
    except FFmpegError:
        _run(["-i", str(video), "-update", "1", "-q:v", "2", str(out)])   # video quá ngắn: lấy khung cuối bằng quét hết
    if not out.is_file():
        raise FFmpegError("Không cắt được khung hình cuối")


def has_audio(video: Path) -> bool:
    """ffmpeg -i in thông tin luồng ra stderr; không cần ffprobe."""
    exe = ffmpeg_path()
    if not exe:
        return False
    p = subprocess.run([exe, "-hide_banner", "-i", str(video)], capture_output=True, text=True, creationflags=_NOWIN)
    return "Audio:" in (p.stderr or "")


def concat(videos: list[Path], out: Path) -> None:
    """Nối theo thứ tự. Thử ghép không mã hóa lại (nhanh, giữ nguyên hình + tiếng); nếu thông số khác nhau
    thì mã hóa lại và GIỮ ÂM THANH (video Veo có AAC). Nếu chỉ một số clip có tiếng thì bỏ tiếng để khỏi lệch."""
    if len(videos) < 2:
        raise FFmpegError("Cần chọn ít nhất 2 video để nối")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{str(v).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                               for v in videos), encoding="utf-8")
        try:
            _run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
        except FFmpegError:
            inputs: list[str] = []
            for v in videos:
                inputs += ["-i", str(v)]
            n = len(videos)
            with_audio = all(has_audio(v) for v in videos)
            flt = "".join(f"[{i}:v:0]scale=1280:720:force_original_aspect_ratio=decrease,"
                          f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v{i}];" for i in range(n))
            if with_audio:
                flt += "".join(f"[{i}:a:0]aresample=48000,aformat=channel_layouts=stereo[a{i}];" for i in range(n))
                flt += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[outv][outa]"
                maps = ["-map", "[outv]", "-map", "[outa]", "-c:a", "aac", "-b:a", "128k"]
            else:
                flt += "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
                maps = ["-map", "[outv]"]
            _run([*inputs, "-filter_complex", flt, *maps, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
