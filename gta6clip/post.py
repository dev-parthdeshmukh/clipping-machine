"""The posting kit next to the clips: POST.md (human, copy-paste) and clips.json (machine)."""

import json

from .util import hhmmss

PLATFORMS = (("TikTok", "tiktok"), ("Shorts", "shorts"), ("Reels", "reels"))


def _section(clip, stream):
    tags = " ".join(clip.get("hashtags") or [])
    caps = clip.get("captions") or {}
    fallback = clip.get("caption") or ""
    yield f"## {clip['file']}"
    yield (f"**{clip['hook_text']}** · {clip.get('kind')} · {clip['duration']:.0f} s · "
           f"score {round(clip['score'])} · voice: {clip.get('narrator_engine') or 'none'}")
    yield ""
    yield f"Narrator: _{clip.get('narrator_line') or ''}_"
    yield ""
    yield f"**Title:** {clip.get('post_title') or clip['hook_text']}"
    yield ""
    yield "**Description:**"
    yield clip.get("description") or fallback
    yield ""
    yield f"Credit: {stream['name']} ({stream['url']})"
    yield tags
    yield ""
    yield f"**Hashtags:** {tags}"
    yield ""
    for label, key in PLATFORMS:
        yield f"**{label}:** {caps.get(key) or fallback} {tags}".rstrip()
        yield ""
    yield f"_Why: {clip.get('reason') or ''}_"
    yield f"_From the stream at {hhmmss(clip['stream_start'])}_"
    yield ""
    yield "---"
    yield ""


def write(outdir, stream, clips, summary):
    md = [f"# {stream['name']}: {stream['title']}", "", f"Stream: {stream['url']}", "", summary, ""]
    if not clips:
        md += ["No clips this run.", ""]
    for clip in clips:
        md += list(_section(clip, stream))
    (outdir / "POST.md").write_text("\n".join(md), encoding="utf-8")
    (outdir / "clips.json").write_text(json.dumps({"stream": stream, "clips": clips}, indent=2,
                                                  ensure_ascii=False), encoding="utf-8")
