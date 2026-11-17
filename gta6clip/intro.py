"""The narrated intro: the clip's payoff plays blurred and dark under the narrator's line
(big words, synced), then a whoosh carries into the clip."""

from . import captions, config
from .util import ass_path, probe, run


def script_words(line, heard, dur):
    """The narrator line's own words (spelling, CAPS) timed from what Whisper heard: one-to-one
    when the counts match, else spread by length over the heard span (or the whole voice)."""
    words = line.split()
    if heard and len(heard) == len(words):
        return [{"s": h["s"], "e": h["e"], "w": w} for w, h in zip(words, heard)]
    a, b = (heard[0]["s"], heard[-1]["e"]) if heard else (0.0, dur)
    weights = [len(w) + 1 for w in words]
    total, t, out = sum(weights), a, []
    for w, k in zip(words, weights):
        e = t + (b - a) * k / total
        out.append({"s": round(t, 3), "e": round(e, 3), "w": w})
        t = e
    if out:
        out[-1]["e"] = b
    return out


def whoosh(path=None):
    """A 0.5 s whoosh (pink noise swell, band-limited), synthesised once."""
    path = path or (config.ENV_DIR / "whoosh.wav")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink:a=0.7",
             "-af", "highpass=f=250,lowpass=f=7000,afade=t=in:d=0.32,afade=t=out:st=0.32:d=0.18",
             "-ar", "48000", str(path)])
    return path


def render_intro(part, payoff_local, offset, voice_wav, line_words, frame_chain, cfg, dest, workdir,
                 encoder_args):
    """Encode the intro to `dest`. `payoff_local` is clip-local source time of the payoff,
    `offset` where the clip starts inside `part`, `frame_chain` a [0:v]->[vout] framing graph."""
    voice_len = probe(voice_wav)["duration"]
    dur = voice_len + 0.3
    info = probe(part)
    t0 = max(0.0, min(offset + payoff_local - dur / 2, info["duration"] - dur))
    ass = captions.build(line_words, dur, workdir / f"{dest.stem}.ass", cfg, y=0.45)
    fonts = ass_path(config.FONTS)
    duck = f"volume=-{cfg['duck_db']}dB"
    w_at = max(0.0, dur - 0.35)
    graph = (f"{frame_chain};"
             f"[vout]gblur=sigma={cfg['intro_blur']},eq=brightness=-{cfg['intro_dark']},"
             f"ass=f='{ass_path(ass)}':fontsdir='{fonts}',format=yuv420p[v];"
             f"[0:a]{duck},aresample=48000[g];"
             f"[1:a]aresample=48000,apad[n];"
             f"[2:a]aresample=48000,adelay={int(w_at * 1000)}:all=1[w];"
             f"[g][n][w]amix=inputs=3:duration=first:normalize=0,"
             f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    run(["ffmpeg", "-y", "-v", "error", "-nostdin",
         "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(part),
         "-i", str(voice_wav), "-i", str(whoosh()),
         "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
         *encoder_args, "-r", "30", "-c:a", "aac", "-b:a", cfg["audio_bitrate"], "-ar", "48000", "-ac", "2",
         str(dest)], timeout=900)
    return dest
