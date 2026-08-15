#!/usr/bin/env python3
"""Minimal PCX (8-bit, RLE) reader/writer + NES CHR tile helpers.

Used to inspect and edit the SMB3 disassembly's CHR/*.pcx tilesets without
Pillow. nesasm's `.incchr` converts each 128x32 8-bit PCX into one 1 KB NES
CHR bank (64 tiles, 16 wide x 4 tall, 8x8 px each), using ONLY the pixel index
value (0-3) as the NES 2bpp pixel — the PCX palette RGB is ignored by nesasm.

Not shipped with the apworld; a dev tool that lives beside the ASM patch
sources. See patch/README.md.
"""
from __future__ import annotations

import struct
import sys


def read_pcx(path: str) -> tuple[int, int, list[int], bytes]:
    """Return (width, height, pixels[row-major index bytes], palette_768)."""
    with open(path, "rb") as f:
        data = f.read()
    manufacturer, version, encoding, bpp = data[0], data[1], data[2], data[3]
    assert manufacturer == 0x0A, "not a PCX"
    assert encoding == 1, "only RLE PCX supported"
    xmin, ymin, xmax, ymax = struct.unpack_from("<HHHH", data, 4)
    width = xmax - xmin + 1
    height = ymax - ymin + 1
    nplanes = data[65]
    bytes_per_line = struct.unpack_from("<H", data, 66)[0]
    assert bpp == 8 and nplanes == 1, f"expected 8bpp/1plane, got {bpp}/{nplanes}"

    # Decode RLE body (starts at offset 128, palette is last 769 bytes if present).
    body = data[128:]
    pal = b""
    if len(body) >= 769 and body[-769] == 0x0C:
        pal = body[-768:]
        body = body[:-769]

    total = bytes_per_line * height
    out = bytearray()
    i = 0
    while len(out) < total and i < len(body):
        b = body[i]; i += 1
        if (b & 0xC0) == 0xC0:
            count = b & 0x3F
            val = body[i]; i += 1
            out.extend([val] * count)
        else:
            out.append(b)
    # Trim each scanline's padding to the real width.
    pixels: list[int] = []
    for row in range(height):
        line = out[row * bytes_per_line: row * bytes_per_line + width]
        pixels.extend(line)
    return width, height, pixels, pal


def encode_rle(scanline: bytes) -> bytes:
    """PCX RLE-encode a single scanline (runs up to 63)."""
    out = bytearray()
    n = len(scanline)
    j = 0
    while j < n:
        val = scanline[j]
        run = 1
        while j + run < n and scanline[j + run] == val and run < 63:
            run += 1
        if run > 1 or (val & 0xC0) == 0xC0:
            out.append(0xC0 | run)
            out.append(val)
        else:
            out.append(val)
        j += run
    return bytes(out)


def write_pcx(path: str, width: int, height: int, pixels: list[int], pal: bytes) -> None:
    """Write an 8-bit RLE PCX matching the layout nesasm/read_pcx expect."""
    bytes_per_line = width if width % 2 == 0 else width + 1
    hdr = bytearray(128)
    hdr[0] = 0x0A          # manufacturer
    hdr[1] = 5             # version 3.0
    hdr[2] = 1             # RLE
    hdr[3] = 8             # bpp
    struct.pack_into("<HHHH", hdr, 4, 0, 0, width - 1, height - 1)
    struct.pack_into("<HH", hdr, 12, 320, 200)  # DPI (cosmetic)
    hdr[65] = 1            # nplanes
    struct.pack_into("<H", hdr, 66, bytes_per_line)
    struct.pack_into("<H", hdr, 68, 1)          # palette info: color
    body = bytearray()
    for row in range(height):
        line = bytearray(pixels[row * width:(row + 1) * width])
        while len(line) < bytes_per_line:
            line.append(0)
        body += encode_rle(bytes(line))
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(body)
        if pal:
            f.write(b"\x0c")
            f.write(pal[:768].ljust(768, b"\x00"))


# --- tile helpers (128x32 = 16x4 tiles of 8x8) ---
TILE = 8
COLS = 16


def tile_pixels(pixels: list[int], width: int, tile_index: int) -> list[list[int]]:
    """Return an 8x8 grid of index values for the given tile (0..63)."""
    trow, tcol = divmod(tile_index, COLS)
    x0, y0 = tcol * TILE, trow * TILE
    return [[pixels[(y0 + y) * width + (x0 + x)] for x in range(TILE)]
            for y in range(TILE)]


def set_tile(pixels: list[int], width: int, tile_index: int, grid: list[list[int]]) -> None:
    trow, tcol = divmod(tile_index, COLS)
    x0, y0 = tcol * TILE, trow * TILE
    for y in range(TILE):
        for x in range(TILE):
            pixels[(y0 + y) * width + (x0 + x)] = grid[y][x]


def render(grid: list[list[int]]) -> str:
    glyph = {0: ".", 1: "1", 2: "2", 3: "#"}
    return "\n".join("".join(glyph.get(v, str(v)) for v in row) for row in grid)


if __name__ == "__main__":
    # Usage: pcxtool.py <file.pcx> <tile_index> [tile_index ...]
    path = sys.argv[1]
    w, h, px, pal = read_pcx(path)
    print(f"{path}: {w}x{h}, {len(px)} px, palette {'present' if pal else 'none'}")
    for arg in sys.argv[2:]:
        ti = int(arg, 0)
        print(f"\n--- tile {ti} (0x{ti:02X}) ---")
        print(render(tile_pixels(px, w, ti)))
