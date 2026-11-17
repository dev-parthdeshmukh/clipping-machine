"""First picking pass: the transcript goes to `claude -p` in 12-minute slices, annotated with
where the audio jumped and where chat sped up, and each slice comes back as candidate clips."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import claude
from .util import log

PROMPT = """Role: short-form editor for a GTA 6 clip channel (TikTok, YouTube Shorts, Reels).
Stream: "{title}" by {streamer}. GTA 6 just launched, so anything about it is in demand.

The transcript below is timestamped in seconds and also picks up game and trailer audio, so \
work out from context who is speaking. Two kinds of tags can start a line:
  [LOUD +N dB]  the sound rose N dB over the previous couple of minutes (shouting, screaming)
  [CHAT xN]     chat ran N times faster than its usual pace (viewers reacting)
Treat tags as clues only: an explosion is loud without being a reaction.

Task: return up to {want} clips worth posting from this slice ({lo:.0f}-{hi:.0f} s). Kinds, \
most valuable first during launch week:
  first_reaction  first time they see/do something in GTA 6, their unfiltered first words
  discovery       they spot something surprising, hidden or wild in the game
  reaction        a huge reaction: yelling, speechless, out of the chair
  funny           a fail, chaos, a roast, something people forward to friends
  take            a strong opinion about GTA 6

A good clip:
  * hooks in its first second (no warm-up filler such as "uh so yeah")
  * needs zero context from earlier in the stream
  * covers the whole topic: begins where the setup begins and runs until the streamer is \
finished with it, including the payoff and their reaction; never stop mid-topic
  * lands its payoff inside the clip and ends on it
  * runs {t_min}-{t_max} s (never outside {min_d}-{max_d} s)
Skip menus, loading screens, donation and sponsor reads, and dead air. Clips must not overlap; \
returning fewer is better than returning weak ones.

Answer with a JSON array only (no prose, no code fence), one object per clip:
{{"start": 1312.5, "end": 1390.0, "kind": "discovery", "title": "internal name",
  "hook_text": "Tim Sees The *Map* 😭", "caption": "post caption under 150 characters",
  "hashtags": ["#gta6", "#gtavi"], "score": 82, "reason": "why it holds attention"}}
score = expected retention 1-100, strict (85+ only for sure things).
hook_text = the title shown on screen for the whole clip: Title Case, 2-5 words, exactly one \
keyword wrapped in *asterisks* (rendered yellow), one emoji at the end, teasing rather than \
telling. Example: "Easiest *Size* Comparison 😭".

TRANSCRIPT
{transcript}
"""


def _tags(t0, t1, loud, chat, chat_norm, cfg):
    tags = []
    if len(loud) and int(t0) < len(loud):
        top = float(np.max(loud[int(t0):max(int(t0) + 1, int(np.ceil(t1)))]))
        if top >= cfg["loud_db"]:
            tags.append(f"[LOUD +{top:.0f}dB]")
    if chat_norm:
        window = chat[int(t0 // 5):int(t1 // 5) + 2]              # chat reacts a few seconds late
        if window and max(window) / chat_norm >= 2.5:
            tags.append(f"[CHAT x{max(window) / chat_norm:.0f}]")
    return tags


def lines(words, loud, chat, cfg, line_seconds=8):
    """Transcript as (start, text) lines of about `line_seconds`, tagged where it got loud or
    chat sped up."""
    chat = chat or []
    busy = [c for c in chat if c > 0]
    chat_norm = float(np.median(busy)) if busy else 0.0
    out, bucket = [], []
    for w in words:
        bucket.append(w)
        if w["e"] - bucket[0]["s"] >= line_seconds:
            out.append(bucket)
            bucket = []
    if bucket:
        out.append(bucket)
    return [(b[0]["s"], " ".join(_tags(b[0]["s"], b[-1]["e"], loud, chat, chat_norm, cfg)
                                 + [x["w"] for x in b]))
            for b in out]


def snap(m, words, cfg):
    """Put a rough [start, end] onto real word boundaries and inside the length limits
    (min_duration..max_duration). Returns the updated moment, or None if it can't fit."""
    lo, hi = cfg["min_duration"], cfg["max_duration"]
    want_s, want_e = float(m["start"]), float(m["end"])
    after = [w for w in words if w["s"] >= want_s - 1.5]
    if not after:
        return None
    first = min(after, key=lambda w: abs(w["s"] - want_s))
    body = [w for w in words if w["s"] >= first["s"] and w["e"] <= want_e + 1.5]
    if not body:
        return None
    last = min(body, key=lambda w: abs(w["e"] - want_e))
    if last["e"] - first["s"] > hi:                        # too long: end on a sentence if possible
        fits = [w for w in body if w["e"] - first["s"] <= hi]
        if not fits:
            return None
        sentence_ends = [w for w in fits if w["w"].rstrip()[-1:] in ".!?"]
        last = (sentence_ends or fits)[-1]
    if last["e"] - first["s"] < lo:                        # too short: run on to the minimum
        later = [w for w in words if last["e"] < w["e"] <= first["s"] + hi]
        long_enough = [w for w in later if w["e"] - first["s"] >= lo]
        last = long_enough[0] if long_enough else (later[-1] if later else last)
        if last["e"] - first["s"] < lo:
            return None
    m["start"] = round(max(0.0, first["s"] - 0.6), 2)
    m["end"] = round(min(last["e"] + 0.6, m["start"] + hi), 2)
    return m


