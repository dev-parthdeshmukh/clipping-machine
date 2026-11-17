"""Editing decisions for one clip, all as numbers: which stretches to keep (dead air out),
where kept time lands in the output, where to punch in, where the payoff is.

Times: `start`/`end` and word times are stream seconds. Segments are clip-local source
seconds (0 = `start`). Output time is the clip after the cuts."""

import numpy as np


def keep_segments(words, start, end, max_gap=0.5, keep_gap=0.15, loud=None, quiet_db=-6.0):
    """Source stretches to keep. A gap longer than `max_gap` between words (or before the
    first word) shrinks to `keep_gap`, half kept on each side -- but only when it is really
    quiet: with `loud` (relative dB per stream second) every second of the gap must sit at
    least `quiet_db` below its surroundings, so trailer audio and wordless screams stay.
    Trailing audio is kept: the clip may end on a laugh or a scream that has no words."""
    dur = end - start
    inside = [w for w in words if w["e"] > start and w["s"] < end]
    if not inside:
        return [(0.0, dur)]
    half = keep_gap / 2
    segs, seg_start = [], 0.0
    prev_end = 0.0                                   # the clip start acts as a word edge
    for i, w in enumerate(inside):
        s = max(0.0, w["s"] - start)
        gap = s - prev_end
        if gap > max_gap and _quiet(loud, start + prev_end, start + s, quiet_db):
            if i == 0:                               # leading silence: start near the first word
                seg_start = s - half
            else:
                segs.append((seg_start, prev_end + half))
                seg_start = s - half
        prev_end = max(prev_end, min(dur, w["e"] - start))
    segs.append((seg_start, dur))
    return [(round(a, 6), round(b, 6)) for a, b in segs]


def _quiet(loud, a, b, quiet_db):
    if loud is None:
        return True
    lo, hi = max(0, int(a)), min(len(loud), int(np.ceil(b)))
    return hi <= lo or float(np.max(np.asarray(loud)[lo:hi])) < quiet_db


def remap(t, segs):
    """Clip-local source time -> output time. A time inside a cut maps to the next kept frame."""
    out = 0.0
    for a, b in segs:
        if t < a:
            return out
        if t <= b:
            return out + (t - a)
        out += b - a
    return out


def _kept(t, segs):
    return any(a <= t <= b for a, b in segs)


def remap_words(words, start, segs):
    """Stream-time words -> output-time words; words that fall in a cut are dropped."""
    out = []
    for w in words:
        s, e = w["s"] - start, w["e"] - start
        if _kept(s, segs):
            out.append({"s": round(remap(s, segs), 3), "e": round(remap(min(e, segs[-1][1]), segs), 3),
                        "w": w["w"]})
    return out


def zoom_points(loud_rel, start, segs, db, spacing=3.0):
    """Output times to punch in: seconds at least `db` above their surroundings, first second
    of each burst, kept (not cut), at least `spacing` seconds apart."""
    loud = np.asarray(loud_rel)
    a, b = int(start), int(np.ceil(start + segs[-1][1]))
    points = []
    for sec in range(max(0, a), min(len(loud), b)):
        if loud[sec] < db:
            continue
        local = sec - start
        if not _kept(local, segs):
            continue
        t = round(remap(local, segs), 3)
        if not points or t - points[-1] >= spacing:
            points.append(t)
    return points


def payoff_time(loud_rel, start, end):
    """Stream second of the loudest moment in [start, end); the midpoint if it is flat."""
    loud = np.asarray(loud_rel)
    a, b = max(0, int(start)), min(len(loud), int(np.ceil(end)))
    if b <= a or float(np.max(loud[a:b])) < 1.0:
        return (start + end) / 2
    return float(a + int(np.argmax(loud[a:b])))
