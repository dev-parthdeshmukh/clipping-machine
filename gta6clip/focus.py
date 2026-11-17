"""The game half follows the action: find where the screen is changing (outside the
facecam), and turn that into a calm camera -- hold still, move only when the action really
moves, ease over ~0.4 s, hold again."""

import numpy as np


def centers(grays, cam=None):
    """Per sampled frame, the (x, y) centre of motion in gray-frame pixels; cam = (x, y, w, h)
    to ignore. Frames with no motion fall back to the previous centre (or the frame centre)."""
    if not grays:
        return []
    h, w = grays[0].shape
    out, last = [], (w / 2, h / 2)
    ys, xs = np.mgrid[0:h, 0:w]
    for i, g in enumerate(grays):
        if i == 0:
            out.append(last)
            continue
        diff = np.abs(g.astype(np.int16) - grays[i - 1].astype(np.int16)).astype(np.float32)
        diff[diff < 12] = 0
        if cam is not None:
            cx, cy, cw, ch = [int(round(v)) for v in cam]
            diff[max(0, cy):cy + ch, max(0, cx):cx + cw] = 0
        total = float(diff.sum())
        if total > 0:
            last = (float((diff * xs).sum() / total), float((diff * ys).sum() / total))
        else:
            last = (w / 2, h / 2) if cam is not None and i == 1 else last
        out.append(last)
    return out


def _smooth(vals, k=5):
    v = np.asarray(vals, dtype=np.float64)
    if len(v) < 3:
        return v
    k = min(k, len(v) | 1)
    pad = np.pad(v, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def plan(times, cs, frame, crop, move=0.4, hold=1.0, shift=0.18):
    """Keyframes [(t, crop_x, crop_y)] for a crop of size `crop` inside `frame` (same units as
    `cs`). Starts on the action; moves only when the smoothed centre stays more than `shift`
    of the crop width away for `hold` seconds; each move takes `move` seconds."""
    fw, fh = frame
    cw, ch = crop
    if not cs:
        return [(0.0, (fw - cw) / 2, (fh - ch) / 2)]
    sx, sy = _smooth([c[0] for c in cs]), _smooth([c[1] for c in cs])

    def clamp(x, y):
        return min(max(x - cw / 2, 0.0), fw - cw), min(max(y - ch / 2, 0.0), fh - ch)

    rx, ry = np.asarray([c[0] for c in cs]), np.asarray([c[1] for c in cs])
    tt = np.asarray(times)

    def settled(t):                                   # where the action is over the next `hold` s
        m = (tt >= t) & (tt <= t + hold)
        return clamp(float(np.median(rx[m])), float(np.median(ry[m]))) if m.any() else clamp(rx[-1], ry[-1])

    cur = settled(times[0]) if len(times) else clamp(sx[0], sy[0])
    keys = [(0.0, *cur)]
    away_since = None
    for t, x, y in zip(times, sx, sy):
        here = clamp(x, y)
        far = abs(here[0] - cur[0]) > shift * cw or abs(here[1] - cur[1]) > shift * ch
        if not far:
            away_since = None
            continue
        if away_since is None:
            away_since = t
        if t - away_since >= hold * 0.5 and t - keys[-1][0] >= move:
            target = settled(t)
            if abs(target[0] - cur[0]) <= shift * cw and abs(target[1] - cur[1]) <= shift * ch:
                continue                              # a blip, not a real move
            keys.append((t, *cur))
            keys.append((t + move, *target))
            cur, away_since = target, None
    return [(round(t, 3), round(x, 1), round(y, 1)) for t, x, y in keys]


def expr(keys, axis):
    """An ffmpeg expression in t for keys[i][axis] (1 = x, 2 = y), linear between keyframes,
    constant before the first and after the last."""
    vals = [(k[0], k[axis]) for k in keys]
    e = f"{vals[-1][1]:.1f}"
    for (t0, a), (t1, b) in reversed(list(zip(vals, vals[1:]))):
        seg = f"{a:.1f}" if a == b else f"({a:.1f}+({b - a:.1f})*(t-{t0:.3f})/{max(t1 - t0, 0.001):.3f})"
        e = f"if(lt(t,{t1:.3f}),{seg},{e})"
    return e
