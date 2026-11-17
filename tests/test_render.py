import pytest

from gta6clip import config, intro, render, util


def test_encoder_args(monkeypatch):
    cfg = config.load()
    monkeypatch.setattr(util, "nvenc_available", lambda: True)
    assert render.encoder_args(cfg)[:2] == ["-c:v", "h264_nvenc"] and "-cq" in render.encoder_args(cfg)
    monkeypatch.setattr(util, "nvenc_available", lambda: False)
    assert render.encoder_args(cfg)[:2] == ["-c:v", "libx264"]
    monkeypatch.setattr(util, "nvenc_available", lambda: True)
    assert render.encoder_args(config.load({"encoder": "libx264"}))[:2] == ["-c:v", "libx264"]


def test_zoom_expr_ramps_and_holds():
    e = render.zoom_expr([10.0], config.load({"zoom_scale": 1.12}))
    f = eval(e.replace("min(", "_min(").replace("max(", "_max(").replace("t", "T"),
             {"_min": min, "_max": max, "T": 10.125})
    assert f == pytest.approx(1.06, abs=0.001)            # halfway up the 0.25 s ramp to 1.12
    assert eval(e.replace("min(", "_min(").replace("max(", "_max(").replace("t", "T"),
                {"_min": min, "_max": max, "T": 11.0}) == pytest.approx(1.12)
    assert render.zoom_expr([], config.load()) == "1"


def test_cut_graph_single_segment_is_passthrough():
    g, v, a = render.cut_graph([(0.0, 10.0)], "vout", "0:a")
    assert "concat" not in g and v and a


def test_cut_graph_uses_trim_and_concat():
    g, v, a = render.cut_graph([(0.0, 1.0), (2.0, 4.0)], "vout", "0:a")
    assert "trim=start=0.000:end=1.000" in g and "atrim=start=2.000:end=4.000" in g
    assert "concat=n=2:v=1:a=1" in g and "select" not in g


@pytest.mark.slow
def test_cuts_keep_audio_video_in_sync(tmp_path):
    import json
    src = tmp_path / "s.mp4"
    util.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=40", "-f", "lavfi",
              "-i", "sine=f=300:d=40", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(src)])
    segs = [(i * 2.0, i * 2.0 + 1.37) for i in range(19)]
    g, v, a = render.cut_graph(segs, "0:v", "0:a")
    out = tmp_path / "o.mp4"
    util.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", g, "-map", f"[{v}]",
              "-map", f"[{a}]", "-r", "30", "-c:a", "aac", str(out)])
    streams = json.loads(util.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)]))["streams"]
    durs = {s["codec_type"]: float(s["duration"]) for s in streams}
    assert abs(durs["video"] - durs["audio"]) < 0.05


@pytest.mark.slow
def test_zoom_stays_centred(tmp_path):
    import numpy as np
    from PIL import Image
    png = tmp_path / "f.png"
    flt = f"drawbox=x=520:y=940:w=40:h=40:color=white:t=fill,{render.zoom_filter([0.0], config.load({'zoom_scale': 1.12}))}"
    util.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=1080x1920:r=30:d=2",
              "-vf", flt, "-ss", "1.0", "-frames:v", "1", str(png)])
    a = np.asarray(Image.open(png).convert("L"))
    ys, xs = np.nonzero(a > 128)
    assert abs(xs.mean() - 540) < 4 and abs(ys.mean() - 960) < 4
    assert xs.max() - xs.min() > 42                  # zoomed in: the box grew


@pytest.mark.slow
def test_whoosh(tmp_path):
    p = intro.whoosh(tmp_path / "w.wav")
    assert 0.45 < util.probe(p)["duration"] < 0.55


@pytest.mark.slow
def test_finish_end_to_end_synthetic(tmp_path):
    part = tmp_path / "part.mp4"   # 20 s 1920x1080 testsrc + tone, stands in for a stream section
    util.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=20", "-f", "lavfi",
              "-i", "sine=f=300:d=20", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(part)])
    voice = tmp_path / "v.wav"
    util.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=2", str(voice)])
    p = render.prepare_local(part, {"start": 2.0, "end": 16.0, "hook_text": "XQC can't BELIEVE this 💀",
                                    "narrator_line": "Look what xQc just found: it's 100% real", "title": "t",
                                    "kind": "reaction", "score": 90, "caption": "c", "hashtags": []},
                             1, tmp_path, config.load())
    rec = render.finish(p, (voice, "voxcpm2"), tmp_path, tmp_path, config.load(), {})
    info = util.probe(tmp_path / rec["file"])
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 14.0 < info["duration"] < 18.0          # 2 s narration + 0.3 + <=14 s body
    assert (tmp_path / rec["cover"]).exists() and rec["narrator_engine"] == "voxcpm2"


@pytest.mark.slow
def test_locate_finds_clip_in_stream_audio(tmp_path):
    import numpy as np
    import soundfile as sf
    rng = np.random.default_rng(1)
    rate = 8000
    env = np.repeat(rng.random(120 * 10), rate // 10)               # 120 s of changing loudness
    stream = (rng.standard_normal(env.size) * env * 0.3).astype(np.float32)
    sf.write(tmp_path / "stream.wav", stream, rate)
    sf.write(tmp_path / "clip.wav", stream[int(57.3 * rate):int(87.3 * rate)], rate)
    at, conf = render.locate(tmp_path / "clip.wav", tmp_path / "stream.wav", guess=50.0)
    assert abs(at - 57.3) < 0.05 and conf > 0.8
