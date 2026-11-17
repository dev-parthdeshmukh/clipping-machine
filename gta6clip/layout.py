"""Framing: turn a 16:9 stream picture into the 9:16 house layout.

    stream  streamer's facecam on top, the game below (the house style)
    face    the whole picture is the streamer (IRL / just chatting): a 9:16 crop on them
    fit     nobody on screen: the whole frame, centred over a blurred copy

graph() returns (ffmpeg filtergraph [0:v] -> [vout], look name, height of the top panel)."""

import threading

import numpy as np

from . import config, focus
from .util import even, log

SAMPLE_EVERY = 0.6        # seconds between looked-at frames
MAX_SAMPLES = 50
LOOK_WIDTH = 640          # frames are shrunk to this width before looking at them
BIG_FACE = 0.12           # a face wider than this share of the frame fills the picture
CAM_W, CAM_H = 4.2, 3.2   # a facecam box is about this many face-widths / face-heights big

_local = threading.local()


def _note(msg):
    if not getattr(_local, "quiet", False):
        log(msg, "info")


def _detector(size):
    import cv2
    model = config.ENV_DIR / "models" / "yunet.onnx"
    if model.exists() and hasattr(cv2, "FaceDetectorYN"):
        net = cv2.FaceDetectorYN.create(str(model), "", size, 0.6, 0.3, 5000)

        def yunet(img, gray):
            found = net.detect(img)[1]
            return [] if found is None else [tuple(f[:4]) for f in found]
        return yunet
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return lambda img, gray: [tuple(r) for r in cascade.detectMultiScale(gray, 1.15, 6, minSize=(16, 16))]


def analyze(source, t0, t1, info):
    """Look at frames between t0 and t1: (faces [(t, x, y, w, h) in source px], times, grays, scale)."""
    try:
        import cv2
    except ImportError:
        return [], [], [], 1.0
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return [], [], [], 1.0
    scale = min(1.0, LOOK_WIDTH / max(1, info["width"]))
    size = (max(1, int(info["width"] * scale)), max(1, int(info["height"] * scale)))
    detect = _detector(size)
    step = max(SAMPLE_EVERY, (t1 - t0) / MAX_SAMPLES)
    faces, times, grays = [], [], []
    t = t0
    try:
        while t < t1:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                break
            img = cv2.resize(frame, size)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            rel = round(t - t0, 3)
            times.append(rel)
            grays.append(gray)
            for x, y, w, h in detect(img, gray):
                faces.append((rel, x / scale, y / scale, w / scale, h / scale))
            t += step
    finally:
        cap.release()
    return faces, times, grays, scale


def _tracks(faces):
    """Group detections into tracks: a face belongs to a track when its centre is within
    one face-width of the track's last position."""
    tracks = []
    for f in sorted(faces):
        cx, cy = f[1] + f[3] / 2, f[2] + f[4] / 2
        for tr in tracks:
            last = tr[-1]
            if last[0] != f[0] and abs(last[1] + last[3] / 2 - cx) < last[3] and \
                    abs(last[2] + last[4] / 2 - cy) < last[4]:
                tr.append(f)
                break
        else:
            tracks.append([f])
    return tracks


def _alive(track, grays, scale):
    """Average pixel change inside the face box over time (posters and thumbnails stay ~0)."""
    if len(grays) < 3:
        return 10.0
    box = np.median(np.array([f[1:] for f in track]), axis=0) * scale
    x, y, w, h = (int(v) for v in box)
    patch = np.stack([g[max(0, y):y + max(1, h), max(0, x):x + max(1, w)].astype(np.float32) for g in grays])
    return float(patch.std(axis=0).mean()) if patch.size else 0.0


def main_face(faces, times, grays, scale):
    """The streamer's face box (x, y, w, h) in source px, or None: the track seen in the most
    frames, ignoring faces that never move."""
    best, best_n = None, 0
    for tr in _tracks(faces):
        n = len({f[0] for f in tr})
        if n < max(2, 0.3 * len(times)) or _alive(tr, grays, scale) < 2.5:
            continue
        if n > best_n:
            best, best_n = tuple(np.median(np.array([f[1:] for f in tr]), axis=0)), n
    return best


def cam_box(face, info):
    """The facecam rectangle around a face: a fixed number of face sizes, face slightly above
    the middle, clamped to the picture."""
    x, y, w, h = face
    bw, bh = CAM_W * w, CAM_H * h
    bx = x + w / 2 - bw / 2
    by = y + h * 0.45 - bh * 0.42
    bx, by = max(0.0, bx), max(0.0, by)
    return (bx, by, min(bw, info["width"] - bx), min(bh, info["height"] - by))


