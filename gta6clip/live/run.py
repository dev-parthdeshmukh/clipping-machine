"""`gta6clip --live twitch:kaicenat youtube:@IShowSpeed`: record every channel the moment it goes
live, detect chat (Twitch) and loudness spikes, and turn each spike into a house-style clip
within a few minutes. Ctrl+C (or --for SECONDS) stops cleanly; recordings are kept."""

import datetime
import json
import shutil
import threading
import time

from .. import config, post
from ..util import log, pcm
from . import chat, clipper, detect, record

import numpy as np


def _audio_loop(rec, book, stop, chunk=30.0):
    """Per-second loudness of the session being recorded, fed to the audio detector."""
    det, sess, offset = None, None, 0.0
    while not stop.is_set():
        cur = rec.current()
        if cur is None:
            stop.wait(5)
            continue
        if cur is not sess:
            sess, offset, det = cur, 0.0, detect.AudioSpikeDetector(rec.name)
        if sess.written() - offset < chunk + 5:
            stop.wait(5)
            continue
        try:
            x = pcm(sess.path, 8000, offset, chunk)
        except RuntimeError:
            stop.wait(10)
            continue
        n = len(x) // 8000
        for i in range(n):
            sec = x[i * 8000:(i + 1) * 8000]
            db = float(20 * np.log10(np.sqrt((sec ** 2).mean()) + 1e-6))
            for ev in det.feed(sess.start_wall + offset + i, db):
                if book.add(ev):
                    log(f"AUDIO SPIKE {rec.name}: +{ev.stats['rise_db']} dB for {ev.stats['seconds']}s", "ok")
        offset += max(n, 1)


def _chat_loop(rec, log_path, book, stop):
    det, offset = detect.ChatSpikeDetector(rec.name), 0
    while not stop.is_set():
        recs, offset = chat.read_new(log_path, offset)
        for r in recs:
            for ev in det.feed(r):
                if book.add(ev):
                    log(f"CHAT SPIKE {rec.name}: {ev.stats['peak_count']} msgs/10s "
                        f"({ev.stats['peak_ratio']}x)", "ok")
        stop.wait(1.0)


def cleanup(rec, book, failed=None):
    """Delete recordings that are finished with: the session has ended, no spike inside it is
    still waiting to be clipped, and no clip from it failed (those are kept for a retry).
    Returns the deleted paths."""
    failed = book.failed if failed is None else failed
    deleted = []
    waiting = book.pending()
    with rec.lock:
        keep = []
        for s in rec.sessions:
            busy = s.end_wall is None or str(s.path) in failed or any(
                s.start_wall <= e.spike_ts <= s.end_wall for e in waiting if e.channel == rec.name)
            if busy:
                keep.append(s)
                continue
            try:
                s.path.unlink(missing_ok=True)
                deleted.append(s.path)
                log(f"{rec.name}: clips done, deleted recording {s.path.name}", "ok")
            except OSError as exc:
                log(f"{rec.name}: could not delete {s.path.name} ({exc})", "warn")
                keep.append(s)
        rec.sessions = keep
    return deleted


def _worker(recorders, book, stop, cfg, day_dir):
    """One clip at a time (the GPU is shared): wait for the footage after each spike, then clip."""
    made, failed = {}, book.failed
    while not stop.is_set() or book.pending():
        for rec in recorders.values():
            cleanup(rec, book, failed)
        ready = []
        for ev in book.pending():
            rec = recorders[ev.channel]
            sess = rec.session_at(ev.spike_ts)
            if sess is None:
                book.take(ev)
                continue
            if sess.end_wall is not None or time.time() >= ev.spike_ts + clipper.POST + 10:
                ready.append((ev, rec, sess))
        if not ready:
            if stop.is_set():
                break
            stop.wait(5)
            continue
        ev, rec, sess = ready[0]
        book.take(ev)
        outdir = day_dir / f"{rec.name.lower()}__live"
        work = config.HOME / "work" / "live" / rec.name.lower()
        outdir.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        clips = made.setdefault(rec.name, [])
        try:
            r = clipper.make_clip(ev, sess, len(clips) + 1, work, outdir, cfg, rec.name)
        except Exception as exc:
            log(f"{ev.event_id}: clip failed ({str(exc)[:200]}); keeping {sess.path.name}", "err")
            failed.add(str(sess.path))
            continue
        if r:
            clips.append(r)
            stream = {"name": rec.name, "title": f"{rec.name} live ({rec.platform})", "url": rec.url}
            post.write(outdir, stream, clips, f"live clipping, {len(clips)} clip(s) so far")
            log(f"-> {outdir / r['file']}", "ok")
    for rec in recorders.values():
        cleanup(rec, book, failed)
    return made


def main(sources, cookies_file=None, duration=None):
    cfg = config.load()
    streamlink = shutil.which("streamlink")
    if not streamlink:
        raise SystemExit("streamlink not found: run setup.ps1")
    stop, book = threading.Event(), detect.EventBook(merge_window=45)
    day_dir = config.HOME / datetime.date.today().isoformat()
    rec_dir = config.HOME / "recordings"
    recorders, threads, rec_threads = {}, [], []
    for src in sources:
        rec = record.Recorder(src, rec_dir / record.stream_url(src)[2].lower(), streamlink,
                              cookies_file if record.stream_url(src)[1] == "youtube" else None, stop)
        recorders[rec.name] = rec
        jobs = [rec.run_forever, lambda r=rec: _audio_loop(r, book, stop)]
        if rec.platform == "twitch":
            chat_log = config.HOME / "chat" / rec.name / "chat.log"
            jobs += [chat.ChatReader(rec.name, chat_log, stop).run_forever,
                     lambda r=rec, p=chat_log: _chat_loop(r, p, book, stop)]
        for fn in jobs:
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            threads.append(t)
            if fn == rec.run_forever:
                rec_threads.append(t)
    log(f"live mode: watching {', '.join(recorders)} - Ctrl+C to stop", "step")
    if duration:
        threading.Timer(duration, stop.set).start()
    worker = threading.Thread(target=lambda: _worker(recorders, book, stop, cfg, day_dir), daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(1.0)
    except KeyboardInterrupt:
        log("stopping: finishing clips for spikes already recorded...", "warn")
        stop.set()
        worker.join()
    stop.set()
    for t in rec_threads:                 # let every recorder stop streamlink and close its file
        t.join(timeout=30)
    for rec in recorders.values():        # sessions are closed now: delete the finished ones
        cleanup(rec, book)
    log("live mode stopped (finished recordings deleted; any kept for a failed clip are in " + str(rec_dir) + ")", "ok")
