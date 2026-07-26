#!/usr/bin/env python3
"""Repaint the SMB3 "level completed" overworld panel glyph to a checkmark.

Vanilla SMB3 marks a cleared overworld panel with an "M" (Mario) or "L" (Luigi)
glyph, drawn from CHR tiles $88-$8B (in CHR/chr022.pcx) and $DC-$DF (in
CHR/chr023.pcx). Both the live "panel flip" animation (Map_PanelCompletePats,
PRG/prg011.asm) and the on-map-reload state (Map_CompleteByML_Tiles,
PRG/prg012.asm) reference these exact CHR indices, so repainting the CHR alone
turns every completed panel into a checkmark with zero ASM/table changes.

This edits the CHR PCX files IN THE DISASM (which is gitignored and assembled
into the base patch); it is a build-time step, run once, documented in
patch/README.md. Idempotent: re-running reproduces the same tiles.

Tile layout of the 2x2 (16x16 px) completed panel, per Southbird's disasm order
(UL, LL, UR, LR):
    chr022: $88=UL(t8) $89=LL(t9) $8A=UR(t10) $8B=LR(t11)
    chr023: $DC=UL(t28) $DD=LL(t29) $DE=UR(t30) $DF=LR(t31)

Pixel index legend (NES 2bpp, palette-agnostic): 0=panel border/bg, 2=panel
fill, 3=glyph color. We paint the checkmark in 3 over the 2 fill, preserving the
existing border/frame so the panel still reads as a panel in every world's
palette.
"""
from __future__ import annotations

import os

from pcxtool import COLS, TILE, read_pcx, render, set_tile, tile_pixels, write_pcx

HERE = os.path.dirname(os.path.abspath(__file__))
DISASM_CHR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "disasm", "CHR"))

# The 16x16 panel as {UL,LL,UR,LR} local tile indices in each bank.
CHR022 = os.path.join(DISASM_CHR, "chr022.pcx")
CHR023 = os.path.join(DISASM_CHR, "chr023.pcx")
PANEL_022 = (8, 9, 10, 11)    # $88,$89,$8A,$8B
PANEL_023 = (28, 29, 30, 31)  # $DC,$DD,$DE,$DF

BG, FILL, INK = 0, 2, 3


def build_check_grid() -> list[list[int]]:
    """Return a clean 16x16 index grid for the checkmark, robustly.

    Rather than trust hand-drawn ASCII spacing, draw the check programmatically:
    a border ring of BG, a FILL interior, and a 2px checkmark stroke in INK.
    """
    g = [[FILL] * 16 for _ in range(16)]
    for i in range(16):
        g[0][i] = g[15][i] = BG
        g[i][0] = g[i][15] = BG
    # Checkmark strokes (points on the two legs), 2px thick, inside the frame.
    # Short leg: down-right from (x=4,y=7) to (x=6,y=10).
    # Long leg: up-right from (x=6,y=10) to (x=12,y=3).
    def stroke(x0, y0, x1, y1):
        steps = max(abs(x1 - x0), abs(y1 - y0))
        for s in range(steps + 1):
            x = round(x0 + (x1 - x0) * s / steps)
            y = round(y0 + (y1 - y0) * s / steps)
            for dx in (0, 1):
                xx = x + dx
                if 1 <= xx <= 14 and 1 <= y <= 14:
                    g[y][xx] = INK
    stroke(4, 7, 6, 10)
    stroke(6, 10, 12, 3)
    return g


def split_2x2(grid16: list[list[int]]):
    """Split a 16x16 grid into (UL, LL, UR, LR) 8x8 grids (disasm tile order)."""
    def sub(y0, x0):
        return [[grid16[y0 + y][x0 + x] for x in range(TILE)] for y in range(TILE)]
    ul = sub(0, 0)
    ur = sub(0, 8)
    ll = sub(8, 0)
    lr = sub(8, 8)
    return ul, ll, ur, lr


def apply(path: str, panel: tuple[int, int, int, int], grid16) -> None:
    w, h, px, pal = read_pcx(path)
    ul, ll, ur, lr = split_2x2(grid16)
    for ti, g in zip(panel, (ul, ll, ur, lr)):
        set_tile(px, w, ti, g)
    write_pcx(path, w, h, px, pal)


def main() -> None:
    grid = build_check_grid()
    print("Checkmark 16x16:")
    print(render(grid))
    for path, panel in ((CHR022, PANEL_022), (CHR023, PANEL_023)):
        apply(path, panel, grid)
        print(f"patched {os.path.relpath(path)} tiles {panel}")


if __name__ == "__main__":
    main()
