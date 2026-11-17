"""Record live channels with Streamlink.

One .ts file per broadcast. A broadcast's clock starts when its first bytes reach the disk
(start_wall), the same PC clock the chat log uses, so chat spikes map onto the video."""

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..util import log


def stream_url(source):
    """'twitch:login' / 'youtube:@handle' / a URL -> (url, platform, name)."""
    s = source.strip()
    if s.lower().startswith("twitch:"):
        name = s.split(":", 1)[1].lower()
        return f"https://twitch.tv/{name}", "twitch", name
    if s.lower().startswith("youtube:"):
        h = s.split(":", 1)[1].lstrip("@")
        return f"https://www.youtube.com/@{h}/live", "youtube", h
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", s)
    if m:
        return s, "twitch", m.group(1).lower()
    m = re.search(r"youtube\.com/@([A-Za-z0-9_.-]+)", s)
    return s, "youtube", (m.group(1) if m else "youtube")


def _cookie_args(cookies_file, url):
    """--http-cookie NAME=VALUE for every cookies.txt line whose domain matches the stream's site."""
    if not cookies_file:
        return []
    site = "youtube.com" if "youtube" in url else "twitch.tv"
    args = []
    for line in Path(cookies_file).read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split("\t")
        if len(parts) == 7 and not line.startswith("#") and parts[0].lstrip(".").endswith(site):
            args += ["--http-cookie", f"{parts[5]}={parts[6]}"]
    return args


def kill_tree(proc):
    """Stop streamlink and its children. On Windows streamlink.exe is a launcher with a Python
    child, so a plain terminate() would leave the recording running."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def command(streamlink, url, out_path, quality="best", cookies_file=None):
    return [str(streamlink), url, quality, "-o", str(out_path), "--retry-streams", "30",
            "--retry-open", "3", "--force", *_cookie_args(cookies_file, url)]


@dataclass
class Session:
    path: Path
    start_wall: float
    end_wall: float = None          # None while still recording

    def written(self):
        """Seconds of stream on disk so far (approximate for a session still recording)."""
        return (self.end_wall or time.time()) - self.start_wall


class Recorder:
    def __init__(self, source, out_dir, streamlink, cookies_file=None, stop=None):
        self.url, self.platform, self.name = stream_url(source)
        self.out_dir, self.streamlink, self.cookies_file = Path(out_dir), streamlink, cookies_file
        self.stop = stop or threading.Event()
        self.sessions, self.lock = [], threading.Lock()

    def session_at(self, wall):
        with self.lock:
            for s in self.sessions:
                if s.start_wall <= wall and (s.end_wall is None or wall <= s.end_wall):
                    return s
        return None

    def current(self):
        with self.lock:
            return self.sessions[-1] if self.sessions and self.sessions[-1].end_wall is None else None

    def _watch(self, proc, path):
        """Follow one streamlink run: open a Session when the first bytes land, close it when
        the file stops growing because streamlink exited (or we were told to stop)."""
        sess, size, grew = None, 0, time.time()
        while proc.poll() is None and not self.stop.is_set():
            now_size = path.stat().st_size if path.exists() else 0
            if now_size and sess is None:
                sess = Session(path, time.time())
                with self.lock:
                    self.sessions.append(sess)
                log(f"LIVE: recording {self.name} -> {path.name}", "ok")
            if now_size > size:
                size, grew = now_size, time.time()
            self.stop.wait(1.0)
        kill_tree(proc)
        return sess, grew

    def run_forever(self):
        """Wait for the channel, record it, and go back to waiting when it ends."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        while not self.stop.is_set():
            path = self.out_dir / f"{self.name}_{time.strftime('%Y%m%d-%H%M%S')}.ts"
            log(f"waiting for {self.name} to go live ({self.platform})", "step")
            proc = subprocess.Popen(command(self.streamlink, self.url, path, cookies_file=self.cookies_file),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sess, last_growth = self._watch(proc, path)
            if sess is None:
                if path.exists() and path.stat().st_size == 0:
                    path.unlink()
            else:
                sess.end_wall = last_growth
                log(f"{self.name}: session ended after {sess.written() / 60:.0f} min", "ok")
            self.stop.wait(5)
