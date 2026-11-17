"""Getting media with yt-dlp, cheaply: the whole stream only as audio (for listening), and video
only for the stretches that become clips."""

import json
import shutil
from pathlib import Path

from .util import log, run

INFO_KEYS = ("id", "title", "channel", "uploader", "duration", "view_count", "live_status", "was_live",
             "is_live", "webpage_url", "extractor_key", "timestamp", "release_timestamp")


def base_args(url, cookies=None, cookies_file=None):
    """Extra yt-dlp arguments: a JS runtime for YouTube (deno is found on its own; otherwise
    node/bun is named explicitly), and login cookies from a file or a browser."""
    out = []
    if "youtu" in url and not shutil.which("deno"):
        runtime = next(((n, shutil.which(n)) for n in ("node", "bun") if shutil.which(n)), None)
        if runtime:
            out += ["--js-runtimes", f"{runtime[0]}:{runtime[1]}"]
    if cookies_file:
        out += ["--cookies", str(cookies_file)]
    elif cookies:
        out += ["--cookies-from-browser", cookies]
    return out


def info(url, args, workdir, refresh=False):
    """Title, channel, length and live state of a stream, remembered in workdir/info.json."""
    saved = workdir / "info.json"
    if saved.exists() and not refresh:
        return json.loads(saved.read_text(encoding="utf-8"))
    meta = json.loads(run(["yt-dlp", "-J", "--no-playlist", *args, url], timeout=180))
    data = {k: meta.get(k) for k in INFO_KEYS}
    data["name"] = data["channel"] or data["uploader"] or "stream"
    data["title"] = data["title"] or "stream"
    saved.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _finished_audio(workdir):
    return next((p for p in sorted(workdir.glob("audio.*")) if p.suffix not in (".part", ".ytdl")), None)


def audio(url, args, workdir, refresh=False):
    """The full stream as an audio file in workdir (downloaded once, unless refresh)."""
    if refresh:
        for f in workdir.glob("audio.*"):
            f.unlink(missing_ok=True)
    have = _finished_audio(workdir)
    if have:
        log(f"reusing downloaded audio ({have.stat().st_size / 1e6:.0f} MB)", "ok")
        return have
    log("downloading the stream's audio (video only for the clips, later)...", "step")
    run(["yt-dlp", "--no-playlist", "-f", "ba/wa/w", "-N", "4", "--newline",
         "-o", str(workdir / "audio.%(ext)s"), *args, url], timeout=7200)
    have = _finished_audio(workdir)
    if not have:
        raise RuntimeError("yt-dlp finished without leaving an audio file")
    log(f"audio: {have.stat().st_size / 1e6:.0f} MB", "ok")
    return have


def section(url, args, start, end, dest, cfg):
    """Video (max cfg["max_height"]) of seconds [start, end] of the stream, as mp4."""
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    for stale in dest.parent.glob(dest.name + "*"):
        stale.unlink(missing_ok=True)
    h = cfg["max_height"]
    run(["yt-dlp", "--no-playlist", "--merge-output-format", "mp4",
         "-f", f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
         "--download-sections", f"*{max(0.0, start):.2f}-{end:.2f}",
         "-o", str(dest), *args, url], timeout=1800)
    if not Path(dest).exists():
        raise RuntimeError(f"no video came back for {start:.0f}-{end:.0f}s")
    return dest
