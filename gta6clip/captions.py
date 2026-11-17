"""Burned-in captions as an .ass subtitle file: short phrases, the word being spoken turns yellow
and pops slightly. Positioned just under the title, clear of the platform buttons on the right."""

MARGIN_L, MARGIN_R = 70, 140          # right side kept clear of like/comment/share buttons
LINGER = 1.2                          # a phrase stays up through pauses shorter than this


def _colour(hex_rgb):
    """'FFE13B' -> '&H003BE1FF' (ASS stores colours as alpha, blue, green, red)."""
    r, g, b = hex_rgb.lstrip("#")[0:2], hex_rgb.lstrip("#")[2:4], hex_rgb.lstrip("#")[4:6]
    return f"&H00{b}{g}{r}".upper()


def _clock(sec):
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}"


def escape(text):
    """Words can't open ASS override blocks or carry backslash commands."""
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _phrases(words, max_words):
    """Split into on-screen phrases: at most `max_words`, broken after sentence ends, after a
    comma once 3 words are up, and at pauses over 0.55 s."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1]["s"] if i + 1 < len(words) else None
        text = w["w"].rstrip()
        if (len(cur) >= max_words or text[-1:] in ".!?" or (text.endswith(",") and len(cur) >= 3)
                or nxt is None or nxt - w["e"] > 0.55):
            out.append(cur)
            cur = []
    return out


def build(words, dur, path, cfg, y=None):
    """Write the .ass for words already on the clip's timeline [0, dur). `y` (0-1 from the top)
    moves the baseline, e.g. for an intro."""
    W, H = cfg["output_width"], cfg["output_height"]
    base, hot = _colour(cfg["text_color"]), _colour(cfg["highlight_color"])
    margin_v = round(H * (1.0 - (cfg["caption_y"] if y is None else y)))
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Pop,{cfg['caption_font']},{cfg['font_size']},{base},{base},&H00000000,&H96000000,"
        f"0,0,0,0,100,100,0,0,1,{cfg['outline_width']},{cfg['shadow']},2,{MARGIN_L},{MARGIN_R},{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    grow, shrink = (r"\fscx112\fscy112", r"\fscx100\fscy100") if cfg["word_pop"] else ("", "")
    groups = _phrases([w for w in words if w["e"] > 0 and w["s"] < dur], cfg["words_per_group"])
    events = []
    for n, group in enumerate(groups):
        shown = [escape(w["w"].strip()) for w in group]
        shown = [s.upper() for s in shown] if cfg["uppercase"] else shown
        limit = min(groups[n + 1][0]["s"] if n + 1 < len(groups) else dur, dur)
        for i, w in enumerate(group):
            begin = max(w["s"], 0.0)
            if i + 1 < len(group):
                finish = max(group[i + 1]["s"], w["e"])
            else:
                finish = limit if limit - w["e"] <= LINGER else min(w["e"] + 0.3, limit)
            finish = max(finish, begin + 0.08)
            text = " ".join(f"{{\\c{hot}&{grow}}}{s}{{\\c{base}&{shrink}}}" if j == i else s
                            for j, s in enumerate(shown))
            events.append(f"Dialogue: 0,{_clock(begin)},{_clock(finish)},Pop,,0,0,0,,{text}")
    path.write_text("\n".join(head + events) + "\n", encoding="utf-8")
    return path
