"""Listening: what was said (Whisper on the GPU, with word times), how loud every second
was, and on YouTube replays how busy chat was. Everything runs on this PC."""

import gc
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

from .util import log, pcm, run

GPU = threading.Lock()      # one GPU job at a time (6 GB VRAM)
_MODELS = {}
_LOCK = threading.Lock()


def _add_cuda_dlls():
    """faster-whisper's CUDA libs come as pip wheels (nvidia-cublas/cudnn); expose their DLLs."""
    if os.name != "nt":
        return
    for site in map(Path, sys.path):
        nv = site / "nvidia"
        if nv.is_dir():
            for b in nv.glob("*/bin"):
                os.add_dll_directory(str(b))
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def _cuda_ok():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def device():
    """(device, compute_type) for Whisper: the GPU when CUDA works, else the CPU."""
    return ("cuda", "float16") if _cuda_ok() else ("cpu", "int8")


def _model(name):
    """One Whisper model per size, shared by streams processed in parallel."""
    with _LOCK:
        if name not in _MODELS:
            _add_cuda_dlls()
            from faster_whisper import WhisperModel
            dev, ct = device()
            log(f"loading Whisper '{name}' on {dev}...", "step")
            try:
                _MODELS[name] = WhisperModel(name, device=dev, compute_type=ct)
            except Exception as exc:                 # missing CUDA libs, out of VRAM
                if dev == "cpu":
                    raise
                log(f"GPU Whisper failed ({str(exc)[:80]}), using the CPU", "warn")
                _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8")
        return _MODELS[name]


def unload():
    """Free Whisper's VRAM before the narrator needs the GPU."""
    with _LOCK:
        _MODELS.clear()
    gc.collect()


def _decode(model_name, audio_array, language, offset):
    model = _model(model_name)
    words = []
    with GPU:
        segments, info = model.transcribe(audio_array, language=language, word_timestamps=True,
                                          vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                                          beam_size=5 if model_name not in ("tiny", "small") else 1,
                                          condition_on_previous_text=False)
        for seg in segments:                      # decoding happens while iterating: keep the lock
            words += [{"s": round(w.start + offset, 2), "e": round(w.end + offset, 2), "w": w.word.strip()}
                      for w in (seg.words or []) if w.word.strip()]
    return words, info.language


FALLBACK_MODEL = "small"


def words_from(model_name, audio_array, language, offset=0.0):
    """Word timings [{s, e, w}] for 16 kHz mono audio, shifted by `offset` seconds.
    faster-whisper's word alignment occasionally crashes on odd audio (IndexError in
    find_alignment); that audio is then decoded again with the smaller model."""
    np.seterr(divide="ignore", over="ignore", invalid="ignore")
    try:
        return _decode(model_name, audio_array, language, offset)
    except (IndexError, ValueError) as exc:
        if model_name == FALLBACK_MODEL:
            raise
        log(f"  Whisper '{model_name}' failed on this audio ({str(exc)[:60]}); retrying with '{FALLBACK_MODEL}'", "warn")
        return _decode(FALLBACK_MODEL, audio_array, language, offset)


def transcript(audio_path, lo, hi, workdir, cfg):
    """Everything said between stream seconds lo and hi, in chunks of scan_block_minutes so a
    10-hour stream never sits in memory at once. Finished chunks are saved, so an interrupted
    run picks up where it stopped. Returns {"words": [...], "language": ...}."""
    done = workdir / "scan.json"
    if done.exists():
        data = json.loads(done.read_text(encoding="utf-8"))
        log(f"reusing transcript ({len(data['words'])} words)", "ok")
        return data
    size = cfg["scan_block_minutes"] * 60
    edges = list(np.arange(lo, hi, size))
    language, words = cfg["language"], []
    log(f"listening to {(hi - lo) / 60:.0f} min of stream ({len(edges)} part(s))...", "step")
    for n, start in enumerate(edges):
        saved = workdir / f"scan_{n:03d}.json"
        if saved.exists():
            part = json.loads(saved.read_text(encoding="utf-8"))
        else:
            audio = pcm(audio_path, 16000, start=float(start), duration=float(min(size, hi - start)))
            part, heard_lang = words_from(cfg["scan_model"], audio, language, offset=float(start))
            language = language or heard_lang
            saved.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
        words.extend(part)
        log(f"  {(min(start + size, hi) - lo) / 60:.0f}/{(hi - lo) / 60:.0f} min heard", "info")
    if not words:
        raise RuntimeError("no speech found in this stream")
    data = {"words": words, "language": language}
    done.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for f in workdir.glob("scan_*.json"):
        f.unlink()
    return data


def loudness(audio_path, workdir):
    """dBFS of every second of the file (RMS), read through ffmpeg a minute at a time."""
    saved = workdir / "loud.json"
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    rate, levels = 8000, []
    with subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-i", str(audio_path), "-vn",
                           "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], stdout=subprocess.PIPE) as proc:
        while chunk := proc.stdout.read(rate * 2 * 60):
            x = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            secs = len(x) // rate
            if secs:
                rms = np.sqrt(np.mean(x[:secs * rate].reshape(secs, rate) ** 2, axis=1))
                levels.extend(np.round(20 * np.log10(rms + 1e-6), 1).tolist())
    saved.write_text(json.dumps(levels), encoding="utf-8")
    return levels


def relative(values, window=120):
    """Each second's level minus the median level of the ~2 minutes around it."""
    v = np.asarray(values, dtype=np.float32)
    if v.size < 5:
        return np.zeros_like(v)
    half = window // 2
    around = np.lib.stride_tricks.sliding_window_view(np.pad(v, half, mode="edge"), window + 1)[:v.size]
    return v - np.median(around[:, ::4], axis=1)


def chat_rate(url, args, workdir, cfg, stream_info):
    """Chat messages per 5 s of a finished YouTube live stream (its chat replay), or None."""
    if not cfg.get("chat") or "youtube" not in (stream_info.get("extractor_key") or "").lower():
        return None
    if stream_info.get("live_status") not in ("was_live", "post_live"):
        return None
    saved = workdir / "chat.json"
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    log("reading the chat replay...", "step")
    try:
        run(["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat",
             "-o", str(workdir / "chat"), *args, url], timeout=cfg["chat_timeout"])
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        log(f"chat replay not used ({str(exc).splitlines()[0][:80]})", "warn")
    replay = next(iter(workdir.glob("chat*.live_chat.json*")), None)
    if replay is None:
        return None
    per5 = {}
    for line in replay.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)["replayChatItemAction"]
            slot = int(item.get("videoOffsetTimeMsec", 0)) // 5000
        except (ValueError, KeyError, TypeError):
            continue
        per5[slot] = per5.get(slot, 0) + len(item.get("actions", []))
    for f in workdir.glob("chat*.live_chat.json*"):
        f.unlink()
    if not per5:
        return None
    rate = [per5.get(i, 0) for i in range(max(per5) + 1)]
    saved.write_text(json.dumps(rate), encoding="utf-8")
    log(f"chat replay: {sum(rate):,} messages", "ok")
    return rate
