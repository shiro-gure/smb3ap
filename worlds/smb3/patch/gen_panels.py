#!/usr/bin/env python3
"""Build-time generator: parse the SMB3 disassembly's per-world structure tables
into a committed Python panel table (`worlds/smb3/panels.py`).

At the Map_Completions bit level a level clear is indistinguishable from a toad
house / spade clear, and the ROM has no level-number table. Level identity + panel
type are only recoverable from the per-world structure tables in
`disasm/PRG/maps/WorldNS.asm`. We parse them once here and emit a reviewable data
module keyed by (world, byte_offset, bit_mask) -> (kind, name).

Dev tooling — NOT shipped in the .apworld. Regenerate with:
    python3 worlds/smb3/patch/gen_panels.py
See patch/README.md.

Structure-table format (per world N, in maps/WorldNS.asm), 4 parallel arrays,
one entry per enterable panel, concatenated across segments S1..S4 in order:
  Wn_ByRowType  (.byte)  high nibble -> map row (World_Map_Y); low nibble = tileset
  Wn_ByScrCol   (.byte)  the completion byte_offset = (XHi<<4)|(X>>4)
  Wn_ObjSets    (.word)  symbol or $hhhh literal (unused for identity)
  Wn_LevelLayout(.word)  symbol or $hhhh literal -> classifies the panel
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DISASM_MAPS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "disasm", "PRG", "maps"))
OUT = os.path.normpath(os.path.join(HERE, "..", "panels.py"))

# Map_CompleteY / Map_CompleteBit (prg011.asm:4574,4578). World_Map_Y high-nibble
# value -> row index; anything not in the table falls through to index 7 (bit $01).
COMPLETE_Y = [0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80]
COMPLETE_BIT = [0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01]


def row_to_bit(row_type_byte: int) -> int:
    """byte from Wn_ByRowType -> Map_Completions bit mask for that panel's row."""
    ymap = (row_type_byte >> 4) << 4  # high nibble as a $x0 World_Map_Y value
    try:
        idx = COMPLETE_Y.index(ymap)
    except ValueError:
        idx = 7  # $90/$A0/$B0 etc. fall through to the last bit ($01)
    return COMPLETE_BIT[idx]


def _read(world: int) -> str:
    with open(os.path.join(DISASM_MAPS, f"World{world}S.asm")) as f:
        return f.read()


def _array_tokens(text: str, base_label: str, directive: str) -> list[str]:
    """Collect the comma-separated tokens of a base array plus its _S2/_S3/_S4
    continuation segments, in order. Returns raw token strings (symbol or $hhhh)."""
    tokens: list[str] = []
    # Match "<label>:\t.byte v, v, ..." for base and each segment suffix, in order.
    for suffix in ("", "_S2", "_S3", "_S4"):
        label = base_label + suffix
        # label at line start, optional data on the same line after the directive.
        m = re.search(rf"^{re.escape(label)}:\s*{re.escape(directive)}\s+(.+)$",
                      text, re.MULTILINE)
        if not m:
            continue  # empty continuation label (bare "Label:") -> no data
        line = m.group(1)
        for tok in line.split(","):
            tok = tok.split(";")[0].strip()  # strip any trailing comment
            if tok:
                tokens.append(tok)
    return tokens


# --- symbol classification -------------------------------------------------
# Real numbered level:  W<world><NN>L, NN = 01..09  ->  "<world>-<n>"
_LEVEL = re.compile(r"^W(\d)(\d\d)L$")
# Fortress:  W<world>0FL  OR  W<world>F<n>L  (W7/W8 use the F<n> form)
_FORT_0F = re.compile(r"^W(\d)0FL$")
_FORT_FN = re.compile(r"^W(\d)F(\d)L$")


def classify(layout_symbol: str, world: int) -> tuple[str, str] | None:
    """Return (kind, name) for a LevelLayout token, or None to exclude the panel.
    kind in {'level','fortress','toad_house'}."""
    s = layout_symbol
    if s.startswith("$"):
        return None  # raw literal placeholder / non-enterable
    if s == "TOADL":
        return ("toad_house", "")  # named with a per-world sequence later
    m = _LEVEL.match(s)
    if m:
        w, nn = int(m.group(1)), int(m.group(2))
        # Only a real level if the layout's world digit matches the world whose
        # panel table we're parsing. A W707L panel appearing in World 8's table is
        # a pipe-maze transit room reusing that layout, NOT level 7-7 — exclude it.
        # nn is a 2-digit field: 01..0N are numbered levels (some worlds go to
        # 6-10). 0F (fortress) doesn't match \d\d so it never lands here.
        if w == world and nn >= 1:
            return ("level", f"{w}-{nn}")
        return None
    m = _FORT_0F.match(s)
    if m and int(m.group(1)) == world:
        return ("fortress", f"{m.group(1)}-F")
    m = _FORT_FN.match(s)
    if m and int(m.group(1)) == world:
        return ("fortress", f"{m.group(1)}-F{m.group(2)}")
    # King rooms (KNG*), Hammer-Bro (W*HB*), pipe junctions (PJ*), giant-piranha
    # (W7I*), hand traps (W8H*), vehicle levels, letter-suffix oddities -> excluded
    # from level checks. Return None; caller logs unrecognized non-excluded ones.
    return None


# Symbols we deliberately exclude (not level checks) — used only to keep the
# "unrecognized" log honest, so genuinely new/odd symbols still surface.
_EXCLUDE = re.compile(
    r"^(KNG\dL|KINGO|W\d?HB[A-Z]?|PJ[A-Z]+L|W7I\dL|W8H\dL|"
    r"W8(Airship|BS|BC|T\d)L|W2(ST|PY)L|W\d\d[A-Z]L|W1UNL|W5T\dL)$"
)


