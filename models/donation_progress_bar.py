"""Renders the donation goal progress bar as a PNG for Discord.

Pure black canvas (AMOLED-friendly) with the #ad1457 accent used on the
website, so the Discord embed and riko.ado.wtf/donations read as one thing.
"""

import io
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

WIDTH = 1000
HEIGHT = 364

BG = (0, 0, 0)
ACCENT = (0xAD, 0x14, 0x57)
ACCENT_BRIGHT = (0xD8, 0x2A, 0x75)
TRACK = (0x1A, 0x16, 0x18)
TRACK_EDGE = (0x2E, 0x25, 0x2A)
INK = (0xF2, 0xEC, 0xEE)
INK_SOFT = (0x8A, 0x7E, 0x84)

REPO_ROOT = Path(__file__).resolve().parent.parent

# python:3.13-slim ships no fonts, so the Dockerfile installs fonts-dejavu-core.
# The list covers that plus common dev machines; the bitmap fallback keeps the
# command working rather than raising if none resolve.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
]

_warned_about_fonts = False


def _resolve_font(candidates, size: int):
    global _warned_about_fonts
    env_override = os.getenv("DONATION_FONT_PATH")
    paths = ([env_override] if env_override else []) + candidates
    for path in paths:
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    if not _warned_about_fonts:
        logger.warning(
            "No TrueType font found for the donation bar, falling back to the "
            "bitmap default. Install fonts-dejavu-core or set DONATION_FONT_PATH."
        )
        _warned_about_fonts = True
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10.1 has no size argument.
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _rounded_bar(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1 if outline else 0)


def render_progress_bar(
    raised_usd: float,
    goal_usd: float,
    donation_count: int = 0,
    title: str = "DONATION GOAL",
    subtitle: Optional[str] = None,
    avatar_path: Optional[str] = None,
) -> io.BytesIO:
    """Render the bar and return a PNG buffer ready for discord.File."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    f_label = _resolve_font(_MONO_CANDIDATES, 22)
    f_huge = _resolve_font(_FONT_CANDIDATES, 78)
    f_goal = _resolve_font(_FONT_CANDIDATES, 34)
    f_pct = _resolve_font(_FONT_CANDIDATES, 40)
    f_foot = _resolve_font(_MONO_CANDIDATES, 20)

    margin = 60
    bar_left = margin
    bar_right = WIDTH - margin
    bar_top = 226
    bar_height = 34
    bar_bottom = bar_top + bar_height
    radius = bar_height // 2

    percent = (raised_usd / goal_usd * 100.0) if goal_usd > 0 else 0.0
    clamped = max(0.0, min(percent, 100.0))

    # Header
    draw.text((margin, 44), title.upper(), font=f_label, fill=ACCENT)

    # Amount raised, with the goal trailing in muted ink on the same baseline.
    raised_text = f"${raised_usd:,.2f}"
    draw.text((margin, 84), raised_text, font=f_huge, fill=INK)
    raised_w = _text_width(draw, raised_text, f_huge)
    draw.text((margin + raised_w + 18, 126), f"/ ${goal_usd:,.2f}", font=f_goal, fill=INK_SOFT)

    # Percentage, right-aligned above the bar
    pct_text = f"{clamped:.1f}%"
    pct_w = _text_width(draw, pct_text, f_pct)
    draw.text((bar_right - pct_w, 168), pct_text, font=f_pct, fill=ACCENT_BRIGHT)

    # Track
    _rounded_bar(draw, (bar_left, bar_top, bar_right, bar_bottom), radius, TRACK, TRACK_EDGE)

    # Fill. A zero-width rounded rectangle renders as a dot, so only draw once
    # the fill is at least as wide as its own end caps.
    track_w = bar_right - bar_left
    fill_w = int(track_w * (clamped / 100.0))
    if fill_w >= bar_height:
        _rounded_bar(draw, (bar_left, bar_top, bar_left + fill_w, bar_bottom), radius, ACCENT)
        # Highlight along the top edge gives the fill a little dimension.
        draw.rounded_rectangle(
            (bar_left + 3, bar_top + 3, bar_left + fill_w - 3, bar_top + bar_height // 2),
            radius=radius // 2,
            fill=ACCENT_BRIGHT,
        )
    elif fill_w > 0:
        draw.ellipse((bar_left, bar_top, bar_left + bar_height, bar_bottom), fill=ACCENT)

    # Footer
    if subtitle is None:
        supporters = "supporter" if donation_count == 1 else "supporters"
        subtitle = f"{donation_count} {supporters}  ·  ko-fi.com/rayenai"
    draw.text((margin, bar_bottom + 30), subtitle, font=f_foot, fill=INK_SOFT)

    # Optional Riko avatar, bottom-right, scaled to the footer band.
    avatar_path = avatar_path or str(REPO_ROOT / "emojis" / "GreetingRiko.png")
    try:
        if Path(avatar_path).is_file():
            avatar = Image.open(avatar_path).convert("RGBA")
            size = 84
            avatar.thumbnail((size, size), Image.LANCZOS)
            img.paste(
                avatar,
                (WIDTH - margin - avatar.width, HEIGHT - avatar.height - 12),
                avatar,
            )
    except Exception as e:
        logger.debug(f"Could not draw donation bar avatar: {e}")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer
