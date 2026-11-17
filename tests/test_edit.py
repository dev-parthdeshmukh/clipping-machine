import numpy as np
import pytest

from gta6clip import edit


def w(s, e):
    return {"s": s, "e": e, "w": "x"}


def test_keep_segments_trims_long_gaps():
    words = [w(100.0, 100.5), w(100.6, 101.0), w(103.0, 103.5)]
    segs = edit.keep_segments(words, 100.0, 104.0)
    assert segs == [(0.0, pytest.approx(1.075)), (pytest.approx(2.925), 4.0)]


def test_keep_segments_no_words_keeps_all():
    assert edit.keep_segments([], 100.0, 130.0) == [(0.0, 30.0)]


def test_keep_segments_trims_leading_silence():
    segs = edit.keep_segments([w(105.0, 106.0)], 100.0, 107.0)
    assert segs == [(pytest.approx(4.925), 7.0)]


def test_gap_with_sound_is_kept_quiet_gap_is_cut():
    words = [w(100.0, 100.5), w(103.0, 103.5)]
    loud = np.zeros(200)                              # trailer audio / scream in the gap: not dead air
    assert edit.keep_segments(words, 100.0, 104.0, loud=loud) == [(0.0, 4.0)]
    loud[100:104] = -12.0                             # genuinely quiet gap
    segs = edit.keep_segments(words, 100.0, 104.0, loud=loud)
    assert segs == [(0.0, pytest.approx(0.575)), (pytest.approx(2.925), 4.0)]


def test_quiet_leading_gap_only():
    loud = np.zeros(200)
    assert edit.keep_segments([w(105.0, 106.0)], 100.0, 107.0, loud=loud) == [(0.0, 7.0)]


def test_remap_and_words():
    segs = [(0.0, 1.075), (2.925, 4.0)]
    assert edit.remap(3.0, segs) == pytest.approx(1.15)
    out = edit.remap_words([w(100.0, 100.5), w(103.0, 103.5)], 100.0, segs)
    assert out[1]["s"] == pytest.approx(1.15) and out[1]["e"] == pytest.approx(1.65)


def test_remap_words_drops_cut_words():
    out = edit.remap_words([w(102.0, 102.2)], 100.0, [(0.0, 1.0), (3.0, 4.0)])
    assert out == []


def test_zoom_points_spaced():
    loud = np.zeros(200)
    loud[[110, 111, 112, 130]] = 10
    assert edit.zoom_points(loud, 100.0, [(0.0, 60.0)], 8.0) == [10.0, 30.0]


def test_zoom_points_in_output_time_and_skip_cut():
    loud = np.zeros(200)
    loud[[105, 120]] = 10                       # 105 is inside a cut, 120 maps to 20-5=15
    assert edit.zoom_points(loud, 100.0, [(0.0, 3.0), (8.0, 40.0)], 8.0) == [15.0]


def test_payoff_time():
    loud = np.zeros(200)
    loud[125] = 12
    assert edit.payoff_time(loud, 100.0, 140.0) == 125.0
    assert edit.payoff_time(np.zeros(200), 100.0, 140.0) == 120.0
