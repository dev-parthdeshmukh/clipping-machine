"""Runs INSIDE VoiceStudio's VoxCPM2 venv (not the clipper venv).

    python voxcpm_worker.py jobs.json

jobs.json = {"snapshot", "ref_wav", "ref_text", "items": [{"text", "out"}]}
Prints one JSON line per item: {"out", "ok", "error"}. One model load for the whole batch;
continuation-mode clone (reference audio + its transcript)."""

import json
import sys


def main(path):
    jobs = json.loads(open(path, encoding="utf-8").read())
    import soundfile as sf
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained(jobs["snapshot"], load_denoiser=False)
    rate = getattr(model.tts_model, "sample_rate", 48000)
    for item in jobs["items"]:
        try:
            wav = model.generate(text=item["text"], reference_wav_path=jobs["ref_wav"],
                                 prompt_wav_path=jobs["ref_wav"], prompt_text=jobs["ref_text"],
                                 cfg_value=2.0, inference_timesteps=10)
            sf.write(item["out"], wav, rate)
            print(json.dumps({"out": item["out"], "ok": True}), flush=True)
        except Exception as exc:                       # incl. CUDA out of memory
            print(json.dumps({"out": item["out"], "ok": False, "error": str(exc)[:300]}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
