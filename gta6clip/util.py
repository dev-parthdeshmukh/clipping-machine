"""Small shared helpers: logging, running tools, decoding audio, probing media, naming files."""

import functools
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import numpy as np

if hasattr(sys.stdout, "reconfigure"):          # emoji in logs on a cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Tools installed in the private venv (yt-dlp, streamlink) live next to its python.exe.
_SCRIPTS = os.path.dirname(sys.executable)
if _SCRIPTS not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _SCRIPTS + os.pathsep + os.environ.get("PATH", "")

_T0 = time.time()
_out_lock = threading.Lock()
_thread = threading.local()
MARKS = {"info": "·", "ok": "✓", "warn": "!", "err": "✗", "step": "▸"}


def set_tag(tag):
    """Label every log line from the current thread (one thread per stream)."""
    _thread.tag = tag


def log(msg, level="info"):
    mins, secs = divmod(int(time.time() - _T0), 60)
    tag = getattr(_thread, "tag", "")
    with _out_lock:
        print(f"{MARKS.get(level, '·')} [{mins:02d}:{secs:02d}] {f'[{tag}] ' if tag else ''}{msg}", flush=True)


def die(msg):
    log(msg, "err")
    sys.exit(1)


def run(cmd, capture=True, check=True, timeout=None):
    """Run a program; return its stdout. Raises RuntimeError with the last lines of its output
    when it fails. Child Python tools are told to speak UTF-8."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    res = subprocess.run([str(c) for c in cmd], capture_output=capture, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout, env=env)
    if check and res.returncode:
        said = (res.stderr or res.stdout or "").strip().splitlines()[-15:]
        raise RuntimeError(f"command failed ({res.returncode}): {cmd[0]}\n" + "\n".join(said))
    return res.stdout or "" if capture else ""


def pcm(path, rate, start=None, duration=None):
    """Mono float32 samples at `rate` Hz, decoded by ffmpeg straight into memory."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    cmd += ["-ss", f"{max(0.0, start):.3f}"] if start is not None else []
    cmd += ["-i", str(path)]
    cmd += ["-t", f"{duration:.3f}"] if duration is not None else []
    res = subprocess.run(cmd + ["-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], capture_output=True)
    if res.returncode:
        raise RuntimeError(f"ffmpeg could not decode {path}: {res.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(res.stdout, dtype="<i2").astype(np.float32) / 32768.0


def probe(path):
    """{"width", "height", "duration", "fps"} of a media file (0 x 0 when it has no picture)."""
    meta = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                           "-show_format", str(path)]))
    vid = next((s for s in meta["streams"] if s.get("codec_type") == "video"), {})
    num, _, den = (vid.get("avg_frame_rate") or "0/0").partition("/")
    try:
        fps = float(num) / float(den) if float(den) else 0.0
    except ValueError:
        fps = 0.0
    return {"width": int(vid.get("width", 0)), "height": int(vid.get("height", 0)),
            "duration": float(meta["format"].get("duration") or 0), "fps": fps or 30.0}


def hhmmss(seconds):
    s = max(0, int(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def minutes(seconds):
    """Human length: '40 s', '12 min', '4 h 09 min'."""
    s = round(seconds)
    if s < 60:
        return f"{s} s"
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def slugify(text, limit=48):
    """Lower-case letters and digits (any alphabet), other runs of space/-/_ become one '-'.
    Safe as a Windows file or folder name."""
    parts, word = [], ""
    for ch in (text or "").lower():
        if ch.isalnum():
            word += ch
        elif ch in " -_" and word:
            parts.append(word)
            word = ""
    if word:
        parts.append(word)
    return "-".join(parts)[:limit].strip("-") or "clip"


def even(n):
    """Nearest even integer at or below round(n) (video sizes must be even)."""
    return int(round(n)) // 2 * 2


def ass_path(path):
    """A path written the way ffmpeg filter options want it on Windows: C\\:/dir/file."""
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


@functools.lru_cache(maxsize=1)
def nvenc_available():
    """Does a tiny NVIDIA (h264_nvenc) encode work on this PC?"""
    try:
        run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=s=256x256:d=0.5",
             "-c:v", "h264_nvenc", "-f", "null", "-"], timeout=60)
        return True
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False


class Timer:
    """Adds up how long each named stage took."""

    def __init__(self):
        self.t0, self.stages = time.time(), {}

    @contextmanager
    def stage(self, name):
        began = time.time()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + time.time() - began

    def total(self):
        return time.time() - self.t0