def _fit(cfg, info):
    W, H = cfg["output_width"], cfg["output_height"]
    return (f"[0:v]split=2[back][front];"
            f"[back]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"gblur=sigma=30,eq=brightness=-0.1[blur];"
            f"[front]scale={W}:-2:flags=lanczos,setsar=1[sharp];"
            f"[blur][sharp]overlay=0:(H-h)/2,format=yuv420p[vout]")


def _face(cfg, info, face):
    W, H = cfg["output_width"], cfg["output_height"]
    sw, sh = info["width"], info["height"]
    cw = even(min(sw, sh * W / H))
    cx = even(min(max(face[0] + face[2] / 2 - cw / 2, 0), sw - cw))
    return (f"[0:v]crop={cw}:{even(sh)}:{cx}:0,scale={W}:{H}:flags=lanczos,setsar=1,"
            f"format=yuv420p[vout]")


def _stream(cfg, info, cam, grays=None, times=None, scale=1.0):
    """Facecam panel on top; below, a punched-in game crop fixed on the centre of the picture
    (or following the action when focus_follow is on)."""
    W, H = cfg["output_width"], cfg["output_height"]
    top = even(cfg["cam_height"])
    bot = H - top
    sw, sh = info["width"], info["height"]
    x, y, w, h = cam
    x0, y0 = max(0.0, x), max(0.0, y)
    w, h = max(2.0, min(x + w, sw) - x0), max(2.0, min(y + h, sh) - y0)
    x, y = x0, y0
    panel = W / top
    cw, ch = (h * panel, h) if w / h > panel else (w, w / panel)
    cx = min(max(x + (w - cw) / 2, 0), sw - cw)
    cy = min(max(y + (h - ch) / 2, 0), sh - ch)
    gh = even(min(sh, sh * cfg["focus_zoom"]))
    gw = even(min(sw, gh * W / bot))
    if cfg.get("focus_follow") and grays and times and len(grays) == len(times):
        s = scale
        keys = focus.plan(list(times), focus.centers(list(grays), cam=(x * s, y * s, w * s, h * s)),
                          frame=(sw * s, sh * s), crop=(gw * s, gh * s))
        keys = [(t, kx / s, ky / s) for t, kx, ky in keys]
        gx, gy = f"'{focus.expr(keys, 1)}'", f"'{focus.expr(keys, 2)}'"
    else:
        gx, gy = even((sw - gw) / 2), even((sh - gh) / 2)
    return (f"[0:v]split=2[a][b];"
            f"[a]crop={even(cw)}:{even(ch)}:{even(cx)}:{even(cy)},"
            f"scale={W}:{top}:flags=lanczos,setsar=1[cam];"
            f"[b]crop={gw}:{gh}:{gx}:{gy},scale={W}:{bot}:flags=lanczos,setsar=1[game];"
            f"[cam][game]vstack=inputs=2,format=yuv420p[vout]")


def graph(source, t0, t1, cfg, info, known=None, analysis=None, quiet=False):
    """(filtergraph, look, top-panel height or None) for the clip [t0, t1] of `source`.
    `known` remembers this stream's facecam so a clip where the face is hidden still gets it."""
    _local.quiet = quiet
    try:
        known = known if known is not None else {}
        want = cfg["layout"]
        if want == "fit":
            return _fit(cfg, info), "fit", None
        faces, times, grays, scale = analysis or analyze(source, t0, t1, info)
        face = main_face(faces, times, grays, scale)
        if face is None and known.get("face"):
            face = known["face"]
            _note("  face not visible here: using the streamer's cam from this stream's other clips")
        if face is None:
            _note("  nobody on screen: whole frame")
            return _fit(cfg, info), "fit", None
        known.setdefault("face", face)
        if want in ("auto", "face") and face[2] / info["width"] >= BIG_FACE:
            _note("  streamer fills the picture: crop on them")
            return _face(cfg, info, face), "face", None
        cam = cam_box(face, info)
        _note(f"  facecam {int(cam[2])}x{int(cam[3])} at {int(cam[0])},{int(cam[1])}")
        return _stream(cfg, info, cam, grays, times, scale), "stream", even(cfg["cam_height"])
    finally:
        _local.quiet = False
