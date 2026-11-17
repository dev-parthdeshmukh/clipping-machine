import numpy as np
from PIL import Image

from gta6clip import config, hook


def test_parse_keyword():
    assert hook.parse("Easiest *Size* Comparison 😭") == [("Easiest", False), ("Size", True), ("Comparison", False), ("😭", False)]
    assert [k for _, k in hook.parse("No marker here")] == [False, True, False]   # longest word fallback


def test_title_has_no_box_and_fits(tmp_path):
    p, w, h = hook.render("Speed Finds *Scuba* Diving 🤯", config.load(), tmp_path / "t.png")
    img = np.asarray(Image.open(p).convert("RGBA"))
    assert w <= 1080 - 2 * 60 and 60 < h < 260
    assert img[0, 0, 3] == 0 and img[-1, -1, 3] == 0                 # transparent corners: no box
    rgb = img[..., :3][img[..., 3] > 200]
    yellow = ((rgb[:, 0] > 220) & (rgb[:, 1] > 190) & (rgb[:, 2] < 90)).sum()
    white = ((rgb > 235).all(axis=1)).sum()
    assert yellow > 300 and white > 300                               # keyword yellow, rest white


def test_hook_emoji_is_colour(tmp_path):
    p, w, h = hook.render("😭", config.load(), tmp_path / "e.png")
    px = Image.open(p).convert("RGB").getcolors(1 << 20)
    assert len([c for n, c in px if len(set(c)) > 1]) > 20


def test_hook_unknown_emoji_font_skips_not_tofu(tmp_path):
    cfg = config.load({"emoji_fonts": [str(tmp_path / "missing.ttf")]})
    p, w, h = hook.render("WOW 😭", cfg, tmp_path / "x.png")
    p2, w2, h2 = hook.render("WOW", cfg, tmp_path / "y.png")
    assert w == w2 and h == h2
