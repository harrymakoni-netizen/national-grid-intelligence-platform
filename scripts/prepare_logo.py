"""Turns the supplied logo PNG into web assets for the interface.

The source art has an opaque white background and a wordmark beneath the
emblem. The sidebar is dark navy, so the white has to go -- but only the
background white, not the white linework inside the emblem (the
transmission tower). So transparency is flood-filled inward from the
border and stops at the emblem's outline, rather than keying out every
white pixel in the image.

Outputs (written into frontend/):
  logo-mark.png   emblem only, transparent, for the sidebar
  logo-full.png   emblem + wordmark, transparent, for a light background
  favicon.png     small square mark for the browser tab

Run: python scripts/prepare_logo.py <source.png>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend"

WHITE_THRESHOLD = 238  # a pixel this bright in all channels counts as background


def transparent_background(im: Image.Image) -> Image.Image:
    """Alpha-out only white regions connected to the image border."""
    rgb = im.convert("RGB")
    arr = np.array(rgb)
    nearly_white = np.all(arr >= WHITE_THRESHOLD, axis=-1)

    # Label connected white regions; keep only those touching the border.
    labels, n = ndimage.label(nearly_white)
    if n:
        border_labels = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
        border_labels.discard(0)
        background = np.isin(labels, list(border_labels))
    else:
        background = np.zeros_like(nearly_white)

    alpha = np.where(background, 0, 255).astype(np.uint8)
    # Soften the cut by one pixel so the edge doesn't alias against navy.
    alpha = ndimage.minimum_filter(alpha, size=2)

    out = np.dstack([arr, alpha])
    return Image.fromarray(out, mode="RGBA")


def crop_to_content(im: Image.Image, pad: int = 8) -> Image.Image:
    bbox = im.getbbox()  # uses alpha
    if not bbox:
        return im
    left, upper, right, lower = bbox
    left, upper = max(left - pad, 0), max(upper - pad, 0)
    right, lower = min(right + pad, im.width), min(lower + pad, im.height)
    return im.crop((left, upper, right, lower))


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "logo-source.png"
    if not source.exists():
        raise SystemExit(f"source logo not found: {source}")

    im = Image.open(source)
    rgba = transparent_background(im)

    full = crop_to_content(rgba)
    full.thumbnail((900, 900), Image.LANCZOS)
    full.save(OUT / "logo-full.png")

    # The emblem sits above the wordmark. Find the horizontal gap of fully
    # transparent rows that separates them, rather than hard-coding a split.
    arr = np.array(rgba)
    row_has_content = (arr[:, :, 3] > 12).any(axis=1)
    rows = np.flatnonzero(row_has_content)
    top, bottom = rows[0], rows[-1]

    gaps = []
    run_start = None
    for y in range(top, bottom + 1):
        if not row_has_content[y]:
            run_start = y if run_start is None else run_start
        elif run_start is not None:
            gaps.append((run_start, y - 1))
            run_start = None
    # Largest gap in the upper two-thirds is the emblem/wordmark divider.
    candidate = [g for g in gaps if g[0] < top + 0.75 * (bottom - top)]
    split = max(candidate, key=lambda g: g[1] - g[0])[0] if candidate else bottom

    mark = crop_to_content(rgba.crop((0, 0, rgba.width, split)))
    mark.thumbnail((512, 512), Image.LANCZOS)
    mark.save(OUT / "logo-mark.png")

    favicon = mark.copy()
    side = max(favicon.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(favicon, ((side - favicon.width) // 2, (side - favicon.height) // 2))
    square.thumbnail((128, 128), Image.LANCZOS)
    square.save(OUT / "favicon.png")

    for name in ("logo-mark.png", "logo-full.png", "favicon.png"):
        p = OUT / name
        print(f"  {name}: {Image.open(p).size}  {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
