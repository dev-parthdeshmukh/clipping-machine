import pytest

from gta6clip import config


def test_defaults_match_spec():
    cfg = config.load()
    assert (cfg["output_width"], cfg["output_height"]) == (1080, 1920)
    assert cfg["scan_model"] == "small" and cfg["caption_model"] == "large-v3-turbo"
    assert cfg["score_bar"] == 70 and cfg["clips_per_stream"] == 3
    assert (cfg["min_duration"], cfg["max_duration"]) == (45, 150)
    assert (cfg["target_min"], cfg["target_max"]) == (60, 120)
    assert cfg["caption_font"] == "Montserrat Black"
    assert cfg["narrator_fallback_voice"] == "am_michael"
    assert cfg["voice_profile"] == ""


def test_house_style_defaults():
    cfg = config.load()
    assert cfg["narrator"] == "none"                      # no narrated intro (house style)
    assert cfg["zoom_scale"] == 1.0                        # no whole-frame punch-in; the game crop zooms
    assert cfg["uppercase"] is False and cfg["words_per_group"] == 3
    assert cfg["caption_y"] == 0.5 and cfg["cam_height"] == 760
    assert cfg["title_font_file"].endswith("Montserrat-Black.ttf") and cfg["title_size"] == 64
    assert cfg["focus_zoom"] == 0.8


def test_user_json_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    (tmp_path / "config.json").write_text('{"score_bar": 60, "font_size": 90}', encoding="utf-8")
    cfg = config.load({"clips_per_stream": 5, "font_size": None})
    assert cfg["score_bar"] == 60 and cfg["font_size"] == 90 and cfg["clips_per_stream"] == 5


def test_bad_json_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    (tmp_path / "config.json").write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit):
        config.load()


def test_clip_length_one_to_two_minutes():
    cfg = config.load()
    assert (cfg["min_duration"], cfg["max_duration"]) == (45, 150)
    assert (cfg["target_min"], cfg["target_max"]) == (60, 120)


def test_house_style_always_splits_streamer_and_game():
    assert config.load()["layout"] == "stream"
