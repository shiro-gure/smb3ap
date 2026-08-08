#!/usr/bin/env python3
"""Apply the World-9 HUB ROM hooks to the disassembly, for the base-patch pipeline.

The hub makes a new game start in World 9 (the Warp Zone) as a travel hub. This
script edits the disasm ASM sources in place (the disasm is gitignored and
reassembled into a base patch — see patch/README.md). Idempotent: re-running
reproduces the same edits (each edit checks it isn't already applied).

Two phases:
  5a (start in World 9): change the new-game start-world byte + fix two
     out-of-bounds hazards that World_Num=8 triggers in Map_Init.
  5b (return-to-hub + world-select panels): the INC->JMP redirect, an injected
     routine in bank 30 free space, and the World9 map/structure edits.

Run 5a only (default) or both:
    python3 worlds/smb3/patch/make_hub.py [--phase 5a|5b|all]

NOT shipped in the .apworld.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DISASM = os.path.normpath(os.path.join(HERE, "..", "..", "..", "disasm"))
PRG = os.path.join(DISASM, "PRG")


def _edit(path: str, old: str, new: str, *, already: str) -> None:
    """Replace `old` with `new` in `path`. If `already` is present, treat the edit
    as done (idempotent). Errors if neither `old` nor `already` is found."""
    with open(path) as f:
        text = f.read()
    if already in text:
        print(f"  [skip] {os.path.relpath(path, DISASM)}: already applied")
        return
    if old not in text:
        raise SystemExit(f"ERROR: anchor not found in {path}:\n  {old!r}")
    if text.count(old) != 1:
        raise SystemExit(f"ERROR: anchor not unique in {path}: {old!r}")
    with open(path, "w") as f:
        f.write(text.replace(old, new))
    print(f"  [ok]   {os.path.relpath(path, DISASM)}")


def _replace_file(path: str, content: str, *, marker: str) -> None:
    """Overwrite a whole file (used for the W9 map/structure, which are fully
    rewritten). Idempotent via `marker` (a distinctive substring of the new
    content): if present, the file is already the hub version."""
    if os.path.exists(path):
        with open(path) as f:
            if marker in f.read():
                print(f"  [skip] {os.path.relpath(path, DISASM)}: already applied")
                return
    with open(path, "w") as f:
        f.write(content)
    print(f"  [ok]   {os.path.relpath(path, DISASM)}")


# --- 5a: start a new game in World 9 -------------------------------------------

# The hub-init hook, appended into bank 30's trailing free space ($9FB6, 74 bytes
# of $FF). Non-shifting: it goes where blank ROM already is, and the only in-place
# change is retargeting one JSR. It runs in place of `JSR Map_Init` in PRG030_84A0:
# calls Map_Init as normal, then for World 9 (World_Num=8) fixes the two Map_Init
# out-of-bounds hazards — the garbage start-Y (from the 8-entry Map_Y_Starts) and
# the junk map objects (from the 8-entry Map_List_Object_* tables). Map_Entered_Y
# is copied into World_Map_Y later in PRG030_84A0, so setting it here suffices.
HUB_INIT_HOOK = """
; ============================================================================
; HUB: World-9 start hook (PR 5a). Injected into blank ROM at bank 30's tail.
; Replaces `JSR Map_Init` in PRG030_84A0. See worlds/smb3/patch/make_hub.py.
; ============================================================================
HubInit:
\tJSR Map_Init\t\t; do the normal map init first
\tLDA World_Num
\tCMP #$08\t\t; World 9 (the hub)?
\tBNE HubInit_Done\t; no -> nothing to fix
\t; Land on the World-1 pipe of the hub (5b). Map_Init forces X=$20 (a wall tile)
\t; and reads a garbage Y, so set both explicitly. X=$40,Y=$50 = the W1 pipe (the
\t; in-game-verified coordinate), adjacent to $DA (right). PRG030_84A0 copies
\t; Map_Entered_* into World_Map_*. The entry table (World9S) matches these raw
\t; coordinates exactly.
\tLDX Player_Current
\tLDA #$50
\tSTA Map_Entered_Y,X
\tLDA #$40
\tSTA Map_Entered_X,X
\t; Clear the junk map objects Map_Init loaded from the OOB table pointer.
\tLDY #(MAPOBJ_TOTAL-1)
HubInit_ClrObj:
\tLDA #MAPOBJ_EMPTY
\tSTA Map_Objects_IDs,Y
\tDEY
\tBPL HubInit_ClrObj
HubInit_Done:
\tRTS
"""

# The return-to-hub hook (5b-4), also injected into bank 30's free space. Replaces
# `INC World_Num` (prg030.asm:2742) at the world-completion path: instead of
# advancing to the next world, force World_Num back to 8 (World 9 = the hub), then
# fall into the same map-init the original code jumped to. Routing every completed
# world back to the hub. (Persistence deferred — the map-init clears Map_Completions;
# AP checks are server-side. See known_bugs BUG-003.)
HUB_RETURN_HOOK = """
; ============================================================================
; HUB: return-to-hub hook (PR 5b). Replaces `INC World_Num` in the world-clear
; path; routes every completed world back to World 9. See make_hub.py.
; ============================================================================
HubReturn:
\tLDA #$08\t\t; World 9 (the hub)
\tSTA World_Num
\tJMP PRG030_84A0\t; re-init the world map (same target the original INC path used)
"""

# The World-9 hub map. 16x9, row-major, $FF-terminated (same format as World1L).
# $02 border, $8D framing fill, $DA = TILE_HORZPATHSKY (walk L/R), $DB =
# TILE_VERTPATHSKY (walk U/D), $BC = TILE_PIPE (world-select panel; walkable via the
# valid-list edit, entered with A). Pipe positions are the GROUND-TRUTH World_Map_X/Y
# the player actually holds, read in-game (so the entry table below matches exactly):
#   row4 (Y=$50): W1@col4 W2@col6 W3@col8 W4@col10   (W1 is a custom pipe; was $D9)
#   row6 (Y=$70): W5@col6 W6@col8 W7@col10
#   row8 (Y=$90): W8@col10
# $DA connects same-row pipes; $DB verticals (row5 col6 & col10, row7 col10) link the
# rows so every world is reachable from the W1 landing. Turns land on pipes (the only
# 4-way-walkable tile after $BC is added to the valid lists).
WORLD9L = """
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $BC, $DA, $BC, $DA, $BC, $DA, $BC, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $DB, $8D, $8D, $8D, $DB, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $BC, $DA, $BC, $DA, $BC, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $DB, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $BC, $8D, $8D, $8D, $8D, $02

