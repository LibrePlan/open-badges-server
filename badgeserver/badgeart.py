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
SHAPES = ("octagon", "circle", "hexagon", "shield", "crest")

_BG_FALLBACK = (43, 108, 176)
_ACCENT_FALLBACK = (176, 135, 43)

# title band per shape (fractions of the canvas height)
_TITLE_BAND = {
    "octagon": (0.56, 0.86),
    "circle": (0.55, 0.80),
    "hexagon": (0.52, 0.73),
    "shield": (0.47, 0.67),
    "crest": (0.58, 0.80),
}

# top of the logo area, as a fraction of canvas height (default 0.07). The
# "crest" has a tall banner-like top section, so its logo starts lower.
_LOGO_TOP = {"crest": 0.22}

# The "crest" outline traces a US detective / FBI-style shield: rounded flared
# top corners with a shallow dip between them, a very gentle waist, a full
# body, and a shield point. Coordinates are (x, y) as fractions of the span,
# x measured from the centre line; only the right half is listed and it is
# mirrored at render time. Tuned against a reference badge silhouette.
_CREST = {
    "corner": (0.475, 0.045),      # the top corner "ear"
    "top_mid_y": 0.014,            # centre of the top edge (shallow dip)
    "top_ctrl": (0.30, -0.012),    # control point for each half of the top edge
    "side": [                      # (control, end) down the right side
        ((0.492, 0.05), (0.475, 0.13)),
        ((0.455, 0.19), (0.435, 0.29)),
        ((0.44, 0.42), (0.465, 0.57)),
        ((0.472, 0.67), (0.42, 0.77)),
        ((0.35, 0.855), (0.22, 0.905)),
        ((0.115, 0.972), None),    # None -> the bottom point (cx, b)
    ],
}
#: supersampling factor for the curved "crest" outline (anti-aliasing)
_CREST_SS = 4


