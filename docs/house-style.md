# House style

Reference: https://www.youtube.com/shorts/OXbXJ_TMIxU (studied frame by frame at 1, 6, 12, 18, 23 s).
Every clip follows this. Consistency beats variety: same layout, fonts, colours, positions every time.

## Layout (1080x1920)
- **Top ~40 % (0-760 px): the streamer.** Facecam cropped tight and scaled to full width, face
  in the upper-middle. Fixed for the whole clip; no panning.
- **Seam (~760 px): the title.** One line, constant from the first to the last frame.
- **Bottom ~60 % (760-1920 px): the game, fixed on the centre of the stream** (most of the action happens in the middle of the screen). Punched in (80 % of frame height), no movement. The old action-following camera is still available with `focus_follow: true` in config.json. Original note:
  the crop is zoomed in on the region of the screen that matches what the streamer is
  reacting to (the map area, the car, the character, the UI element), and it re-frames
  between moments (e.g. Egypt+China silhouettes -> zoomed China -> zoomed map region).
  Moves are smooth (ease, ~0.4 s), then hold still; never a constant drift.

## Title (constant, at the seam)
- Plain text, **no box**. Bold rounded sans (Montserrat ExtraBold-style), white fill,
  thick black outline + soft dark shadow, centred, ~64 px.
- Title Case, 2-5 words, exactly **one keyword in yellow** (#FFE13B), one emoji at the end.
  e.g. "Easiest **Size** Comparison 😭".

## Captions (inside the bottom half, near its top)
- Same font family, white with black outline/shadow; the spoken word highlighted yellow.
- **1-3 words at a time**, natural case (not ALL CAPS): "bigger than China", "y'all saying bruh".
- Positioned ~120 px below the title (upper part of the game area), centred.

## Pacing
- ~20-30 s, starts on the hook, no dead air. Occasional meme/reaction cutaway (optional).

## Open question for the user
- Keep the narrated blurred-teaser intro (our addition, not in the reference) or drop it?
