"""Pass 2, the "viral editor": Claude judges the best pass-1 candidates side by side,
re-scores them, writes 3 hooks (and picks one), the narrator line and per-platform captions."""

import json
import subprocess

from . import claude
from .util import log

PROMPT = """You are the head editor of a GTA 6 clip channel on TikTok, YouTube Shorts and \
Instagram Reels, paid per view. Below are the {n} best candidate clips from a stream by \
{streamer} ("{title}"), as JSON. Judge them SIDE BY SIDE, harshly, on:
- hook: do the first 1-2 seconds stop the scroll?
- standalone: does it make sense with zero context?
- payoff: does it land inside the clip?
- shareability: would people send it to a friend or comment?

For EACH candidate return:
- "id" = the candidate's id
- "score": 1-100 predicted retention after your comparison (85+ only for clips you'd bet on)
- "hooks": 3 different on-screen titles (shown the whole clip): Title Case, 2-5 words, \
exactly one keyword wrapped in *asterisks* (shown in yellow), one emoji at the end, tease \
not tell. Example: "Easiest *Size* Comparison 😭"
- "best_hook": index 0-2 of the strongest hook
- "narrator_line": the line a narrator says over a blurred teaser before the clip plays. \
At most 12 words, name the streamer, tease the moment and never spoil the payoff, and make \
every line different from the others (no shared template). Example style: \
"Kai Cenat was NOT ready for this GTA 6 moment."
- "captions": {{"tiktok": "...", "shorts": "...", "reels": "..."}} post captions that drive \
comments, each under 150 chars, written for that platform
- "post_title": the video title for YouTube Shorts / TikTok, at most 70 characters, names \nthe streamer, curiosity without clickbait, at most one emoji, no hashtags
- "description": 2-3 short sentences for the post description: what happens (no spoiler of \nthe payoff), a question that invites comments
- "hashtags": 5-8 hashtags, always #gta6 and #shorts, plus the streamer and the moment

Return ONLY a JSON array of these objects, no prose, no code fence.

CANDIDATES:
{candidates}
"""


def _text(words, start, end):
    return " ".join(w["w"] for w in words if start <= w["s"] < end)


def _tags(raw):
    """#-prefixed, de-duplicated, with #gta6 and #shorts always present."""
    out = []
    for t in list(raw or []) + ["#gta6", "#shorts"]:
        t = "#" + str(t).strip().lstrip("#").replace(" ", "")
        if len(t) > 1 and t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return out


def _fallback(m, stream):
    """Pass-1 data dressed as a final, for when pass 2 is unavailable."""
    out = dict(m)
    out.setdefault("hooks", [m.get("hook_text") or ""])
    out["narrator_line"] = f"Look what {stream['name']} just did in GTA 6..."
    cap = m.get("caption") or ""
    out["captions"] = {"tiktok": cap, "shorts": cap, "reels": cap}
    out["post_title"] = (m.get("hook_text") or "").replace("*", "")[:70]
    out["description"] = cap
    out["hashtags"] = _tags(m.get("hashtags"))
    return out


def _merge(m, r):
    out = dict(m)
    hooks = [h for h in (r.get("hooks") or []) if isinstance(h, str) and h.strip()]
    if hooks:
        best = r.get("best_hook", 0)
        out["hooks"] = hooks
        out["hook_text"] = hooks[best] if isinstance(best, int) and 0 <= best < len(hooks) else hooks[0]
    try:
        out["score"] = float(r.get("score", m.get("score", 0)))
    except (TypeError, ValueError):                 # "high", None...: keep the pass-1 score
        out["score"] = float(m.get("score", 0))
    out["narrator_line"] = str(r.get("narrator_line") or "").strip()
    caps = r.get("captions") if isinstance(r.get("captions"), dict) else {}
    base = m.get("caption") or ""
    out["captions"] = {k: str(caps.get(k) or base) for k in ("tiktok", "shorts", "reels")}
    out["hashtags"] = _tags(r.get("hashtags") or m.get("hashtags"))
    out["post_title"] = str(r.get("post_title") or out.get("hook_text") or "").replace("*", "").strip()[:70]
    out["description"] = str(r.get("description") or base).strip()
    return out


def finalize(cands, words, cfg, stream, workdir):
    """Re-scored finals at or above the score bar, best first, at most clips_per_stream.
    Cached in workdir/moments.json."""
    cache = workdir / "moments.json"
    if cache.exists():
        found = json.loads(cache.read_text(encoding="utf-8"))
        log(f"reusing {len(found)} picked moment(s)", "ok")
        return found
    if not cands:
        return []
    finalists = sorted(cands, key=lambda m: -float(m.get("score", 0)))[: cfg["finalists"]]
    payload = [{"id": i, "start": m["start"], "end": m["end"], "kind": m.get("kind"),
                "pass1_hook": m.get("hook_text"), "pass1_reason": m.get("reason"),
                "transcript": _text(words, m["start"], m["end"])} for i, m in enumerate(finalists)]
    prompt = PROMPT.format(n=len(finalists), streamer=stream["name"], title=stream["title"],
                           candidates=json.dumps(payload, indent=1, ensure_ascii=False))
    try:
        reply = claude.parse_array(claude.ask(prompt, cfg))
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        log(f"viral editor pass failed ({str(exc)[:100]}); using pass-1 scores", "warn")
        reply = []
    by_id = {r.get("id"): r for r in reply if isinstance(r.get("id"), int)}
    if by_id:
        scored = [_merge(m, by_id[i]) for i, m in enumerate(finalists) if i in by_id]
        for m in scored:
            if not m["narrator_line"]:
                m["narrator_line"] = _fallback(m, stream)["narrator_line"]
    else:
        scored = [_fallback(m, stream) for m in finalists]
    scored.sort(key=lambda m: -m["score"])
    bar = cfg["score_bar"]
    chosen = [m for m in scored if m["score"] >= bar][: cfg["clips_per_stream"]]
    if not chosen:
        best = round(scored[0]["score"]) if scored else 0
        log(f"no clip reached {bar} (best was {best}); try --bar 60", "warn")
        return []
    log(f"picked {len(chosen)} of {len(cands)} candidate moments", "ok")
    cache.write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding="utf-8")
    return chosen