\t.byte $FF
"""

# The W9 structure tables. ByRowType = (rawY & $F0) | (destWorld-1); the world-9
# bypass (prg012.asm:575) reads the matched ByRowType's low nibble as destWorld-1.
# ByScrCol = (XHi<<4) | (map_X>>4). Values are the in-game-verified coordinates:
#   W1 (X=$40,Y=$50) -> $50 col $04     W5 (X=$60,Y=$70) -> $74 col $06
#   W2 (X=$60,Y=$50) -> $51 col $06     W6 (X=$80,Y=$70) -> $75 col $08
#   W3 (X=$80,Y=$50) -> $52 col $08     W7 (X=$A0,Y=$70) -> $76 col $0A
#   W4 (X=$A0,Y=$50) -> $53 col $0A     W8 (X=$A0,Y=$90) -> $97 col $0A
# Columns are unique WITHIN each row (the row search anchors on Y, then the column
# search disambiguates), so the lookup is unambiguous.
WORLD9S = """W9_InitIndex:\t.byte $00, (W9_ByRowType_S2 - W9_ByRowType), (W9_ByRowType_S3 - W9_ByRowType), (W9_ByRowType_S4 - W9_ByRowType)
W9_ByRowType:\t.byte $50, $51, $52, $53, $74, $75, $76, $97
W9_ByRowType_S2:
W9_ByRowType_S3:
W9_ByRowType_S4:
W9_ByScrCol:\t.byte $04, $06, $08, $0A, $06, $08, $0A, $0A
W9_ByScrCol_S2:
W9_ByScrCol_S3:
W9_ByScrCol_S4:
W9_ObjSets:
W9_ObjSets_S2:
W9_ObjSets_S3:
W9_ObjSets_S4:
W9_LevelLayout:
W9_LevelLayout_S2:
W9_LevelLayout_S3:
W9_LevelLayout_S4:
"""


def phase_5a() -> None:
    print("phase 5a — start new game in World 9:")

    # 1) New-game start world: LDA #$00 (World 1) -> LDA #$08 (World 9).
    #    Anchored on the surrounding comment+STA so we hit the new-game path only
    #    (prg024.asm:2398-2400), not some other LDA #$00.
    _edit(
        os.path.join(PRG, "prg024.asm"),
        "\t; World_Num = 0 (World 1)\n\tLDA #$00\n\tSTA World_Num",
        "\t; HUB: World_Num = 8 (World 9 / Warp Zone hub)\n\tLDA #$08\n\tSTA World_Num",
        already="HUB: World_Num = 8",
    )

    # 2) Redirect the map-init call to our hook (in-place JSR operand change).
    prg030 = os.path.join(PRG, "prg030.asm")
    _edit(
        prg030,
        "\tJSR Map_Init\t ; Initialize map variables (page 11)",
        "\tJSR HubInit\t ; HUB: Map_Init + World-9 start fixups (was: JSR Map_Init)",
        already="JSR HubInit",
    )

    # 3) Append the hook routine into bank 30's trailing free space. The disasm's
    #    last real code precedes a "remaining ROM space was all blank ($FF)" note;
    #    appending here lands the routine in that blank region (non-shifting).
    _edit(
        prg030,
        "; NOTE: The remaining ROM space was all blank ($FF)\n",
        "; NOTE: The remaining ROM space was all blank ($FF)\n" + HUB_INIT_HOOK,
        already="HubInit:",
    )


def phase_5b() -> None:
    """Free travel: make pipes walkable, redesign the W9 map into a connected 2x4
    hub grid, wire each pipe to a world, and return the player to the hub on world
    completion. Requires phase_5a (the start-in-W9 hook) to have run."""
    print("phase 5b — W9 hub map + walkable pipes + return-to-hub:")
    prg010 = os.path.join(PRG, "prg010.asm")
    prg030 = os.path.join(PRG, "prg030.asm")

    # 1) Make TILE_PIPE ($BC) walkable in all four directions so the player can roam
    #    between pipes (they're the grid's 4-way junctions). The list length is
    #    derived from the label distance (Map_Object_Valid_Tiles2Check), so adding a
    #    byte to each list updates the count automatically. Comment at the table:
    #    "Safe to expand this, but make sure you update all four!!"
    for label in ("Map_Object_Valid_Left:", "Map_Object_Valid_Right:",
                  "Map_Object_Valid_Down:", "Map_Object_Valid_Up:"):
        _edit(
            prg010,
            f"{label}",
            f"{label}\t; HUB: + TILE_PIPE (walkable pipes)\n\t.byte TILE_PIPE",
            already=f"{label}\t; HUB: + TILE_PIPE",
        )

    # 2) Replace the World-9 map layout with the hub grid.
    _replace_file(os.path.join(PRG, "maps", "World9L.asm"), WORLD9L,
                  marker="$BC, $DA, $BC, $DA, $BC, $8D, $8D, $8D, $8D, $02")
    # 3) Replace the World-9 structure tables (pipe -> world routing).
    _replace_file(os.path.join(PRG, "maps", "World9S.asm"), WORLD9S,
                  marker=".byte $50, $51, $52, $53, $74, $75, $76, $97")

    # 4) Return-to-hub: INC World_Num (world-clear) -> JMP HubReturn.
    _edit(
        prg030,
        "\tINC World_Num\t ; Go to next world!",
        "\tJMP HubReturn\t ; HUB: return to World 9 instead of advancing (was: INC World_Num)",
        already="JMP HubReturn",
    )
    # 5) Append the HubReturn routine into bank 30's free space (after HubInit).
    _edit(
        prg030,
        "HubInit_Done:\n\tRTS\n",
        "HubInit_Done:\n\tRTS\n" + HUB_RETURN_HOOK,
        already="HubReturn:",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["5a", "5b", "all"], default="5a")
    args = ap.parse_args()
    if args.phase in ("5a", "all"):
        phase_5a()
    if args.phase in ("5b", "all"):
        phase_5b()
    print("done.")


if __name__ == "__main__":
    main()
