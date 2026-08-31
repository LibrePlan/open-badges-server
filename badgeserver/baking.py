# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""Bake an Open Badges assertion URL into a PNG.

The convention (Open Badges "baking") is a PNG ``iTXt`` chunk whose keyword is
``openbadges`` and whose value is the URL of the hosted assertion JSON.
"""

from __future__ import annotations

from PIL import Image, PngImagePlugin

BAKE_KEYWORD = "openbadges"


def bake_png(source_png_path: str, assertion_url: str, dest_path: str) -> None:
    with Image.open(source_png_path) as img:
        img = img.convert("RGBA")
        meta = PngImagePlugin.PngInfo()
        meta.add_itxt(BAKE_KEYWORD, assertion_url)
        img.save(dest_path, "PNG", pnginfo=meta)


def read_baked_url(png_path: str) -> str | None:
    with Image.open(png_path) as img:
        return img.text.get(BAKE_KEYWORD) if hasattr(img, "text") else None
