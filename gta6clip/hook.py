"""The title: white outlined text with one yellow keyword, drawn with Pillow so colour
emoji render (libass can't). Emoji come from the first colour emoji font that works;
an emoji no font can draw is skipped, never drawn as a box."""

import functools

from PIL import Image, ImageDraw, ImageFont

import unicodedata


def _is_emoji(ch):
    """Pictographs, symbols and their joiners/variation selectors are drawn from an emoji font."""
    cp = ord(ch)
    return (unicodedata.category(ch) == "So" and cp >= 0x2190) or cp in (0x200D, 0xFE0F) or 0x1F000 <= cp <= 0x1FAFF


def _runs(word):
    """'wow😭!' -> [(False, 'wow'), (True, '😭'), (False, '!')]."""
    runs = []
    for ch in word:
        kind = _is_emoji(ch)
        if runs and runs[-1][0] == kind:
            runs[-1] = (kind, runs[-1][1] + ch)
        else:
            runs.append((kind, ch))
    return runs


def _colourful(img):
    colours = img.convert("RGB").getcolors(1 << 20) or []
    return len([c for _, c in colours if len(set(c)) > 1]) > 20


@functools.lru_cache(maxsize=512)
def _emoji(ch, size, fonts):
    """One colour emoji as an RGBA tile of `size` px, or None if no font draws it in colour."""
    for path in fonts:
        for strike in (size * 2, 109, 160):          # Segoe scales; Noto/Apple are bitmap strikes
            try:
                font = ImageFont.truetype(path, strike)
            except OSError:
                continue
            tile = Image.new("RGBA", (strike * 2, strike * 2), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((strike // 4, strike // 4), ch, font=font, embedded_color=True)
            box = tile.getbbox()
            if box and _colourful(tile.crop(box)):
                return tile.crop(box).resize((size, size), Image.LANCZOS)
    return None


YELLOW = (255, 225, 59, 255)
WHITE = (255, 255, 255, 255)


def parse(text):
    """[(word, is_keyword)]: the word wrapped in *asterisks* is the yellow keyword; with no
    marker, the longest plain word gets it. Exactly one keyword."""
    words = text.split()
    marked = [w.startswith("*") and w.rstrip("!?.,").endswith("*") and len(w) > 2 for w in words]
    out = [(w.replace("*", ""), m) for w, m in zip(words, marked)]
    if not any(marked):
        plain = [i for i, (w, _) in enumerate(out) if not any(_is_emoji(c) for c in w)]
        if plain:
            best = max(plain, key=lambda i: len(out[i][0]))
            out[best] = (out[best][0], True)
    else:
        first = marked.index(True)
        out = [(w, i == first) for i, (w, _) in enumerate(out)]
    return out


def render(text, cfg, path):
    """The constant title: plain text, no box. White Montserrat Black with a thick black
    outline and soft shadow, one keyword in yellow, colour emoji. Returns (path, w, h)."""
    from PIL import ImageFilter
    size = cfg["title_size"]
    font = ImageFont.truetype(cfg["title_font_file"], size)
    fonts = tuple(cfg["emoji_fonts"])
    stroke = cfg["title_outline"]
    em = int(size * 1.05)
    space = font.getlength(" ")
    max_w = cfg["output_width"] - 2 * cfg["hook_margin_x"] - 2 * stroke
    words = []
    for w, key in parse(text):
        runs = [(k, c if not k else "".join(ch for ch in c if _emoji(ch, em, fonts) is not None)) for k, c in _runs(w)]
        runs = [(k, c) for k, c in runs if c]
        if runs:
            words.append((runs, key))

    def measure(runs):
        return sum(len(c) * em if k else font.getlength(c) for k, c in runs)

    lines, cur = [], []
    for wd in words:
        trial = cur + [wd]
        width = sum(measure(r) for r, _ in trial) + space * (len(trial) - 1)
        if cur and width > max_w:
            lines.append(cur)
            cur = [wd]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lines = lines or [[]]
    line_h = int(size * 1.22)
    pad = stroke + 8
    widths = [sum(measure(r) for r, _ in ln) + space * max(0, len(ln) - 1) for ln in lines]
    box_w, box_h = int(max(widths + [1]) + 2 * pad), int(len(lines) * line_h + 2 * pad)

    def draw_text(layer, colour_for, shadow=False):
        d = ImageDraw.Draw(layer)
        for row, (line, width) in enumerate(zip(lines, widths)):
            x, y = (box_w - width) / 2, pad + row * line_h
            for runs, key in line:
                for is_emoji, chunk in runs:
                    if is_emoji:
                        for ch in chunk:
                            if not shadow:
                                layer.alpha_composite(_emoji(ch, em, fonts), (int(x), int(y + (line_h - em) / 2)))
                            x += em
                    else:
                        d.text((x, y), chunk, font=font, fill=colour_for(key), stroke_width=stroke,
                               stroke_fill=(0, 0, 0, 255))
                        x += font.getlength(chunk)
                x += space

    shadow = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw_text(shadow, lambda k: (0, 0, 0, 255), shadow=True)
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    img.alpha_composite(shadow, (0, 4))
    draw_text(img, lambda k: YELLOW if k else WHITE)
    img.save(path)
    return path, box_w, box_h
