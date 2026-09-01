# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Validate an uploaded image and normalise it to a square PNG.

Raster formats are handled with Pillow. SVG is rasterised with ``cairosvg``
when the ``python3-cairosvg`` package is installed; without it, SVG uploads
fail with a clear message and raster uploads still work.
"""

from __future__ import annotations

import io

from flask_babel import gettext as _
from PIL import Image, UnidentifiedImageError

try:  # optional: only needed for SVG input
    import cairosvg
except Exception:  # noqa: BLE001 - ImportError, or OSError if cairo libs are absent
    cairosvg = None

ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


class ImageError(ValueError):
    """Raised when an upload is not a usable image."""


def _looks_like_svg(raw: bytes) -> bool:
    head = raw[:2048].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head)


def rasterize_to_png(raw: bytes, size: int) -> bytes:
    """Return *raw* (any accepted image, including SVG) as a square PNG.

    Raises :class:`ImageError` for empty, unrecognised or unsupported input.
    """
    if not raw:
        raise ImageError(_("The uploaded file is empty."))

    if _looks_like_svg(raw):
        if cairosvg is None:
            raise ImageError(
                _(
                    "SVG support needs the python3-cairosvg package. Install it, "
                    "or upload a PNG, JPEG or WEBP."
                )
            )
        try:
            raw = cairosvg.svg2png(bytestring=raw, output_width=size, output_height=size)
        except Exception as exc:  # noqa: BLE001
            raise ImageError(_("Could not render the SVG: %(error)s", error=exc)) from exc

    return _square_png_bytes(raw, size)


def _square_png_bytes(raw: bytes, size: int) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError(_("The file is not a recognised image.")) from exc

    with Image.open(io.BytesIO(raw)) as img:
        if img.format not in ACCEPTED_FORMATS:
            raise ImageError(
                _(
                    "Unsupported image format %(format)r. Use PNG, JPEG, WEBP, GIF or SVG.",
                    format=img.format,
                )
            )
        img = img.convert("RGBA")
        width, height = img.size
        side = max(width, height)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - width) // 2, (side - height) // 2))
        if side != size:
            canvas = canvas.resize((size, size), Image.LANCZOS)
        out = io.BytesIO()
        canvas.save(out, "PNG", optimize=True)
        return out.getvalue()


def save_square_png(raw: bytes, dest_path: str, size: int = 512) -> None:
    """Write *raw* image bytes to *dest_path* as a square PNG of *size* px."""
    with open(dest_path, "wb") as fh:
        fh.write(rasterize_to_png(raw, size))
