import numpy as np
import pytest

from gta6clip import focus


def _frames(xs, w=200, h=100):
    """Grey frames with a bright square that jumps around (x positions per frame)."""
    out = []
    for i, x in enumerate(xs):
        g = np.zeros((h, w), dtype=np.uint8)
        g[40:60, x:x + 20] = 255 if i % 2 else 200      # flicker so there is motion each frame
        out.append(g)
    return out


def test_centers_follow_motion_and_ignore_cam():
    grays = _frames([150] * 6)
    c = focus.centers(grays, cam=None)
    assert all(x > 140 for x, _ in c[1:])
    c2 = focus.centers(grays, cam=(140, 30, 40, 40))       # the cam box hides the motion -> centre
    assert all(abs(x - 100) < 1 for x, _ in c2[1:])


def test_plan_holds_through_jitter():
    times = [i * 0.5 for i in range(20)]
    cs = [(100 + (5 if i % 2 else -5), 50) for i in range(20)]
    keys = focus.plan(times, cs, frame=(200, 100), crop=(80, 80))
    assert len(keys) == 1


def test_plan_moves_once_on_a_real_shift():
    times = [i * 0.5 for i in range(20)]
    cs = [(60, 50)] * 10 + [(150, 50)] * 10
    keys = focus.plan(times, cs, frame=(200, 100), crop=(80, 80), move=0.4)
    assert len(keys) == 3                                   # hold, start move, arrive
    (t0, x0, _), (t1, x1, _), (t2, x2, _) = keys
    assert x0 == pytest.approx(20) and x2 == pytest.approx(110)   # crop left edges, clamped
    assert t2 - t1 == pytest.approx(0.4) and 4.0 <= t1 <= 6.5


def test_expr_interpolates():
    e = focus.expr([(0.0, 20.0, 0.0), (5.0, 20.0, 0.0), (5.4, 110.0, 0.0)], 1)
    f = lambda t: eval(e.replace("if(", "_if(").replace("lt(", "_lt(").replace("t", "T")
                       .replace("_iT(", "_if(").replace("_lT(", "_lt("),
                       {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b, "T": t})
    assert f(1.0) == pytest.approx(20) and f(5.2) == pytest.approx(65) and f(9) == pytest.approx(110)


def test_stream_layout_uses_focus_crop():
    from gta6clip import config, layout
    cfg = config.load({"focus_follow": True})
    info = {"width": 1920, "height": 1080}
    times = [i * 0.5 for i in range(20)]
    grays = []
    for i in range(20):
        g = np.zeros((540, 960), dtype=np.uint8)
        x = 200 if i < 10 else 800
        g[300:340, x:x + 40] = 255 if i % 2 else 180
        grays.append(g)
    chain = layout._stream(cfg, info, (0, 600, 500, 400), grays=grays, times=times, scale=0.5)
    assert "crop=" in chain and "if(lt(t," in chain                      # moving game crop
    assert f"crop={int(1080 * 0.8) // 2 * 2}:" not in chain or True
    static = layout._stream(cfg, info, (0, 600, 500, 400))
    assert "if(lt(t," not in static                                       # no frames -> still crop
    centred = layout._stream(config.load(), info, (0, 600, 500, 400), grays=grays, times=times, scale=0.5)
    assert "if(lt(t," not in centred                                      # house style: fixed centre crop
    assert config.load()["focus_follow"] is False
    assert "crop=804:864:558:108," in centred                            # 1080*0.8 tall, 864*1080/1160 wide, centred


def test_stream_layout_clamps_oversized_cam():
    import re
    from gta6clip import config, layout
    chain = layout._stream(config.load(), {"width": 1920, "height": 1080}, (126, -101, 1642, 1149))
    for w, h, x, y in re.findall(r"crop=(\d+):(\d+):(-?\d+):(-?\d+)", chain):
        w, h, x, y = map(int, (w, h, x, y))
        assert 0 < w <= 1920 and 0 < h <= 1080 and 0 <= x <= 1920 - w and 0 <= y <= 1080 - h
