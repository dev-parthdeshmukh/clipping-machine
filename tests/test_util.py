from pathlib import Path

from gta6clip import util


def test_slugify_windows_safe():
    assert util.slugify('xQc: GTA 6 "LAUNCH" | día 1?') == "xqc-gta-6-launch-día-1"
    assert util.slugify("") == "clip"


def test_ass_path_escapes_drive():
    assert util.ass_path(Path(r"C:\Users\a b\x.ass")) == r"C\:/Users/a b/x.ass"


def test_hhmmss_and_minutes():
    assert util.hhmmss(3725) == "1:02:05"
    assert util.minutes(14949) == "4 h 09 min" and util.minutes(40) == "40 s"


def test_run_raises_with_tail():
    import pytest
    with pytest.raises(RuntimeError, match="command failed"):
        util.run(["python", "-c", "import sys; print('boom'); sys.exit(3)"])
    assert util.run(["python", "-c", "print('héllo 😭')"]).strip() == "héllo 😭"
