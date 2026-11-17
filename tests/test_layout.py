import numpy as np

from gta6clip import config, layout

INFO = {"width": 1920, "height": 1080}


def _grays(n, moving_box=None, still_box=None, scale=0.5):
    rng = np.random.default_rng(0)
    out = []
    for i in range(n):
        g = np.zeros((540, 960), dtype=np.uint8)
        if moving_box:
            x, y, w, h = (int(v * scale) for v in moving_box)
            g[y:y + h, x:x + w] = rng.integers(0, 255, (h, w))
        if still_box:
            x, y, w, h = (int(v * scale) for v in still_box)
            g[y:y + h, x:x + w] = 128
        out.append(g)
    return out


def test_main_face_prefers_live_face_over_poster():
    times = [i * 0.6 for i in range(10)]
    cam = (100, 700, 120, 140)
    poster = (1500, 100, 120, 140)
    faces = [(t, *cam) for t in times] + [(t, *poster) for t in times]
    grays = _grays(10, moving_box=cam, still_box=poster)
    face = layout.main_face(faces, times, grays, 0.5)
    assert face is not None and abs(face[0] - 100) < 1


def test_main_face_needs_persistence():
    times = [i * 0.6 for i in range(10)]
    faces = [(times[0], 100, 700, 120, 140)]                 # one stray detection
    assert layout.main_face(faces, times, _grays(10), 0.5) is None


def test_cam_box_clamped_and_sized():
    x, y, w, h = layout.cam_box((40, 960, 100, 110), INFO)
    assert x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080
    assert w > 300 and h > 200


def test_graph_no_face_is_fit_and_known_cam_reused():
    cfg = config.load()
    times = [i * 0.6 for i in range(10)]
    empty = ([], times, _grays(10), 0.5)
    chain, look, cam_h = layout.graph(None, 0, 6, cfg, INFO, known={}, analysis=empty, quiet=True)
    assert look == "fit" and cam_h is None
    chain, look, cam_h = layout.graph(None, 0, 6, cfg, INFO, known={"face": (100, 700, 120, 140)},
                                      analysis=empty, quiet=True)
    assert look == "stream" and cam_h == 760
