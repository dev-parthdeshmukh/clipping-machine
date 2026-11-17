"""The narrator: one short line per clip, in the channel voice.

Primary: VoxCPM2 (Apache-2.0) cloning the VoiceStudio profile `voice_profile` in
continuation mode, run as ONE batch in VoiceStudio's own VoxCPM2 venv (one model load).
Fallback, per line: Kokoro `narrator_fallback_voice` on the CPU. Results are cached by
(engine, profile, text) so re-runs never re-synthesise."""

import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

from . import config
from .util import log, run

API = "http://127.0.0.1:3900"
WORKER = Path(__file__).resolve().parent / "workers" / "voxcpm_worker.py"


def _fetch_profile(cfg):
    """(audio bytes, reference transcript) of the VoiceStudio profile. Needs VoiceStudio open."""
    pid = cfg["voice_profile"]
    with urllib.request.urlopen(f"{API}/profiles", timeout=10) as r:
        profiles = json.loads(r.read().decode("utf-8"))
    prof = next((p for p in profiles if p.get("id") == pid), None)
    if not prof:
        raise OSError(f"VoiceStudio has no voice profile {pid}")
    with urllib.request.urlopen(f"{API}/profiles/{pid}/audio", timeout=30) as r:
        audio = r.read()
    return audio, prof.get("ref_text") or ""


def _ensure_reference(cfg):
    """(16 kHz mono wav, transcript) of the reference voice, cached in ENV_DIR/voice."""
    vdir = config.ENV_DIR / "voice"
    wav, txt = vdir / f"{cfg['voice_profile']}.wav", vdir / f"{cfg['voice_profile']}.txt"
    if wav.exists() and txt.exists():
        return wav, txt.read_text(encoding="utf-8")
    audio, text = _fetch_profile(cfg)
    vdir.mkdir(parents=True, exist_ok=True)
    raw = vdir / f"{cfg['voice_profile']}.src"
    raw.write_bytes(audio)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ac", "1", "-ar", "16000", str(wav)])
    raw.unlink(missing_ok=True)
    txt.write_text(text, encoding="utf-8")
    return wav, text


def _voxcpm_batch(items, cfg):
    """Run the worker once for all items. Returns {out_path: ok}."""
    ref_wav, ref_text = _ensure_reference(cfg)
    jobs = config.HOME / "work" / "voice" / "jobs.json"
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text(json.dumps({"snapshot": str(config.VOXCPM_SNAPSHOT), "ref_wav": str(ref_wav),
                                "ref_text": ref_text, "items": items}, ensure_ascii=False), encoding="utf-8")
    log(f"narrating {len(items)} line(s) with VoxCPM2 (~2 min each on a 6 GB GPU)...", "step")
    proc = subprocess.run([str(config.VOXCPM_PY), str(WORKER), str(jobs)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300 * len(items) + 300)
    done = {}
    for line in proc.stdout.splitlines():
        try:
            r = json.loads(line)
            done[r["out"]] = bool(r.get("ok")) and Path(r["out"]).exists()
        except (ValueError, KeyError):
            continue
    if proc.returncode != 0 and not any(done.values()):
        log(f"VoxCPM2 failed: {(proc.stderr or '').strip().splitlines()[-1:] or proc.returncode}", "warn")
    return {i["out"]: done.get(i["out"], False) for i in items}


_KOKORO = {}


def _kokoro(text, out, cfg):
    """One line with Kokoro (CPU), 24 kHz wav."""
    import numpy as np
    import soundfile as sf
    if "pipe" not in _KOKORO:
        from kokoro import KPipeline
        _KOKORO["pipe"] = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    audio = np.concatenate([a.numpy() for _, _, a in
                            _KOKORO["pipe"](text, voice=cfg["narrator_fallback_voice"], speed=1.1)])
    sf.write(str(out), audio, 24000)
    return Path(out)


def _key(engine, cfg, text):
    return hashlib.sha1(f"{engine}|{cfg['voice_profile']}|{text}".encode("utf-8")).hexdigest()[:16]


def synth(lines, outdir, cfg):
    """{key: text} -> {key: (wav path, engine)}. Every line gets a voice: VoxCPM2 when it
    works, Kokoro for whatever it could not make."""
    cache = config.HOME / "work" / "voice"
    cache.mkdir(parents=True, exist_ok=True)
    engine = cfg["narrator"]                         # a cached Kokoro fallback is retried with VoxCPM2
    result, todo = {}, {}
    for key, text in lines.items():
        hit = cache / f"{_key(engine, cfg, text)}_{engine}.wav"
        if hit.exists():
            result[key] = (hit, engine)
        else:
            todo[key] = text
    if todo and cfg["narrator"] == "voxcpm2":
        items = [{"text": t, "out": str(cache / f"{_key('voxcpm2', cfg, t)}_voxcpm2.wav")} for t in todo.values()]
        try:
            ok = _voxcpm_batch(items, cfg)
        except Exception as exc:                     # VoiceStudio down / bad reply / worker crash
            log(f"VoxCPM2 unavailable ({str(exc)[:100]}); using Kokoro", "warn")
            ok = {}
        for key, text in list(todo.items()):
            out = cache / f"{_key('voxcpm2', cfg, text)}_voxcpm2.wav"
            if ok.get(str(out)):
                result[key] = (out, "voxcpm2")
                del todo[key]
    for key, text in todo.items():
        out = cache / f"{_key('kokoro', cfg, text)}_kokoro.wav"
        try:
            result[key] = (_kokoro(text, out, cfg), "kokoro")
            log(f"  '{text[:40]}' voiced by Kokoro", "warn" if cfg["narrator"] == "voxcpm2" else "info")
        except Exception as exc:                     # this clip ships without an intro
            log(f"  '{text[:40]}' not voiced ({str(exc)[:80]}): clip gets no intro", "warn")
    return result
