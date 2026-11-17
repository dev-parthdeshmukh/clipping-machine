"""Settings and paths. Defaults below; override any key in %USERPROFILE%/gta6-clips/config.json."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the plugin / repo folder
FONTS = ROOT / "fonts"
HOME = Path.home() / "gta6-clips"                       # clips, cache, watchlist, user config
ENV_DIR = Path.home() / ".gta6-clipper"                 # private venv, models, voice reference
VOXCPM_PY = (Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
             / "OmniVoice/engines/voxcpm2/voxcpm2/.venv/Scripts/python.exe")
VOXCPM_SNAPSHOT = (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
                   / "OmniVoice/hf_cache/models--openbmb--VoxCPM2/snapshots"
                   / "32279effe8c19989596f05d353d1447f51d9e915")

DEFAULTS = {
    # where streams come from
    "game": "Grand Theft Auto VI",   # category looked up with your Twitch key
    "search": "GTA 6",               # what --find searches YouTube for
    "title_words": ["gta"],          # titles must contain one of these
    "max_age_hours": 36,             # watchlist broadcasts older than this are skipped

    # downloads
    "max_height": 1080,

    # transcription and loudness
    "scan_model": "small",           # quick pass over the whole stream (used for picking)
    "caption_model": "large-v3-turbo",  # accurate pass over each chosen clip (captions)
    "language": None,
    "scan_block_minutes": 20,
    "loud_db": 6.0,
    "chat": True,
    "chat_timeout": 420,

    # choosing moments
    "clips_per_stream": 3,
    "min_duration": 45,
    "max_duration": 150,
    "target_min": 60,                # clips cover the whole topic: 1-2 minutes
    "target_max": 120,
    "score_bar": 70,
    "finalists": 10,
    "chunk_minutes": 12,
    "claude_parallel": 4,
    "claude_model": None,

    # editing
    "dead_gap": 0.5,
    "keep_gap": 0.15,
    "quiet_db": -6.0,                # a gap is dead air only this far below its surroundings
    "zoom_db": 8.0,
    "zoom_scale": 1.0,               # 1.0 = no whole-frame punch-in (house style: the game crop zooms)
    "zoom_in": 0.25,
    "zoom_hold": 1.5,

    # framing
    "layout": "stream",              # house style: streamer on top, game below always
    "output_width": 1080,
    "output_height": 1920,
    "cam_height": 760,               # streamer panel on top; the title sits on this seam
    "focus_zoom": 0.8,
    "focus_follow": False,           # house style: game crop fixed on the centre (True = follow motion)               # game crop height as a share of the frame (0.8 = punched in)
    "fit_aspect": 1.7778,
    "track_smoothing": 5,

    # title (constant, on the seam)
    "title_font_file": str(FONTS / "Montserrat-Black.ttf"),
    "title_size": 64,
    "title_outline": 7,
    "title_y": 0.40,                 # used when there is no facecam seam
    "hook_margin_x": 60,
    "emoji_fonts": [r"C:\Windows\Fonts\seguiemj.ttf", str(FONTS / "NotoColorEmoji.ttf")],

    # captions
    "caption_font": "Montserrat Black",
    "font_size": 82,
    "words_per_group": 3,
    "uppercase": False,
    "text_color": "FFFFFF",
    "highlight_color": "FFE13B",
    "outline_width": 8,
    "shadow": 4,
    "caption_y": 0.5,                # just under the title, top of the game area
    "word_pop": True,

    # narrated intro
    "narrator": "none",              # house style: no narrated intro (--voice voxcpm2|kokoro turns it on)
    "voice_profile": "",              # your VoiceStudio voice profile id (narrator only)
    "narrator_fallback_voice": "am_michael",
    "intro_blur": 30,
    "intro_dark": 0.25,
    "reveal": 0.4,
    "duck_db": 12,

    # encoding
    "encoder": "auto",               # auto = h264_nvenc if it works, else libx264
    "nvenc_args": ["-preset", "p7", "-tune", "hq", "-cq", "19"],
    "crf": 20,
    "preset": "medium",
    "audio_bitrate": "192k",
    "loudnorm": True,
}


def load(overrides=None):
    """Defaults, then HOME/config.json, then non-None overrides."""
    cfg = json.loads(json.dumps(DEFAULTS))      # deep copy: lists stay per-call
    path = HOME / "config.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path} is not valid JSON: {exc}")
    for key, value in (overrides or {}).items():
        if value is not None:
            cfg[key] = value
    return cfg
