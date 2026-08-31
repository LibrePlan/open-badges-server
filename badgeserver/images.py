# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Validate an uploaded image and normalise it to a square PNG.

SVG is intentionally unsupported: the baking step (``baking.py``) needs a
raster PNG, and keeping a single format avoids a rasteriser dependency.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


class ImageError(ValueError):
    """Raised when an upload is not a usable raster image."""


def save_square_png(raw: bytes, dest_path: str, size: int = 512) -> None:
    """Write *raw* image bytes to *dest_path* as a transparent square PNG."""
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError("The file is not a recognised image.") from exc

    with Image.open(io.BytesIO(raw)) as img:
        if img.format not in ACCEPTED_FORMATS:
            raise ImageError(
                f"Unsupported image format {img.format!r}. Use PNG, JPEG, WEBP or GIF."
            )
        img = img.convert("RGBA")
        width, height = img.size
        side = max(width, height)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - width) // 2, (side - height) // 2))
        if side != size:
            canvas = canvas.resize((size, size), Image.LANCZOS)
        canvas.save(dest_path, "PNG", optimize=True)
