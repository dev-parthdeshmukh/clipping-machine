from pathlib import Path

from gta6clip import config, narrator


def _write_all(items, cfg):
    for i in items:
        Path(i["out"]).write_bytes(b"RIFF")
    return {i["out"]: True for i in items}


def test_cache_hit_skips_engines(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    calls = []
    monkeypatch.setattr(narrator, "_ensure_reference", lambda cfg: (tmp_path / "r.wav", "ref"))
    monkeypatch.setattr(narrator, "_voxcpm_batch", lambda items, cfg: calls.append(1) or _write_all(items, cfg))
    a = narrator.synth({"c1": "Look what xQc did"}, tmp_path, config.load({"narrator": "voxcpm2"}))
    b = narrator.synth({"c1": "Look what xQc did"}, tmp_path, config.load({"narrator": "voxcpm2"}))
    assert a["c1"][1] == "voxcpm2" and len(calls) == 1 and a == b and a["c1"][0].exists()


def test_one_batch_for_many_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    batches = []
    monkeypatch.setattr(narrator, "_ensure_reference", lambda cfg: (tmp_path / "r.wav", "ref"))
    monkeypatch.setattr(narrator, "_voxcpm_batch", lambda items, cfg: batches.append(len(items)) or _write_all(items, cfg))
    narrator.synth({"a": "one", "b": "two", "c": "three"}, tmp_path, config.load({"narrator": "voxcpm2"}))
    assert batches == [3]


def test_failed_items_fall_back_to_kokoro(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(narrator, "_ensure_reference", lambda cfg: (tmp_path / "r.wav", "ref"))
    monkeypatch.setattr(narrator, "_voxcpm_batch", lambda items, cfg: {i["out"]: False for i in items})
    monkeypatch.setattr(narrator, "_kokoro", lambda text, out, cfg: Path(out).write_bytes(b"RIFF") or Path(out))
    got = narrator.synth({"c1": "x", "c2": "y"}, tmp_path, config.load({"narrator": "voxcpm2"}))
    assert {e for _, e in got.values()} == {"kokoro"}


def test_voicestudio_down_uses_kokoro(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "ENV_DIR", tmp_path)

    def down(cfg):
        raise OSError("refused")
    monkeypatch.setattr(narrator, "_fetch_profile", down)
    monkeypatch.setattr(narrator, "_kokoro", lambda text, out, cfg: Path(out).write_bytes(b"RIFF") or Path(out))
    assert narrator.synth({"c1": "x"}, tmp_path, config.load({"narrator": "voxcpm2"}))["c1"][1] == "kokoro"


def test_voice_kokoro_setting_skips_voxcpm(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(narrator, "_voxcpm_batch", lambda items, cfg: (_ for _ in ()).throw(AssertionError("used")))
    monkeypatch.setattr(narrator, "_kokoro", lambda text, out, cfg: Path(out).write_bytes(b"RIFF") or Path(out))
    got = narrator.synth({"c1": "x"}, tmp_path, config.load({"narrator": "kokoro"}))
    assert got["c1"][1] == "kokoro"


def test_kokoro_failure_drops_only_that_line(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)

    def kok(text, out, cfg):
        if text == "bad":
            raise RuntimeError("espeak missing")
        Path(out).write_bytes(b"RIFF")
        return Path(out)
    monkeypatch.setattr(narrator, "_kokoro", kok)
    got = narrator.synth({"a": "ok", "b": "bad"}, tmp_path, config.load({"narrator": "kokoro"}))
    assert set(got) == {"a"}


def test_bad_voicestudio_reply_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "ENV_DIR", tmp_path)
    monkeypatch.setattr(narrator, "_fetch_profile", lambda cfg: (_ for _ in ()).throw(ValueError("bad json")))
    monkeypatch.setattr(narrator, "_kokoro", lambda text, out, cfg: Path(out).write_bytes(b"RIFF") or Path(out))
    assert narrator.synth({"c1": "x"}, tmp_path, config.load({"narrator": "voxcpm2"}))["c1"][1] == "kokoro"


def test_cached_reference_used_when_voicestudio_down(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_DIR", tmp_path)
    vdir = tmp_path / "voice"
    vdir.mkdir()
    (vdir / "abc123.wav").write_bytes(b"RIFF")
    (vdir / "abc123.txt").write_text("ref text", encoding="utf-8")
    monkeypatch.setattr(narrator, "_fetch_profile", lambda cfg: (_ for _ in ()).throw(OSError("down")))
    wav, text = narrator._ensure_reference(config.load({"voice_profile": "abc123"}))
    assert wav == vdir / "abc123.wav" and text == "ref text"
