import json

from gta6clip import post


def test_post_md_per_platform(tmp_path):
    clip = {"file": "01_x.mp4", "hook_text": "H 😭", "kind": "reaction", "duration": 31.0, "score": 91,
            "captions": {"tiktok": "tt", "shorts": "ss", "reels": "rr"}, "hashtags": ["#gta6"],
            "reason": "r", "stream_start": 3725.0, "narrator_line": "n", "narrator_engine": "kokoro"}
    post.write(tmp_path, {"name": "xQc", "title": "GTA 6", "url": "u"}, [clip], "sum")
    md = (tmp_path / "POST.md").read_text(encoding="utf-8")
    for s in ("H 😭", "TikTok", "tt", "Shorts", "ss", "Reels", "rr", "#gta6", "1:02:05", "voice: kokoro"):
        assert s in md
    data = json.loads((tmp_path / "clips.json").read_text(encoding="utf-8"))
    assert data["clips"][0]["file"] == "01_x.mp4"


def test_post_md_title_description_credit(tmp_path):
    clip = {"file": "01_x.mp4", "hook_text": "H", "kind": "discovery", "duration": 30.0, "score": 90,
            "captions": {}, "hashtags": ["#gta6", "#shorts"], "reason": "r", "stream_start": 10.0,
            "post_title": "Speed finds SCUBA 🤯", "description": "Speed loses it.", "narrator_engine": "voxcpm2"}
    post.write(tmp_path, {"name": "IShowSpeed", "title": "GTA 6", "url": "https://yt/x"}, [clip], "sum")
    md = (tmp_path / "POST.md").read_text(encoding="utf-8")
    assert "**Title:** Speed finds SCUBA 🤯" in md
    assert "**Description:**\nSpeed loses it.\n\nCredit: IShowSpeed (https://yt/x)\n#gta6 #shorts" in md
    assert "**Hashtags:** #gta6 #shorts" in md


def test_post_md_no_clips(tmp_path):
    post.write(tmp_path, {"name": "xQc", "title": "GTA 6", "url": "u"}, [], "sum")
    assert "No clips" in (tmp_path / "POST.md").read_text(encoding="utf-8")