def _clampf(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _quad(p0, p1, p2, steps: int) -> list[tuple[float, float]]:
    """Sample a quadratic Bezier from *p0* to *p2* (control *p1*), *p2* excluded."""
    out = []
    for i in range(steps):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return out


def _crest(size: int, inset: float) -> list[tuple[float, float]]:
    a, b = inset, size - inset
    s = b - a
    cx = a + s / 2
    p = _CREST

    def loc(fx, fy):
        return (cx + fx * s, a + fy * s)

    hw, corner_y = p["corner"]
    corner_r = loc(hw, corner_y)
    corner_l = loc(-hw, corner_y)
    top_mid = loc(0.0, p["top_mid_y"])
    tcx, tcy = p["top_ctrl"]

    # top edge: left corner -> centre dip -> right corner
    pts = _quad(corner_l, loc(-tcx, tcy), top_mid, 16)
    pts += _quad(top_mid, loc(tcx, tcy), corner_r, 16)

    # right side: corner -> ... -> bottom point
    right = [corner_r]
    for ctrl, end in p["side"]:
        target = (cx, b) if end is None else loc(*end)
        right += _quad(right[-1], loc(*ctrl), target, 16)
        right.append(target)

    left = [(2 * cx - x, y) for x, y in reversed(right)]
    return pts + right + left[1:-1]


def _crest_layers(
    size: int, stroke: int, bg: tuple[int, int, int], accent: tuple[int, int, int]
) -> tuple[Image.Image, Image.Image]:
    """Anti-aliased crest: return ``(body_rgba, mask_L)`` at *size*.

    The outline is a curve, so it is drawn at ``_CREST_SS`` x and downsampled --
    a stroked polygon would butt each tiny segment and look chunky.
    """
    ss = _CREST_SS
    big = size * ss
    outer = _polygon("crest", big, 0)
    body = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    if stroke > 0:
        bd.polygon(outer, fill=accent + (255,))
        bd.polygon(_polygon("crest", big, stroke * ss), fill=bg + (255,))
    else:
        bd.polygon(outer, fill=bg + (255,))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(outer, fill=255)
    return (
        body.resize((size, size), Image.LANCZOS),
        mask.resize((size, size), Image.LANCZOS),
    )


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
    if shape == "crest":
        return _crest(size, inset)
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


#: default border width, in pixels at a 512 px canvas (matches size // 64)
BORDER_WIDTH_DEFAULT = 8


def render_badge(
    logo_png: bytes,
    title: str,
    *,
    shape: str,
    bg: str,
    accent: str,
    size: int,
    logo_scale: float = 1.0,
    border_width: int = BORDER_WIDTH_DEFAULT,
    logo_offset: int = 0,
    title_offset: int = 0,
) -> Image.Image:
    """Return the composed badge as an RGBA image.

    *logo_scale* (1.0 = automatic) enlarges or shrinks the logo. *border_width*
    is in pixels at a 512 px canvas (0 = no border) and scaled to *size*.
    *logo_offset* / *title_offset* nudge the logo and the title vertically, in
    percent of the canvas height (positive = down).
    """
    if shape not in SHAPES:
        shape = "octagon"
    bg_rgb = _hex_to_rgb(bg, _BG_FALLBACK)
    accent_rgb = _hex_to_rgb(accent, _ACCENT_FALLBACK)
    scale = min(max(logo_scale or 1.0, 0.4), 2.0)
    logo_dy = (logo_offset or 0) / 100 * size
    title_dy = (title_offset or 0) / 100 * size
    bw = BORDER_WIDTH_DEFAULT if border_width is None else max(0, border_width)
    stroke = round(bw * size / 512)
    outline = accent_rgb + (255,) if stroke > 0 else None

    if shape == "crest":
        canvas, mask = _crest_layers(size, stroke, bg_rgb, accent_rgb)
        draw = ImageDraw.Draw(canvas)
    else:
        mask = _shape_mask(shape, size)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        if shape == "circle":
            draw.ellipse(
                [stroke, stroke, size - 1 - stroke, size - 1 - stroke],
                fill=bg_rgb + (255,),
                outline=outline,
                width=max(1, stroke),
            )
        else:
            draw.polygon(
                _polygon(shape, size, stroke),
                fill=bg_rgb + (255,),
                outline=outline,
                width=max(1, stroke),
            )

    has_title = bool((title or "").strip())
    band0, band1 = _TITLE_BAND.get(shape, (0.56, 0.86))
    title_top = _clampf(band0 * size + title_dy, size * 0.10, size * 0.80)
    title_bottom = _clampf(band1 * size + title_dy, title_top + size * 0.08, size * 0.98)

    with Image.open(io.BytesIO(logo_png)) as logo:
        logo = logo.convert("RGBA")
        # The logo occupies the area between the top of the shape and the title.
        top = size * _LOGO_TOP.get(shape, 0.07)
        bottom = (title_top - size * 0.02) if has_title else size * 0.93
        avail_mid = (top + bottom) / 2
        # Beyond 100 %, the logo is allowed to grow past its nominal area (and
        # over the title) -- the title-position slider and the live preview let
        # the operator sort out the overlap.
        headroom = (bottom - top) * (1.0 if scale <= 1.05 else 1.7)
        box_w = min(_row_span(mask, round(avail_mid)) * 0.90, size * 0.44 * scale)
        box_h = min(headroom, size * 0.44 * scale)
        logo = _contain(logo, max(1, round(box_w)), max(1, round(box_h)))
        ly = round(avail_mid - logo.height / 2 + logo_dy)
        ly = int(_clampf(ly, size * 0.02, size * 0.98 - logo.height))
        canvas.alpha_composite(logo, ((size - logo.width) // 2, ly))

    if has_title:
        luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
        text_colour = (0, 0, 0) if luminance > 150 else (255, 255, 255)
        spans = [_row_span(mask, y) for y in range(int(title_top), int(title_bottom), 8)]
        band_w = min(spans) if spans else 0
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
    border_width: int = BORDER_WIDTH_DEFAULT,
    logo_offset: int = 0,
    title_offset: int = 0,
) -> None:
    render_badge(
        logo_png, title, shape=shape, bg=bg, accent=accent, size=size,
        logo_scale=logo_scale, border_width=border_width,
        logo_offset=logo_offset, title_offset=title_offset,
    ).save(dest_path, "PNG", optimize=True)
