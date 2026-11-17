"""gta6clip: GTA 6 streams in, narrated ready-to-post vertical clips out.

  gta6clip URL [URL ...]        clip these streams
  gta6clip --find               find today's biggest GTA 6 streams and clip them
  gta6clip --find --list        only show what it would clip

Phase 1 (streams in parallel): audio -> listen -> pick (2 Claude passes).
Phase 2 (once): narrate every picked clip's line (VoxCPM2 clone, Kokoro fallback).
Phase 3 (per stream): fetch clip video -> edit, caption, intro -> encode -> POST.md.
Clips land in %USERPROFILE%/gta6-clips/<date>/<streamer>__<title>/. Re-running resumes."""

import argparse
import datetime
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor

from . import config, editor, fetch, find, moments, narrator, post, render, scan
from .util import Timer, die, hhmmss, log, minutes, probe, set_tag, slugify


def parse(argv):
    p = argparse.ArgumentParser(prog="gta6clip", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("urls", nargs="*", help="stream / VOD links (YouTube, Twitch, Kick)")
    p.add_argument("--find", action="store_true", help="find today's biggest GTA 6 streams")
    p.add_argument("--live", action="store_true",
                   help="live mode: the links are channels (twitch:login, youtube:@handle); record them "
                        "while live and clip chat/loudness spikes as they happen")
    p.add_argument("--for", dest="duration", type=int, metavar="SECONDS", help="with --live: stop after this long")
    p.add_argument("--list", action="store_true", help="with --find: only list them")
    p.add_argument("--streams", type=int, default=5, help="with --find: how many streams (default 5)")
    p.add_argument("--clips", type=int, help="clips per stream (default 3)")
    p.add_argument("--bar", type=int, help="minimum score 1-100 (default 70)")
    p.add_argument("--parallel", type=int, default=2, help="streams analysed at once (default 2)")
    p.add_argument("--section", metavar="RANGE", help='only part of the stream, e.g. "1:00:00-3:30:00"')
    p.add_argument("--cookies", choices=["chrome", "edge", "firefox", "brave", "opera"],
                   help="use your browser login (age-restricted YouTube, Kick)")
    p.add_argument("--cookies-file", metavar="PATH",
                   help="an exported cookies.txt (age-restricted YouTube when browser cookies fail)")
    p.add_argument("--layout", choices=["auto", "stream", "face", "fit"])
    p.add_argument("--model", dest="claude_model", help="Claude model for picking, e.g. sonnet")
    p.add_argument("--voice", choices=["voxcpm2", "kokoro"], help="narrator engine (default voxcpm2)")
    p.add_argument("--no-narrator", action="store_true", help="no narrated intro")
    p.add_argument("--keep-audio", action="store_true", help="keep the stream audio after clipping")
    p.add_argument("--redo", action="store_true", help="pick the moments again (keeps the audio)")
    return p.parse_args(argv)


def _seconds(stamp):
    total = 0.0
    for part in stamp.strip().split(":"):
        total = total * 60 + float(part)
    return total


def _require_tools():
    for tool, hint in (("yt-dlp", "run setup.ps1"), ("ffmpeg", "winget install Gyan.FFmpeg")):
        if shutil.which(tool) is None:
            die(f"'{tool}' not found. {hint}")


def analyse_stream(url, cfg, opts):
    """Phase 1 for one stream: everything up to the final picks."""
    timer = Timer()
    args = fetch.base_args(url, opts.cookies, opts.cookies_file)
    work = config.HOME / "work" / re.sub(r"[^A-Za-z0-9_-]", "_", url.split("://")[-1])[-80:]
    work.mkdir(parents=True, exist_ok=True)
    with timer.stage("look up"):
        info = fetch.info(url, args, work)
        live = info.get("live_status") == "is_live"
        if live:                                      # cached info may be stale: ask again
            info = fetch.info(url, args, work, refresh=True)
            live = info.get("live_status") == "is_live"
    set_tag(info["name"][:18])
    if live and "youtube" in (info.get("extractor_key") or "").lower():
        raise RuntimeError("still live on YouTube: it can be clipped once the stream ends "
                           "(or clip the streamer's Twitch VOD link, which works while live)")
    if live:
        log("still live: clipping what has been streamed so far (audio downloaded fresh)", "warn")
        for f in ("scan.json", "loud.json", "chat.json", "candidates.json", "moments.json"):
            (work / f).unlink(missing_ok=True)       # a growing VOD: earlier listening is out of date
    with timer.stage("download audio"):
        audio = fetch.audio(url, args, work, refresh=live)
    length = probe(audio)["duration"]
    lo, hi = 0.0, length
    if opts.section:
        a, _, b = opts.section.lstrip("*").partition("-")
        lo, hi = _seconds(a), (min(_seconds(b), length) if b else length)
    pick_dir = work if not opts.section else work / f"part_{int(lo)}_{int(hi)}"
    pick_dir.mkdir(exist_ok=True)
    if opts.redo:
        for f in ("moments.json", "candidates.json"):
            (pick_dir / f).unlink(missing_ok=True)
    stream = {"name": info["name"], "title": info["title"], "url": url}
    log(f"{info['title'][:70]} · {minutes(length)} of stream", "ok")
    with timer.stage("listen"):
        heard = scan.transcript(audio, lo, hi, pick_dir, cfg)
        loud = scan.relative(scan.loudness(audio, work))
        chat = scan.chat_rate(url, args, work, cfg, info)
    with timer.stage("pick"):
        cands = moments.candidates(heard, loud, chat, pick_dir, cfg, stream)
        finals = editor.finalize(cands, heard["words"], cfg, stream, pick_dir)
    set_tag("")
    return {"url": url, "args": args, "info": info, "stream": stream, "audio": audio, "work": work,
            "pick_dir": pick_dir, "finals": finals, "language": heard.get("language"), "loud_rel": loud,
            "span": hi - lo, "timer": timer}


def make_clips(s, voices, cfg, opts):
    """Phase 3 for one analysed stream. Returns the clip records."""
    set_tag(s["info"]["name"][:18])
    timer = s["timer"]
    outdir = (config.HOME / datetime.date.today().isoformat()
              / f"{slugify(s['info']['name'], 24)}__{slugify(s['info']['title'], 40)}")
    outdir.mkdir(parents=True, exist_ok=True)
    ready, made, known = [], [], {}
    with timer.stage("make clips"):
        for i, m in enumerate(s["finals"], 1):
            try:
                ready.append(render.prepare(s["url"], s["args"], s["audio"], m, i, s["pick_dir"], cfg,
                                            s["language"], s["loud_rel"]))
            except Exception as exc:
                log(f"[clip {i}] failed: {str(exc)[:300]}", "err")
        for p in ready:
            render.learn(p, cfg, known)
        for p in ready:
            try:
                made.append(render.finish(p, voices.get(_vkey(s, p["index"])), outdir, s["pick_dir"], cfg, known))
            except Exception as exc:
                log(f"[clip {p['index']}] failed: {str(exc)[:300]}", "err")
    summary = (f"{minutes(s['span'])} of stream -> {len(made)} clip(s) in {minutes(timer.total())} ("
               + ", ".join(f"{k} {minutes(v)}" for k, v in timer.stages.items()) + ")")
    post.write(outdir, s["stream"], made, summary)
    (outdir / "report.json").write_text(json.dumps({
        "stream": s["stream"], "stream_seconds": round(s["span"]), "clips": len(made),
        "total_seconds": round(timer.total()),
        "stages_seconds": {k: round(v) for k, v in timer.stages.items()}}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    if not opts.keep_audio and made:
        s["audio"].unlink(missing_ok=True)
    log(summary, "ok")
    log(f"output: {outdir}", "ok")
    set_tag("")
    s["outdir"], s["summary"] = outdir, summary
    return made


def _vkey(s, index):
    return f"{s['url']}|{index}"


def _friendly(url, msg):
    browsers = ("Run it again with --cookies firefox (signed in there), or export a cookies.txt from your "
                "browser and pass --cookies-file cookies.txt. On Windows, --cookies chrome only works with "
                "Chrome fully closed, and newer Chrome versions can't be read at all.")
    if "confirm your age" in msg or "Sign in to confirm" in msg:
        return "This YouTube video is age-restricted and needs your login. " + browsers
    if "403" in msg and "kick" in url:
        return "Kick refused the download (403). " + browsers
    if "cookie" in msg.lower() and ("chrome" in msg.lower() or "decrypt" in msg.lower()):
        return "Couldn't read the browser's cookies. " + browsers
    return msg[:400]


def main(argv=None):
    import sys
    opts = parse(sys.argv[1:] if argv is None else argv)
    _require_tools()
    if opts.live:
        from .live import run as live_run
        if not opts.urls:
            die("give channels, e.g.  --live twitch:kaicenat youtube:@IShowSpeed")
        return live_run.main(opts.urls, opts.cookies_file, opts.duration)
    cfg = config.load({"clips_per_stream": opts.clips, "score_bar": opts.bar, "layout": opts.layout,
                       "claude_model": opts.claude_model, "narrator": opts.voice})
    config.HOME.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(config.HOME).free / 1e9
    if free_gb < 2:
        log(f"only {free_gb:.1f} GB free; long streams need ~0.1 GB per hour", "warn")

    urls = list(opts.urls)
    if opts.find:
        log("looking for GTA streams worth clipping...", "step")
        found = find.find(cfg, limit=opts.streams)
        if not found:
            die("found no GTA streams. Paste links, or add channels to gta6-clips/streamers.txt.")
        print()
        for i, s in enumerate(found, 1):
            print(f"  {i}. {s['name'][:22]:22} {s['views']:>10,} {'LIVE ' if s['live'] else ''}· "
                  f"{s['title'][:60]}  ({s['source']})\n     {s['url']}")
        print()
        if opts.list:
            return
        urls += [s["url"] for s in found]
    if not urls:
        die("nothing to clip: pass stream links, or --find, or --live with channels")

    analysed = []
    with ThreadPoolExecutor(max_workers=max(1, opts.parallel)) as pool:
        futures = [(pool.submit(analyse_stream, u, cfg, opts), u) for u in urls]
        for fut, url in futures:
            try:
                analysed.append(fut.result())
            except Exception as exc:
                log(f"{url}: {_friendly(url, str(exc))}", "err")

    scan.unload()                                     # free VRAM for the narrator
    voices = {}
    lines = {_vkey(s, i): m["narrator_line"] for s in analysed
             for i, m in enumerate(s["finals"], 1) if m.get("narrator_line")}
    if lines and not opts.no_narrator and cfg["narrator"] != "none":
        try:
            voices = narrator.synth(lines, config.HOME / "work" / "voice", cfg)
        except Exception as exc:                      # clips still ship, without intros
            log(f"narration skipped ({str(exc)[:120]}): clips get no intro", "warn")
            voices = {}

    results = []
    for s in analysed:
        if not s["finals"]:
            continue
        results.append((s, make_clips(s, voices, cfg, opts)))

    total = sum(len(c) for _, c in results)
    print()
    log(f"done: {total} clip(s) from {len(analysed)} stream(s)", "ok")
    for s, clips in results:
        meta = s.get("info") or {}
        print(f"\n  {meta.get('name', s['url'])} · {meta.get('title', '')[:60]}\n"
              f"  {s.get('summary', '')}\n  {s.get('outdir', '')}")
        for c in clips:
            print(f"    [{round(c['score'])}] {c['duration']:>3.0f}s @{hhmmss(c['stream_start'])}  {c['hook_text']}")
    print()


if __name__ == "__main__":
    main()
