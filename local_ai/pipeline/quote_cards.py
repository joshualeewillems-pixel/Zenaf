"""In-house quote-card renderer (spec §5).

The one thing Zenaf renders itself: the story's key line on a clean card,
tasteCompass-aware styling when available, optional share badge (QR to
`zenaf.ai/a/<id>`) burned in. PIL only — no AI, no API, milliseconds.

Quote cards skip the import step: they are registered directly as
`quote_card` artifacts parented to the story at generation time.
"""

from __future__ import annotations

import hashlib
import io
import textwrap
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CARD_SIZE = (1080, 1080)
BADGE_SIZE = 180
MARGIN = 90

#: Stock palettes (bg, ink, accent). Taste-aware pick hashes the user's
#: style anchors onto one of these; no anchors -> the first (stock).
PALETTES = [
    ((250, 246, 238), (35, 32, 28), (200, 120, 60)),    # warm paper
    ((24, 26, 32), (235, 230, 220), (201, 168, 106)),   # midnight gold
    ((240, 238, 245), (40, 38, 50), (122, 120, 160)),   # lavender dusk
    ((238, 245, 240), (30, 45, 38), (110, 150, 120)),   # sage
]

SHARE_URL_TEMPLATE = "https://zenaf.ai/a/{artifact_id}"


def _pick_palette(style_anchors: str) -> tuple[tuple[int, int, int], ...]:
    if not (style_anchors or "").strip():
        return PALETTES[0]
    digest = hashlib.sha256(style_anchors.encode()).digest()
    return PALETTES[digest[0] % len(PALETTES)]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_regular(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_quote_card(
    key_line: str,
    *,
    title: str = "",
    style_anchors: str = "",
    badge_url: str | None = None,
) -> bytes:
    """Render a quote card PNG. `badge_url` adds a QR share badge
    (bottom-right); pass None to skip it."""
    bg, ink, accent = _pick_palette(style_anchors)
    img = Image.new("RGB", CARD_SIZE, bg)
    draw = ImageDraw.Draw(img)

    # Accent rule at top.
    draw.rectangle([MARGIN, MARGIN, MARGIN + 120, MARGIN + 8], fill=accent)

    quote_font = _font(56)
    max_w = CARD_SIZE[0] - 2 * MARGIN
    lines = _wrap(draw, f"\u201c{key_line.strip()}\u201d", quote_font, max_w)
    line_h = 78
    total_h = len(lines) * line_h
    y = (CARD_SIZE[1] - total_h) // 2 - 40
    for line in lines:
        draw.text((MARGIN, y), line, font=quote_font, fill=ink)
        y += line_h

    if title:
        attr_font = _font_regular(34)
        draw.text(
            (MARGIN, y + 40), f"— {title}", font=attr_font, fill=accent
        )

    # Wordmark.
    mark_font = _font_regular(28)
    draw.text(
        (MARGIN, CARD_SIZE[1] - MARGIN - 30), "zenaf",
        font=mark_font, fill=accent,
    )

    if badge_url:
        import qrcode

        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(badge_url)
        qr.make(fit=True)
        badge = qr.make_image(fill_color=ink, back_color=bg).convert("RGB")
        badge = badge.resize((BADGE_SIZE, BADGE_SIZE))
        img.paste(badge, (CARD_SIZE[0] - MARGIN - BADGE_SIZE,
                          CARD_SIZE[1] - MARGIN - BADGE_SIZE))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
