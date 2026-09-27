"""Generate ``packaging/icon.ico`` with the standard library only.

The artwork is drawn procedurally so the repository stays free of opaque
binary blobs: a rounded indigo tile with ascending signal bars in cyan.

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)
BG = (11, 15, 25, 255)
TILE = (99, 102, 241, 255)
CYAN = (6, 182, 212, 255)
ACCENT = (139, 92, 246, 255)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "packaging" / "icon.ico"

BAR_FRACTIONS = (0.30, 0.48, 0.66, 0.84)
BAR_COLORS = (ACCENT, CYAN, CYAN, CYAN)


def _rounded_alpha(x: int, y: int, size: int, radius: int) -> bool:
    """Coverage test for a rounded square filling the canvas."""
    left, top = 0, 0
    right, bottom = size - 1, size - 1
    for cx, cy in (
        (left + radius, top + radius),
        (right - radius, top + radius),
        (left + radius, bottom - radius),
        (right - radius, bottom - radius),
    ):
        outside_x = x < left + radius or x > right - radius
        outside_y = y < top + radius or y > bottom - radius
        if not (outside_x and outside_y):
            continue
        if abs(x - cx) <= radius and abs(y - cy) <= radius and (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
            return True
    return bool(left <= x <= right and top <= y <= bottom)


def render_rgba(size: int) -> bytes:
    radius = max(3, size // 6)
    margin = max(2, size // 8)
    inner = size - 2 * margin
    bar_width = max(1, inner // 7)

    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            if not _rounded_alpha(x, y, size, radius):
                rows.extend((0, 0, 0, 0))
                continue
            color = BG
            if margin <= x < size - margin and margin <= y < size - margin:
                color = TILE
            span = inner / (len(BAR_FRACTIONS) * 2)
            for index, fraction in enumerate(BAR_FRACTIONS):
                start = margin + span * index * 2
                bar_top = margin + inner * (1 - fraction)
                if start <= x < start + bar_width and bar_top <= y < size - margin - inner * 0.12:
                    color = BAR_COLORS[index]
                    break
            rows.extend(color)
    return bytes(rows)


def encode_png(size: int) -> bytes:
    raw = render_rgba(size)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def build_ico() -> bytes:
    images = [encode_png(size) for size in SIZES]
    count = len(images)
    offset = 6 + 16 * count
    directory = bytearray()
    payload = bytearray()
    for size, data in zip(SIZES, images, strict=True):
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)
    return struct.pack("<HHH", 0, 1, count) + bytes(directory) + bytes(payload)


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(build_ico())
    print(f"Wrote {TARGET} ({TARGET.stat().st_size} bytes, {len(SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
