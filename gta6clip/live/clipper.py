"""Turn one live spike into a house-style clip: cut the raw window from the recording,
transcribe it, let Claude choose the whole topic and the title (fallback: a window around the
spike), then render with the normal pipeline."""

import json
import subprocess

from .. import claude, editor, moments, render, scan
from ..util import log, pcm, probe, run, slugify

PRE, POST = 75.0, 90.0     # raw window around the spike (clip-watcher uses 75 + 75)

PROMPT = """You clip GTA 6 livestreams for TikTok, YouTube Shorts and Reels. Below is the \
transcript of a {length:.0f} s window from {streamer}'s live stream (seconds from the window \
start). Chat or the audio spiked at {spike:.1f} s: something happened a few seconds before that.

Pick ONE clip that covers the whole topic around that moment: start where its setup begins \
(the hook within the first second, never on filler like "uh so yeah"), keep going until the \
streamer is done with it (the payoff and their reaction). Never cut mid-topic. Length target \
{t_min}-{t_max} s, inside 0-{length:.0f}.

Return ONLY a JSON object, no prose:
{{"start": 12.5, "end": 95.0, "score": 80,
  "hook_text": "on-screen title: Title Case, 2-5 words, exactly one keyword wrapped in *asterisks*, one emoji at the end, e.g. Easiest *Size* Comparison 😭",
  "post_title": "video title, max 70 characters, names the streamer",
  "description": "2-3 short sentences, no spoiler, ends with a question",
  "hashtags": ["#gta6", "#shorts", "..."],
  "captions": {{"tiktok": "...", "shorts": "...", "reels": "..."}}}}

TRANSCRIPT:
{transcript}
"""


def plan_window(spike_wall, start_wall, pre=PRE, post=POST):
    """(spike, window_start, window_end) in seconds of the recording file."""
    spike = spike_wall - start_wall
    return spike, max(0.0, spike - pre), spike + post


def _object(raw):
    try:
        text = raw.strip()
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except (ValueError, AttributeError):
        return {}


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def pick(words, spike_rel, streamer, cfg):
    """The clip inside the window: dict with start/end (window seconds), titles, captions."""
    length = words[-1]["e"] if words else spike_rel + POST
    lines = moments.lines(words, [], [], cfg) if words else []
    prompt = PROMPT.format(length=length, streamer=streamer, spike=spike_rel, t_min=cfg["target_min"],
                           t_max=cfg["target_max"],
                           transcript="\n".join(f"[{t:.1f}] {x}" for t, x in lines))
    try:
        r = _object(claude.ask(prompt, cfg))
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        log(f"  Claude unavailable ({str(exc)[:60]}): using the window around the spike", "warn")
        r = {}
    m = None
    if r.get("start") is not None and r.get("end") is not None:
        try:
            m = moments.snap({"start": max(0.0, float(r["start"])), "end": min(length, float(r["end"]))},
                             words, cfg)
        except (TypeError, ValueError):
            m = None
    if m:
        hook = str(r.get("hook_text") or f"{streamer} *Can't* Believe This 😭")
        m.update({"source": "claude", "hook_text": hook, "hooks": [hook],
                  "score": _num(r.get("score"), 70.0),
                  "post_title": str(r.get("post_title") or hook).replace("*", "")[:70],
                  "description": str(r.get("description") or ""),
                  "hashtags": editor._tags(r.get("hashtags")),
                  "captions": r.get("captions") if isinstance(r.get("captions"), dict) else {}})
        return m
    m = (moments.snap({"start": max(0.0, spike_rel - 45), "end": spike_rel + 45}, words, cfg)
         if words else None) or {"start": max(0.0, spike_rel - 45), "end": min(length, spike_rel + 45)}
    hook = f"{streamer} *Can't* Believe This 😭"
    m.update({"source": "fallback", "hook_text": hook, "hooks": [hook], "score": 60.0,
              "post_title": f"{streamer} can't believe this in GTA 6",
              "description": f"{streamer} live on GTA 6. What would you have done?",
              "hashtags": editor._tags([f"#{slugify(streamer).replace('-', '')}"]), "captions": {}})
    return m


def cut(recording, start, length, dest):
    """Stream-copy [start, start+length] of the recording (no re-encode, audio intact)."""
    run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", str(recording),
         "-t", f"{length:.3f}", "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
         "-movflags", "+faststart", str(dest)], timeout=600)
    return dest


def make_clip(event, session, index, workdir, outdir, cfg, streamer):
    """Cut, pick, render one event. Returns the clip record (render.finish) or None."""
    spike, w0, w1 = plan_window(event.spike_ts, session.start_wall)
    w1 = min(w1, session.written() - 2)
    raw = workdir / f"{event.event_id}_raw.mp4"
    cut(session.path, w0, w1 - w0, raw)
    if probe(raw)["duration"] < 20:
        log(f"  {event.event_id}: only {probe(raw)['duration']:.0f}s of footage, skipped", "warn")
        return None
    words, _ = scan.words_from(cfg["scan_model"], pcm(raw, 16000), cfg["language"])
    m = pick(words, spike - w0, streamer, cfg)
    m.update({"title": f"live-{slugify(m['hook_text'].replace('*', ''), 30)}", "kind": "live",
              "reason": f"live {event.stats.get('source', 'chat')} spike", "caption": m["captions"].get("tiktok", "")})
    log(f"  clip {index}: {m['hook_text']} ({m['end'] - m['start']:.0f}s, {m['source']})", "step")
    p = render.prepare_local(raw, m, index, workdir, cfg)
    rec = render.finish(p, None, outdir, workdir, cfg, {})
    rec["stream_start"] = round(w0 + m["start"], 1)
    rec["stream_end"] = round(w0 + m["end"], 1)
    rec["spike"] = event.stats
    return rec
