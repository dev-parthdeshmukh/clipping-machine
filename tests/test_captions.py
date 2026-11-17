import subprocess

import pytest

from gta6clip import captions, config, util


def test_ass_style_spec(tmp_path):
    p = captions.build([{"s": 0.1, "e": 0.5, "w": "it's"}, {"s": 0.6, "e": 0.9, "w": "{100%}"}],
                       2.0, tmp_path / "c.ass", config.load())
    t = p.read_text(encoding="utf-8")
    assert "Style: Pop,Montserrat Black,82," in t
    assert ",1,8,4,2,70,140,960,1" in t        # border style, outline 8, shadow 4, bottom-centre, margins L/R/V (y 0.5)
    assert "&H003BE1FF" in t                    # highlight FFE13B in ASS byte order
    assert "it's" in t and "(100%)" in t and "{100%}" not in t


def test_y_override_moves_text(tmp_path):
    p = captions.build([{"s": 0.0, "e": 0.5, "w": "hi"}], 1.0, tmp_path / "c.ass", config.load(), y=0.45)
    assert ",70,140,1056,1" in p.read_text(encoding="utf-8")     # 1920*(1-0.45)


def test_escape():
    assert captions.escape(r"a{b}\c") == "a(b)c"


@pytest.mark.slow
def test_libass_picks_bundled_font(tmp_path):
    ass = captions.build([{"s": 0.0, "e": 1.0, "w": "hi"}], 1.0, tmp_path / "c.ass", config.load())
    log = subprocess.run(["ffmpeg", "-v", "verbose", "-f", "lavfi", "-i", "color=s=1080x1920:d=1", "-vf",
                          f"ass=f='{util.ass_path(ass)}':fontsdir='{util.ass_path(config.FONTS)}'",
                          "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    assert "Montserrat-Black" in log or "Montserrat Black" in log.split("fontselect")[-1]
