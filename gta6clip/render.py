"""Make one clip: fetch only its video, line it up with the stream audio, caption it, cut
the dead air, punch in on the peaks, frame it 9:16, add the hook bar, put the narrated
intro in front, encode (NVENC when it works) and grab a cover frame."""

import numpy as np

from . import captions, config, edit, fetch, hook, intro, layout, scan, util
from .util import ass_path, log, pcm, probe, run, slugify

PAD = 4.0   # extra seconds fetched on each side, trimmed off after alignment


def encoder_args(cfg):
    if cfg["encoder"] in ("auto", "h264_nvenc") and util.nvenc_available():
        return ["-c:v", "h264_nvenc", *cfg["nvenc_args"], "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"], "-pix_fmt", "yuv420p"]


def zoom_expr(points, cfg):
    """Scale factor over output time t: up over zoom_in, hold zoom_hold, back over zoom_in."""
    if not points:
        return "1"
    zi, hold, extra = cfg["zoom_in"], cfg["zoom_hold"], cfg["zoom_scale"] - 1
    tris = [f"min(min(max((t-{z:.3f})/{zi},0),1),min(max(({z + 2 * zi + hold:.3f}-t)/{zi},0),1))"
            for z in points]
    expr = tris[0]
    for tri in tris[1:]:
        expr = f"max({expr},{tri})"
    return f"1+{extra:.4f}*{expr}"


def zoom_filter(points, cfg):
    """Per-frame punch-in, centred: scale up by the zoom factor, crop the middle back out."""
    W, H = cfg["output_width"], cfg["output_height"]
    z = zoom_expr(points, cfg)
    if z == "1":
        return "null"
    return (f"scale=w='{W}*({z})':h='{H}*({z})':eval=frame,"
            f"crop={W}:{H}:x='({W}*({z})-{W})/2':y='({H}*({z})-{H})/2'")


