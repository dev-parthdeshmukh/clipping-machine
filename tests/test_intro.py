from gta6clip import intro


def test_script_words_use_script_text_with_heard_timing():
    heard = [{"s": 0.1, "e": 0.3, "w": "Chi"}, {"s": 0.3, "e": 0.6, "w": "Cenat"}, {"s": 0.7, "e": 0.8, "w": "was"},
             {"s": 0.9, "e": 1.1, "w": "not"}, {"s": 1.2, "e": 1.5, "w": "ready"}]
    out = intro.script_words("Kai Cenat was NOT ready", heard, 2.0)
    assert [w["w"] for w in out] == ["Kai", "Cenat", "was", "NOT", "ready"]
    assert out[3]["s"] == 0.9


def test_script_words_count_mismatch_spreads_over_heard_span():
    heard = [{"s": 0.5, "e": 1.0, "w": "xqc"}, {"s": 1.0, "e": 2.5, "w": "gta six"}]
    out = intro.script_words("Look what xQc found in GTA 6", heard, 3.0)
    assert [w["w"] for w in out] == ["Look", "what", "xQc", "found", "in", "GTA", "6"]
    assert out[0]["s"] == 0.5 and abs(out[-1]["e"] - 2.5) < 1e-9
    assert all(a["e"] <= b["s"] + 1e-9 for a, b in zip(out, out[1:]))


def test_script_words_nothing_heard_spreads_over_voice():
    out = intro.script_words("Kai was NOT ready", [], 2.0)
    assert out[0]["s"] == 0.0 and abs(out[-1]["e"] - 2.0) < 1e-9
