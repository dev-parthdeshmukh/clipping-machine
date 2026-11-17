import json

import numpy as np
import pytest

from gta6clip import scan, util


def test_relative_flags_spike():
    v = [-30.0] * 300
    v[150] = -15.0
    r = scan.relative(v)
    assert r[150] == pytest.approx(15.0, abs=0.5) and abs(r[10]) < 0.5


def test_relative_short_input_is_zero():
    assert list(scan.relative([1.0, 2.0])) == [0.0, 0.0]


def test_device_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(scan, "_cuda_ok", lambda: False)
    assert scan.device() == ("cpu", "int8")
    monkeypatch.setattr(scan, "_cuda_ok", lambda: True)
    assert scan.device() == ("cuda", "float16")


def test_chat_rate_skips_non_youtube(tmp_path):
    assert scan.chat_rate("u", [], tmp_path, {"chat": True}, {"extractor_key": "TwitchVod"}) is None


def test_chat_rate_buckets(tmp_path, monkeypatch):
    def fake_run(cmd, timeout=None):
        lines = [{"replayChatItemAction": {"videoOffsetTimeMsec": str(ms), "actions": [1]}}
                 for ms in (100, 4900, 5100, 12000)]
        (tmp_path / "chat.live_chat.json").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        return ""
    monkeypatch.setattr(scan, "run", fake_run)
    rate = scan.chat_rate("u", [], tmp_path, {"chat": True, "chat_timeout": 5},
                          {"extractor_key": "Youtube", "live_status": "was_live"})
    assert rate == [2, 1, 1]


class _Seg:
    def __init__(self, words):
        self.words = words


class _W:
    def __init__(self, s, e, w):
        self.start, self.end, self.word = s, e, w


class _Info:
    language = "en"


def test_words_from_retries_with_fallback_model_on_alignment_bug(monkeypatch):
    used = []

    class Broken:
        def transcribe(self, *a, **k):
            def gen():
                raise IndexError("boolean index did not match indexed array")
                yield
            return gen(), _Info()

    class Good:
        def transcribe(self, *a, **k):
            return iter([_Seg([_W(0.0, 0.4, " hi")])]), _Info()

    monkeypatch.setattr(scan, "_model", lambda name: used.append(name) or (Broken() if name == "large-v3-turbo" else Good()))
    words, lang = scan.words_from("large-v3-turbo", np.zeros(16000, dtype=np.float32), "en", offset=10.0)
    assert words == [{"s": 10.0, "e": 10.4, "w": "hi"}] and used == ["large-v3-turbo", "small"]


@pytest.mark.slow
def test_loudness_per_second(tmp_path):
    wav = tmp_path / "a.wav"
    util.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", "-af", "volume=0.5", str(wav)])
    out = scan.loudness(wav, tmp_path)
    # lavfi sine has amplitude 1/8; x0.5 -> peak 0.0625 -> RMS 0.0442 -> -27.1 dB
    assert len(out) == 3 and all(x == pytest.approx(-27.1, abs=0.5) for x in out)