def cut_graph(segs, vin, ain):
    """Keep only `segs` (clip-local seconds) of [vin]/[ain] with per-segment trim/atrim and
    one concat, so audio and video stay in sync. Returns (graph, video label, audio label)."""
    if len(segs) == 1 and segs[0][0] <= 0.001:
        a, b = segs[0]
        return (f"[{vin}]trim=end={b:.3f},setpts=PTS-STARTPTS[vcut];"
                f"[{ain}]atrim=end={b:.3f},asetpts=PTS-STARTPTS[acut]"), "vcut", "acut"
    n = len(segs)
    g = [f"[{vin}]split={n}" + "".join(f"[vs{i}]" for i in range(n)),
         f"[{ain}]asplit={n}" + "".join(f"[as{i}]" for i in range(n))]
    for i, (a, b) in enumerate(segs):
        g.append(f"[vs{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[vt{i}]")
        g.append(f"[as{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[at{i}]")
    g.append("".join(f"[vt{i}][at{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vcut][acut]")
    return ";".join(g), "vcut", "acut"


def _energy(path, start, dur, rate=8000, hop=80):
    """Loudness curve, 100 values per second, of `dur` seconds of `path` from `start`."""
    x = pcm(path, rate, start, dur)
    frames = x[: len(x) // hop * hop].reshape(-1, hop)
    return np.log1p(100.0 * np.sqrt((frames ** 2).mean(axis=1))).astype(np.float64)


def locate(clip_file, audio_file, guess, search=30.0):
    """Where the downloaded clip starts in the stream (seconds), found by sliding the clip's
    loudness curve along the stream's around `guess` (FFT cross-correlation, normalised per
    position). Returns (seconds, match quality 0-1)."""
    probe_len = 20.0
    a = _energy(clip_file, 0, probe_len)
    origin = max(0.0, guess - search)
    b = _energy(audio_file, origin, probe_len + 2 * search)
    n = len(a)
    if n < 200 or len(b) <= n:
        return guess, 0.0
    a = (a - a.mean()) / (a.std() + 1e-9)
    size = 1 << int(np.ceil(np.log2(len(b) + n)))
    raw = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)[: len(b) - n + 1]
    sums = np.concatenate(([0.0], np.cumsum(b)))
    sq = np.concatenate(([0.0], np.cumsum(b * b)))
    mean = (sums[n:] - sums[:-n]) / n
    std = np.sqrt(np.maximum((sq[n:] - sq[:-n]) / n - mean ** 2, 1e-12))
    score = raw / (n * std)
    best = int(np.argmax(score))
    return origin + best / 100.0, float(score[best])


def _finish_prepare(part, info, offset, moment, index, loud_rel, cfg, language):
    start, end = moment["start"], moment["end"]
    dur = end - start
    words, _ = scan.words_from(cfg["caption_model"], pcm(part, 16000, offset, dur), language, offset=start)
    segs = edit.keep_segments(words, start, end, cfg["dead_gap"], cfg["keep_gap"], loud=loud_rel,
                              quiet_db=cfg["quiet_db"])
    return {"index": index, "name": f"{index:02d}_{slugify(moment.get('title') or moment.get('hook_text'))}",
            "moment": moment, "part": part, "info": info, "offset": offset, "dur": dur, "segs": segs,
            "words": edit.remap_words(words, start, segs),
            "zooms": edit.zoom_points(loud_rel, start, segs, cfg["zoom_db"]),
            "payoff_local": edit.payoff_time(loud_rel, start, end) - start,
            "analysis": layout.analyze(part, offset, offset + dur, info)}


def prepare(url, args, audio, moment, index, workdir, cfg, language, loud_rel):
    """Fetch one clip's video, line it up with the stream audio, caption and plan its edit."""
    start, end = moment["start"], moment["end"]
    log(f"[clip {index}] {moment.get('hook_text', '')}  ({end - start:.0f} s)", "step")
    part = fetch.section(url, args, start - PAD, end + PAD, workdir / f"part_{index:02d}.mp4", cfg)
    info = probe(part)
    if not info["width"]:
        raise RuntimeError("the clip download came back without video")
    at, conf = locate(part, audio, max(0.0, start - PAD))
    offset = start - at if conf >= 0.5 else min(PAD, start)
    offset = min(max(offset, 0.0), max(0.0, info["duration"] - (end - start)))
    if conf < 0.5:
        log(f"  couldn't line the clip up by sound (match {conf:.2f}); using the planned times", "warn")
    return _finish_prepare(part, info, offset, moment, index, loud_rel, cfg, language)


def prepare_local(part, moment, index, workdir, cfg, loud_rel=None, language=None):
    """Same as prepare() for a local file whose times are the moment's times (no download)."""
    if loud_rel is None:
        loud_rel = scan.relative(scan.loudness(part, workdir))
    return _finish_prepare(part, probe(part), moment["start"], dict(moment), index, loud_rel, cfg, language)


def learn(p, cfg, known):
    """Quiet pass: let every clip teach `known` where this stream's facecam sits."""
    layout.graph(p["part"], p["offset"], p["offset"] + p["dur"], cfg, p["info"],
                 known=known, analysis=p["analysis"], quiet=True)


def _body(p, outdir, workdir, cfg, known, reveal, enc):
    m, dur, part, name = p["moment"], p["dur"], p["part"], p["name"]
    W, H = cfg["output_width"], cfg["output_height"]
    out_len = sum(b - a for a, b in p["segs"])
    ass = captions.build(p["words"], out_len, workdir / f"{name}.ass", cfg)
    chain, look, cam_h = layout.graph(part, p["offset"], p["offset"] + dur, cfg, p["info"],
                                      known=known, analysis=p["analysis"])
    cuts, vcut, acut = cut_graph(p["segs"], "vout", "0:a")
    g = (f"{chain};{cuts};[{vcut}]{zoom_filter(p['zooms'], cfg)},setsar=1,"
         f"ass=f='{ass_path(ass)}':fontsdir='{ass_path(config.FONTS)}'[vc]")
    inputs = ["-ss", f"{p['offset']:.3f}", "-t", f"{dur:.3f}", "-i", str(part)]
    last = "vc"
    if m.get("hook_text"):
        try:
            png, _, hh = hook.render(m["hook_text"], cfg, workdir / f"{name}_hook.png")
            top = int(cam_h - hh / 2) if cam_h else int(H * cfg["title_y"] - hh / 2)
            inputs += ["-i", str(png)]
            g += f";[vc][1:v]overlay=(W-w)/2:{top}[vh]"
            last = "vh"
        except (OSError, ValueError) as exc:
            log(f"  title bar skipped ({exc})", "warn")
    if reveal:
        g += (f";[{last}]split[r1][r2];[r2]gblur=sigma={cfg['intro_blur']},format=yuva420p,"
              f"fade=t=out:st=0:d={cfg['reveal']}:alpha=1[rb];[r1][rb]overlay=format=auto[vr]")
        last = "vr"
    g += f";[{last}]format=yuv420p[v]"
    speech = "loudnorm=I=-14:TP=-1.5:LRA=11," if cfg["loudnorm"] else ""
    g += f";[{acut}]{speech}aresample=48000[a]"
    dest = workdir / f"{name}_body.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-nostdin", *inputs, "-filter_complex", g,
         "-map", "[v]", "-map", "[a]", *enc, "-r", "30", "-c:a", "aac", "-b:a", cfg["audio_bitrate"],
         "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(dest)], timeout=1800)
    return dest, look, cam_h


def _intro(p, voice_wav, workdir, cfg, known, enc):
    voice_len = probe(voice_wav)["duration"]
    heard, _ = scan.words_from(cfg["caption_model"], pcm(voice_wav, 16000), "en")
    words = intro.script_words(p["moment"]["narrator_line"], heard, voice_len)
    t0 = max(0.0, p["offset"] + p["payoff_local"] - (voice_len + 0.3) / 2)
    frame, _, _ = layout.graph(p["part"], t0, t0 + voice_len + 0.3, cfg, p["info"], known=known, quiet=True)
    dest = workdir / f"{p['name']}_intro.mp4"
    return intro.render_intro(p["part"], p["payoff_local"], p["offset"], voice_wav, words, frame, cfg,
                              dest, workdir, enc)


def finish(p, voice, outdir, workdir, cfg, known):
    """Frame, edit, caption, title, narrate and encode one prepared clip. Returns its record."""
    m = p["moment"]
    enc = encoder_args(cfg)
    log(f"[clip {p['index']}] editing + encoding ({enc[1]})", "step")
    body, look, _ = _body(p, outdir, workdir, cfg, known, reveal=voice is not None, enc=enc)
    dest = outdir / f"{p['name']}.mp4"
    if voice is not None:
        head = _intro(p, voice[0], workdir, cfg, known, enc)
        lst = workdir / f"{p['name']}_concat.txt"
        lst.write_text("".join(f"file '{ass_path(x).replace(chr(92) + ':', ':')}'\n" for x in (head, body)),
                       encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", "-movflags", "+faststart", str(dest)], timeout=600)
        head.unlink(missing_ok=True)
        lst.unlink(missing_ok=True)
        body.unlink(missing_ok=True)
        lead = probe(dest)["duration"] - sum(b - a for a, b in p["segs"])
    else:
        body.replace(dest)
        lead = 0.0
    cover = outdir / f"{p['name']}_cover.jpg"
    at = lead + edit.remap(p["payoff_local"], p["segs"])
    run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{max(0.0, at):.3f}", "-i", str(dest),
         "-frames:v", "1", "-q:v", "2", str(cover)])
    p["part"].unlink(missing_ok=True) if p["part"].name.startswith("part_") else None
    log(f"  -> {dest.name} ({look} layout)", "ok")
    return {"file": dest.name, "cover": cover.name, "kind": m.get("kind"), "hook_text": m.get("hook_text"),
            "hooks": m.get("hooks", []), "caption": m.get("caption"), "captions": m.get("captions", {}),
            "post_title": m.get("post_title"), "description": m.get("description"),
            "hashtags": m.get("hashtags", []), "score": m.get("score"), "reason": m.get("reason"),
            "narrator_line": m.get("narrator_line"), "narrator_engine": voice[1] if voice else None,
            "layout": look, "stream_start": round(m["start"], 1), "stream_end": round(m["end"], 1),
            "duration": round(probe(dest)["duration"], 1)}