def dedupe(cands):
    """Highest score wins; a clip sharing more than 30 % of the shorter one's length with a
    kept clip is dropped."""
    kept = []
    for c in sorted(cands, key=lambda c: float(c.get("score", 0)), reverse=True):
        def clash(k):
            shared = min(c["end"], k["end"]) - max(c["start"], k["start"])
            return shared > 0.3 * min(c["end"] - c["start"], k["end"] - k["start"])
        if not any(clash(k) for k in kept):
            kept.append(c)
    return kept


def candidates(scan_data, loud_rel, chat, workdir, cfg, stream):
    """All candidate clips for one stream (snapped, de-duplicated), saved to candidates.json."""
    saved = workdir / "candidates.json"
    if saved.exists():
        found = json.loads(saved.read_text(encoding="utf-8"))
        log(f"reusing {len(found)} candidate moment(s)", "ok")
        return found
    words = scan_data["words"]
    tagged = lines(words, loud_rel, chat, cfg)
    span = cfg["chunk_minutes"] * 60
    first, last = words[0]["s"], words[-1]["e"]
    slices = []
    t = first
    while t < last:
        body = [f"[{s:.1f}] {text}" for s, text in tagged if t <= s < t + span]
        if sum(len(b.split()) for b in body) >= 30:
            slices.append((t, min(t + span, last), "\n".join(body)))
        t += span
    if not slices:
        raise RuntimeError("not enough talking in this stream to clip")
    want = max(2, min(5, round(cfg["clips_per_stream"] / len(slices)) + 2)) + 2
    log(f"Claude is reading {len(slices)} part(s) of the stream, {cfg['claude_parallel']} at a time...", "step")

    def ask(piece):
        lo, hi, text = piece
        prompt = PROMPT.format(streamer=stream["name"], title=stream["title"], want=want, lo=lo, hi=hi,
                               min_d=cfg["min_duration"], max_d=cfg["max_duration"],
                               t_min=cfg["target_min"], t_max=cfg["target_max"], transcript=text)
        try:
            reply = claude.parse_array(claude.ask(prompt, cfg))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            log(f"  part {lo / 60:.0f}-{hi / 60:.0f} min skipped: {str(exc)[:120]}", "warn")
            return []
        good = []
        for m in reply:
            try:
                if lo - 5 <= float(m["start"]) < hi + 30 and (s := snap(m, words, cfg)):
                    good.append(s)
            except (KeyError, TypeError, ValueError):
                continue
        return good

    with ThreadPoolExecutor(max_workers=max(1, int(cfg["claude_parallel"]))) as pool:
        found = dedupe([m for got in pool.map(ask, slices) for m in got])
    if found:                                    # an empty answer is not saved: retried next run
        saved.write_text(json.dumps(found, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"{len(found)} candidate moment(s)", "ok")
    return found