def main() -> None:
    panels: dict[tuple[int, int, int], tuple[str, str]] = {}
    fortress_panels: list[tuple[int, int, int]] = []
    unrecognized: list[str] = []
    for world in range(1, 9):  # World 9 (Warp Zone) has no level pointers
        text = _read(world)
        rows = _array_tokens(text, f"W{world}_ByRowType", ".byte")
        cols = _array_tokens(text, f"W{world}_ByScrCol", ".byte")
        layouts = _array_tokens(text, f"W{world}_LevelLayout", ".word")
        n = min(len(rows), len(cols), len(layouts))
        if not (len(rows) == len(cols) == len(layouts)):
            print(f"WARN world {world}: array lengths differ "
                  f"(rows={len(rows)} cols={len(cols)} layouts={len(layouts)})",
                  file=sys.stderr)
        toad_seq = 0
        for i in range(n):
            offset = int(cols[i].replace("$", ""), 16)  # $hh byte column
            bit = row_to_bit(int(rows[i].replace("$", ""), 16))
            layout = layouts[i]
            got = classify(layout, world)
            if got is None:
                # A W<other>NNL / W<other>F*L symbol in this world's table is a
                # cross-world reused layout (pipe-maze transit room) — known-excluded,
                # not a mystery. Only log symbols that are neither a literal, an
                # explicit exclusion, nor a cross-world level/fortress reuse.
                cross_world = bool(_LEVEL.match(layout) or _FORT_0F.match(layout)
                                   or _FORT_FN.match(layout))
                if (not layout.startswith("$") and not _EXCLUDE.match(layout)
                        and not cross_world):
                    unrecognized.append(f"W{world} i={i} {layout}")
                continue
            kind, name = got
            key = (world, offset, bit)
            if kind == "fortress":
                # Fortresses keep their existing Phase-0 count-based detection and
                # location ids (FORTRESS_COUNTS in Locations.py). We deliberately do
                # NOT emit them here — the panel table is levels + toad houses only.
                # (Tracked: the parser sees 12 fortress panels vs FORTRESS_COUNTS'
                # 14 — W3/W5 "second" forts are alternate internal rooms, not map
                # panels. See known_bugs.md; not changed in this PR.)
                fortress_panels.append((world, offset, bit))
                continue
            if kind == "toad_house":
                toad_seq += 1
                name = f"World {world} Toad House {toad_seq}"
            if key in panels:
                print(f"WARN world {world}: duplicate key {key} "
                      f"({panels[key]} vs {kind}/{name})", file=sys.stderr)
            panels[key] = (kind, name)

    if unrecognized:
        print("WARN unrecognized LevelLayout symbols (excluded — verify):",
              file=sys.stderr)
        for u in unrecognized:
            print("   ", u, file=sys.stderr)

    _emit(panels, fortress_panels)
    counts = {}
    for kind, _ in panels.values():
        counts[kind] = counts.get(kind, 0) + 1
    fort_by_world = {}
    for w, _o, _b in fortress_panels:
        fort_by_world[w] = fort_by_world.get(w, 0) + 1
    print(f"wrote {OUT}: {len(panels)} panels {counts}")
    print(f"(excluded {len(fortress_panels)} fortress panels — kept on Phase-0 "
          f"count-based path; per-world: {fort_by_world})")


def _emit(panels: dict, fortress_panels: "list[tuple[int, int, int]]") -> None:
    lines = [
        '"""GENERATED by worlds/smb3/patch/gen_panels.py — DO NOT EDIT BY HAND.',
        "",
        "Overworld completable panels, parsed from the disassembly's per-world",
        "structure tables (disasm/PRG/maps/WorldNS.asm). Keyed by the identity the",
        "game produces when it marks a panel complete: (world, byte_offset, bit_mask)",
        "where byte_offset=(World_Map_XHi<<4)|(World_Map_X>>4) and bit_mask is the",
        'Map_CompleteBit for the panel\'s row. Regenerate with gen_panels.py."""',
        "",
        "# (world, byte_offset, bit_mask) -> (kind, name); kind in "
        "{'level','fortress','toad_house'}",
        "PANELS = {",
    ]
    for key in sorted(panels):
        world, offset, bit = key
        kind, name = panels[key]
        lines.append(f"    ({world}, 0x{offset:02X}, 0x{bit:02X}): "
                     f"({kind!r}, {name!r}),")
    lines.append("}")
    lines.append("")
    # Fortress panel positions (world -> ordered [(byte_offset, bit_mask), ...]).
    # Fortresses are NOT in PANELS (they keep their count-based location ids), but the
    # client needs their (offset, bit) to REDRAW cleared-fortress checkmarks after a
    # map repaint wipes Map_Completions — it lights the first N fortress panels of a
    # world where N = that world's checked fortress count. Ordered by (offset, bit) for
    # a stable, deterministic assignment.
    fort_by_world: "dict[int, list[tuple[int, int]]]" = {}
    for w, off, bit in fortress_panels:
        fort_by_world.setdefault(w, []).append((off, bit))
    lines.append("# world -> ordered [(byte_offset, bit_mask), ...] for FORTRESS panels")
    lines.append("# (redraw-only; fortress location ids stay count-based in Locations.py).")
    lines.append("FORTRESS_PANEL_BITS = {")
    for w in sorted(fort_by_world):
        pairs = ", ".join(f"(0x{o:02X}, 0x{b:02X})"
                          for o, b in sorted(fort_by_world[w]))
        lines.append(f"    {w}: [{pairs}],")
    lines.append("}")
    lines.append("")
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
