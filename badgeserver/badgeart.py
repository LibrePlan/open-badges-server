# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Compose a badge image from a logo and a title.

Draws a shape (octagon / circle / hexagon / shield) filled with a background
colour and a ring, places the logo in the upper area, and word-wraps the title
beneath it. Output is a square RGBA PNG that feeds the baking pipeline as-is.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SHAPES = ("octagon", "circle", "hexagon", "shield")

_BG_FALLBACK = (43, 108, 176)
_ACCENT_FALLBACK = (176, 135, 43)

# vertical layout per shape: logo centre, and the title band (fractions of size)
_LOGO_CY = {"octagon": 0.34, "circle": 0.37, "hexagon": 0.32, "shield": 0.30}
_TITLE_BAND = {
    "octagon": (0.56, 0.86),
    "circle": (0.55, 0.80),
    "hexagon": (0.52, 0.73),
    "shield": (0.47, 0.67),
}


def _hex_to_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    v = (value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return fallback
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return fallback


def _polygon(shape: str, size: int, inset: float) -> list[tuple[float, float]]:
    a, b = inset, size - inset
    span = b - a
    mid = size / 2
    if shape == "hexagon":
        return [
            (a + span * 0.25, a), (a + span * 0.75, a), (b, mid),
            (a + span * 0.75, b), (a + span * 0.25, b), (a, mid),
        ]
    if shape == "shield":
        shoulder = a + span * 0.58
        return [(a, a), (b, a), (b, shoulder), (mid, b), (a, shoulder)]
    # octagon (default)
    cut = span * 0.293
    return [
        (a + cut, a), (b - cut, a), (b, a + cut), (b, b - cut),
        (b - cut, b), (a + cut, b), (a, b - cut), (a, a + cut),
    ]


def _shape_mask(shape: str, size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    if shape == "circle":
        md.ellipse([0, 0, size - 1, size - 1], fill=255)
    else:
        md.polygon(_polygon(shape, size, 0), fill=255)
    return mask


def _row_span(mask: Image.Image, y: int) -> int:
    """Width of the shape (filled pixels) on row *y*."""
    y = max(0, min(mask.height - 1, y))
    row = list(mask.crop((0, y, mask.width, y + 1)).getdata())
    xs = [i for i, v in enumerate(row) if v]
    return xs[-1] - xs[0] + 1 if xs else 0


def _contain(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Scale *image* (up or down) to fit the box, keeping aspect ratio."""
    scale = min(box_w / image.width, box_h / image.height)
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )


def _load_font(px: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_PATH, px)
    except OSError:
        try:
            return ImageFont.load_default(px)
        except TypeError:  # very old Pillow
            return ImageFont.load_default()


def _wrap(text: str, font, max_w: float, draw: ImageDraw.ImageDraw) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or draw.textlength(trial, font=font) <= max_w:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_title(
    img: Image.Image,
    title: str,
    size: int,
    colour: tuple[int, int, int],
    *,
    max_w: float,
    band_top: float,
    band_bottom: float,
) -> None:
    title = (title or "").strip()
    if not title:
        return
    draw = ImageDraw.Draw(img)
    band_h = band_bottom - band_top

    chosen = None
    for px in range(size // 7, size // 26, -2):
        font = _load_font(px)
        lines = _wrap(title, font, max_w, draw)
        if len(lines) > 3:
            continue
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)
        if widest <= max_w and line_h * len(lines) <= band_h:
            chosen = (font, lines, line_h)
            break

    if chosen is None:
        font = _load_font(max(9, size // 26))
        lines = _wrap(title, font, max_w, draw)[:3]
        ascent, descent = font.getmetrics()
        chosen = (font, lines, ascent + descent)

    font, lines, line_h = chosen
    y = band_top + (band_h - line_h * len(lines)) / 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((size - w) / 2, y), line, font=font, fill=colour)
        y += line_h


def render_badge(
    logo_png: bytes,
    title: str,
    *,
    shape: str,
    bg: str,
    accent: str,
    size: int,
    logo_scale: float = 1.0,
) -> Image.Image:
    """Return the composed badge as an RGBA image.

    *logo_scale* (1.0 = automatic) enlarges or shrinks the logo, clamped so it
    cannot overflow the shape or reach into the title band.
    """
    if shape not in SHAPES:
        shape = "octagon"
    bg_rgb = _hex_to_rgb(bg, _BG_FALLBACK)
    accent_rgb = _hex_to_rgb(accent, _ACCENT_FALLBACK)
    scale = min(max(logo_scale or 1.0, 0.4), 1.7)
    stroke = max(3, size // 64)

    mask = _shape_mask(shape, size)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if shape == "circle":
        draw.ellipse(
            [stroke, stroke, size - stroke, size - stroke],
            fill=bg_rgb + (255,),
            outline=accent_rgb + (255,),
            width=stroke,
        )
    else:
        draw.polygon(
            _polygon(shape, size, stroke),
            fill=bg_rgb + (255,),
            outline=accent_rgb + (255,),
            width=stroke,
        )

    has_title = bool((title or "").strip())
    # Vertical split: logo up top, title (if any) in a lower band.
    logo_centre_y = round(size * (_LOGO_CY.get(shape, 0.34) if has_title else 0.5))
    title_top, title_bottom = (b * size for b in _TITLE_BAND.get(shape, (0.56, 0.86)))

    with Image.open(io.BytesIO(logo_png)) as logo:
        logo = logo.convert("RGBA")
        box_w = max(1, round(_row_span(mask, logo_centre_y) * 0.62 * scale))
        box_h = round(size * (0.34 if has_title else 0.6) * scale)
        if has_title:  # keep the logo clear of the title
            box_h = min(box_h, max(1, round(2 * (title_top - size * 0.02 - logo_centre_y))))
        logo = _contain(logo, box_w, box_h)
        canvas.alpha_composite(
            logo, ((size - logo.width) // 2, logo_centre_y - logo.height // 2)
        )

    if has_title:
        luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
        text_colour = (0, 0, 0) if luminance > 150 else (255, 255, 255)
        band_w = min(
            _row_span(mask, y) for y in range(int(title_top), int(title_bottom), 8)
        )
        _draw_title(
            canvas,
            title,
            size,
            text_colour,
            max_w=band_w * 0.86,
            band_top=title_top,
            band_bottom=title_bottom,
        )

    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(canvas, (0, 0), mask)
    return clipped


def compose_badge(
    logo_png: bytes,
    title: str,
    *,
    shape: str,
    bg: str,
    accent: str,
    size: int,
    dest_path: str,
    logo_scale: float = 1.0,
) -> None:
    render_badge(
        logo_png, title, shape=shape, bg=bg, accent=accent, size=size,
        logo_scale=logo_scale,
    ).save(dest_path, "PNG", optimize=True)
