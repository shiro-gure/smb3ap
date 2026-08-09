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
\t; Land ON the World-2 pipe. In-game the player holds X=$60, Y=$50 while standing
\t; on that pipe (verified from the heartbeat) — the pipe graphic is drawn a row
\t; higher, but the enterable/standing cell is Y=$50. Map_Init forces X=$20 (a wall)
\t; and reads a garbage Y, so set both. PRG030_84A0 copies Map_Entered_* into
\t; World_Map_*.
\tLDX Player_Current
\tLDA #$50
\tSTA Map_Entered_Y,X
\tLDA #$60
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
# world back to the hub.
#
# NOTE: in-game completion persistence is NOT done in ROM (there is no persistent free
# RAM for a world-segmented store, and the native Map_Completions bitfield is a single
# world-agnostic 128-byte buffer — persisting it across travel bleeds one world's
# checkmarks onto another world's panels). Instead the AP CLIENT re-writes the current
# world's checkmark bits on each map load (Client.py). So the vanilla wipe-on-load is
# left intact here.
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

# PR 5c Part 2 — keep completed LEVEL panels re-enterable while still showing the ✓.
# Vanilla couples "checkmark" and "can't re-enter": Map_Reload_with_Completions repaints
# a cleared panel to a Map_CompleteByML_Tiles value ($00/$40/$80/$C0) that is the LOWEST
# in its quadrant, so it fails the enterability test (prg010.asm:2792, tile >= threshold).
# We decouple them for numbered LEVEL panels only (which are ALWAYS quadrant 0, tile
# $03-$0C): write an ENTERABLE metatile $16 whose four CHR planes we point at the same
# ✓-painted tiles ($88-$8B) as the completion tile. $16 >= $03 (the q0 threshold) so it
# re-enters; the level identity comes from the structure tables (by row/col), not the
# tile graphic, so the correct level reloads.
#
# Toad houses / spades / hand-traps reach the completion flip via the Map_Completable_Tiles
# match (prg012.asm:343) and are LEFT on the vanilla non-enterable path — they "stay used."
# Only the range-check route (prg012.asm:355), i.e. numbered levels, is redirected, and only
# for quadrant 0 (the pool $BF / W5 star $E9 in q2/q3 keep vanilla behavior).
#
# The redirect must be non-shifting. `CMP Tile_Attributes_TS0,X` (DD 00 A4, 3 bytes) +
# `BGE PRG012_A570` (B0 xx, 2 bytes) = 5 bytes, replaced by `JMP LevelCompGate` (4C xx xx,
# 3 bytes) + 2 NOPs. LevelCompGate reproduces the compare, preserves the fort/removable
# fall-through (< threshold), sends quadrant>0 to the vanilla PRG012_A570, and for quadrant
# 0 writes the enterable ✓ tile then rejoins the shared write/continue at PRG031_A581.
LEVEL_COMP_HOOK = """
; ============================================================================
; HUB 5c: enterable-checkmark gate for numbered LEVEL panels (quadrant 0).
; Reached from the hijacked `CMP Tile_Attributes_TS0,X / BGE PRG012_A570` in
; Map_Reload_with_Completions. Keeps cleared levels re-enterable + checkmarked;
; toad houses and pool/star keep vanilla behavior. See worlds/smb3/patch/make_hub.py.
; ============================================================================
LevelCompGate:
\tCMP Tile_Attributes_TS0,X\t; (reproduce the hijacked compare: tile vs quadrant threshold)
\tBCC LevelCompGate_NotLevel\t; tile < threshold -> not completable here (fort/removable path)
\t; tile >= threshold: this is a completable panel. Only quadrant 0 == numbered level.
\tCPX #$00
\tBEQ LevelCompGate_Level\t; quadrant 0 -> numbered level -> enterable checkmark
\tJMP PRG012_A570\t\t; quadrant 1/2/3 (pool/star/etc) -> vanilla non-enterable M/L (far JMP)
LevelCompGate_Level:
\t; Quadrant 0 numbered level: write the enterable checkmark tile ($16) instead of
\t; the (non-enterable) Map_CompleteByML_Tiles value, then rejoin the shared writer.
\tLDA #$16\t\t; TILE_LEVELCLEAR (enterable, CHR-painted to the checkmark)
\tJMP PRG031_A581\t\t; shared: Y = Temp_Var5; STA [Map_Tile_AddrL],Y; continue scan
LevelCompGate_NotLevel:
\tJMP PRG012_A54A\t\t; fall-through target of the original BGE (fort / removable tiles)
"""

# PR 5c Part 2b — let the player WALK THROUGH a cleared level (tile $16) instead of being
# stopped on it. Separate from re-entry: the "you must complete that level!" movement gate
# (prg010.asm:2621-2665) blocks passage over any tile whose value is >= Tile_AttrTable+4
# (the enterable threshold) unless you reverse or wear a Judgem's cloud. Vanilla completion
# tiles ($00/$40/..) are BELOW threshold, so movement flows over them; our enterable $16 is
# ABOVE threshold (that's what makes it re-enterable), so it wrongly triggers the block.
#
# Fix: special-case $16 as "already completed -> free movement" at the top of that gate.
# Hijack `LDA World_Map_Tile / CMP Tile_AttrTable+4,Y` (A5 E5 D9 98 7E, 5 bytes) with
# `JMP MoveGate` (3) + 2 NOP; MoveGate lets $16 (and below-threshold tiles) pass to
# PRG010_CE64 (free move) and rejoins the block path (PRG010_MoveBlock, labeled at the
# original `LDA Pad_Holding`) for real uncleared panels. Non-shifting; MoveGate lives in
# bank-10's blank tail (same bank as the jump targets).
MOVE_GATE_HOOK = """
; ============================================================================
; HUB 5c: walk-through gate for cleared levels (tile $16). Reached from the
; hijacked `LDA World_Map_Tile / CMP Tile_AttrTable+4,Y` in the map-move code.
; $16 (cleared level) and below-threshold tiles -> free movement; real enterable
; uncleared panels -> the original "must complete" block. See make_hub.py.
; ============================================================================
MoveGate:
\tLDA <World_Map_Tile
\tCMP #$16\t\t; cleared-level checkmark tile?
\tBEQ MoveGate_Free\t; yes -> walk through (treat as completed)
\tCMP Tile_AttrTable+4,Y\t; (reproduce the hijacked compare)
\tBCC MoveGate_Free\t; < threshold -> free movement (vanilla behavior)
\tJMP PRG010_MoveBlock\t; >= threshold -> real enterable panel -> block gate (far JMP)
MoveGate_Free:
\tJMP PRG010_CE64\t\t; below threshold or cleared -> free movement
"""

# PR 5c Part 3 — on-demand map repaint so the AP client's re-asserted checkmark bits
# become visible right after arriving on a world map (not only after entering a level
# and returning). The client sets a flag byte (Map_RepaintReq = LevLoad_Unused1 / $0701,
# free again after the Part-1 gate was reverted); the idle map loop checks it once per
# frame and, when set on a settled map, re-runs the game's own map-load tail
# (PRG030_84D7 — the reload+full-redraw AFTER the completions clear loop, so it repaints
# WITHOUT wiping the client's bits). Cost: a brief blank + fade-in, i.e. it looks like
# the world reloading for ~half a second. Reuses proven code (low risk).
#
# Hook: retarget `JSR Map_DoMap` (prg030.asm:946, in the idle WorldMap_Loop, bank 30)
# to `JSR MapRepaintCheck`. The check only fires on Map_Operation == $0D (Normal / idle
# — not during pan/warp/level-clear animations), clears the flag first (so it runs once),
# then JMPs to the reload tail; otherwise it just runs Map_DoMap as before.
MAP_REPAINT_HOOK = """
; ============================================================================
; HUB 5c: on-demand map repaint. Reached from the hijacked `JSR Map_DoMap` in
; the idle WorldMap_Loop. If the client set Map_RepaintReq (LevLoad_Unused1) and
; the map is settled (Map_Operation == $0D), re-run the map-load tail to repaint
; checkmarks (keeps the client's Map_Completions bits — no wipe). See make_hub.py.
; ============================================================================
MapRepaintCheck:
\tLDA LevLoad_Unused1\t; Map_RepaintReq
\tBEQ MapRepaintCheck_Normal\t; not requested -> normal map tick
\tLDA Map_Operation
\tCMP #$0D\t\t; only when the map is settled/normal (not mid-animation)
\tBNE MapRepaintCheck_Normal
\tLDA #$00
\tSTA LevLoad_Unused1\t; consume the request (repaint once)
\tJMP PRG030_84D7\t\t; reload+full-redraw tail (after the clear loop -> no wipe)
MapRepaintCheck_Normal:
\tJMP Map_DoMap\t\t; nothing to do -> the normal map tick (tail-call)
"""

# The World-9 hub map = VANILLA World9L with a MINIMAL edit: three $D7 (decorative
# cloud) tiles turned into $DB (TILE_VERTPATHSKY, walk U/D) to add vertical links
# between the pipe rows. Everything else (sand island, water, pipes, and the vanilla
# $DA horizontal path stubs that already connect each pipe row) is byte-identical to
# vanilla, so the Warp-Zone art is preserved. Pipes become walkable via the valid-
# list edit. The vanilla W9 structure table (World9S) is left UNCHANGED — its entries
# already route to worlds 1-8 (including a World-1 entry at Y=$50,col4 that vanilla
# never gave a pipe). Edits vs vanilla:
#   - 3 $DB vertical links: row4 col6 (W2<->W5), row4 col10 (W4<->W7), row6 col10
#     (W7<->pipe8).
#   - custom World-1 pipe: row3 col4 $D9 -> $BC (left of pipe 2; the $DA at col5
#     already connects it, and the vanilla $50/$04 table entry already routes it to
#     World 1).
WORLD9L = """
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $8D, $02
\t.byte $02, $8D, $8D, $87, $95, $95, $95, $95, $95, $95, $95, $95, $95, $95, $88, $02
\t.byte $02, $88, $8D, $8E, $BC, $DA, $BC, $DA, $BC, $DA, $BC, $D7, $D7, $D7, $8C, $02
\t.byte $02, $90, $8D, $8E, $D7, $D7, $DB, $D7, $D7, $D7, $DB, $D7, $D7, $84, $90, $02
\t.byte $02, $8D, $87, $96, $D9, $DA, $BC, $DA, $BC, $DA, $BC, $D7, $A1, $93, $8D, $02
\t.byte $02, $8D, $8E, $D7, $D7, $D7, $D7, $D7, $D7, $D7, $DB, $D7, $D7, $8C, $8D, $02
\t.byte $02, $8D, $8E, $D7, $D7, $84, $85, $86, $D9, $DA, $BC, $D7, $84, $90, $8D, $02
\t.byte $02, $8D, $8F, $85, $85, $90, $8D, $8F, $85, $85, $85, $85, $90, $8D, $8D, $02

\t.byte $FF
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

    # 2) Vanilla World9L + 3 $DB vertical links (keeps the vanilla art). Marker is a
    #    row that only exists in the edited version (row4 with the two $DB links).
    _replace_file(os.path.join(PRG, "maps", "World9L.asm"), WORLD9L,
                  marker="$D7, $DB, $D7, $D7, $D7, $DB, $D7")
    # 3) World9S (the pipe->world routing table) is left UNCHANGED from vanilla — its
    #    entries already route to worlds 1-8.

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


def phase_5c() -> None:
    """Cleared levels stay re-enterable + walk-through while showing the checkmark.

    (Completion persistence across travel is handled by the AP CLIENT re-writing the
    current world's checkmark bits on each map load — NOT in ROM. The native
    Map_Completions bitfield is a single world-agnostic 128-byte buffer with no free
    persistent RAM to segment it per world, so the vanilla wipe-on-load is left intact.)

    Requires phase_5a + phase_5b (HubInit/HubReturn already injected)."""
    print("phase 5c — re-enterable + walk-through cleared-level checkmarks:")

    # --- Part 2: cleared levels stay re-enterable while showing the checkmark ---------
    prg012 = os.path.join(PRG, "prg012.asm")

    # 1) Point the (unused, enterable) metatile $16 at the checkmark CHR ($88-$8B), so a
    #    cleared level can be drawn as a checkmark yet remain enterable. Metatile $16 is
    #    index 6 of the $10-$1F row in each of the 4 CHR planes (UL/LL/UR/LR). Each plane
    #    row has a distinct prefix, so the anchors are unique.
    for plane_prefix, chr_byte in (
        ("$8C, $8C, $8C, $8C, $8C, $8C", "$88"),  # UL plane (prg012.asm:28)
        ("$BE, $BE, $BE, $BE, $BE, $BE", "$89"),  # LL plane (:46)
        ("$8D, $8D, $8D, $8D, $8D, $8D", "$8A"),  # UR plane (:64)
        ("$A6, $A7, $C8, $C9, $CA, $CB", "$8B"),  # LR plane (:82)
    ):
        _edit(
            prg012,
            f"\t.byte {plane_prefix}, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF ; Tiles $10 - $1F",
            f"\t.byte {plane_prefix}, {chr_byte}, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF ; Tiles $10 - $1F  ; HUB 5c: $16 = level-clear checkmark",
            already=f"{plane_prefix}, {chr_byte}, $FF",
        )

    # 2) Redirect the numbered-level completion repaint to LevelCompGate. Replace the
    #    `CMP Tile_Attributes_TS0,X / BGE PRG012_A570` (5 bytes) with `JMP LevelCompGate`
    #    + 2 NOP (5 bytes, non-shifting). The gate re-does the compare, preserves the
    #    fort/removable fall-through, sends quadrant>0 (pool/star) to vanilla, and writes
    #    the enterable checkmark tile for quadrant-0 numbered levels.
    _edit(
        prg012,
        "\tCMP Tile_Attributes_TS0,X\n\tBGE PRG012_A570\t; If this tile is a completable tile",
        "\tJMP LevelCompGate\t; HUB 5c: enterable-checkmark gate for levels (was: CMP/BGE)\n"
        "\tNOP\n\tNOP\t\t; (pad to preserve the 5-byte length; non-shifting)\n"
        "\t; original: BGE PRG012_A570\t; If this tile is a completable tile",
        already="JMP LevelCompGate",
    )

    # 3) Append LevelCompGate into bank 12's blank tail (576 bytes free; in-bank so the
    #    JMP/branch reach is fine). Appending at the "Rest of ROM bank was empty" note lands
    #    it in the blank region (non-shifting — nothing follows it in the bank).
    _edit(
        prg012,
        "; Rest of ROM bank was empty\n",
        "; Rest of ROM bank was empty\n" + LEVEL_COMP_HOOK,
        already="LevelCompGate:",
    )

    # --- Part 2b: walk THROUGH a cleared level (don't stop movement on it) ------------
    prg010 = os.path.join(PRG, "prg010.asm")

    # 4) Hijack `LDA World_Map_Tile / CMP Tile_AttrTable+4,Y` (5 bytes) at the move gate
    #    -> `JMP MoveGate` + 2 NOP (5 bytes, non-shifting), and LABEL the block-path rejoin
    #    (`LDA Pad_Holding`, the fall-through when a tile is a real enterable panel) as
    #    PRG010_MoveBlock so MoveGate can return to it. The BLT that followed the original
    #    CMP is now handled inside MoveGate (BCS -> block, else free), so drop it here.
    _edit(
        prg010,
        "\tLDA <World_Map_Tile\n\tCMP Tile_AttrTable+4,Y\n"
        "\tBLT PRG010_CE64\t \t; If tile is not in \"enterable\" range, jump to PRG010_CE64\n"
        "\n"
        "\tLDA <Pad_Holding",
        "\tJMP MoveGate\t ; HUB 5c: walk-through gate for cleared levels (was: LDA/CMP)\n"
        "\tNOP\n\tNOP\t\t; (pad to preserve length; the original BLT is handled in MoveGate)\n"
        "\n"
        "PRG010_MoveBlock:\t\t; HUB 5c: MoveGate rejoins here for real uncleared panels\n"
        "\tLDA <Pad_Holding",
        already="JMP MoveGate",
    )

    # 5) Append MoveGate into bank 10's blank tail (576 bytes free; same bank as the jump
    #    targets PRG010_CE64 / PRG010_MoveBlock).
    _edit(
        prg010,
        "; Rest of ROM bank was empty\n",
        "; Rest of ROM bank was empty\n" + MOVE_GATE_HOOK,
        already="MoveGate:",
    )

    # --- Part 3: on-demand map repaint (client-triggered, reuses the map-load tail) ----
    prg030 = os.path.join(PRG, "prg030.asm")

    # 6) Retarget the idle-loop `JSR Map_DoMap` (prg030.asm:946) -> `JSR MapRepaintCheck`
    #    (in-place operand change, non-shifting). Unique anchor.
    _edit(
        prg030,
        "\tJSR Map_DoMap\t \t\t; Do the map!",
        "\tJSR MapRepaintCheck\t; HUB 5c: repaint checkmarks if requested, else Map_DoMap",
        already="JSR MapRepaintCheck",
    )

    # 7) Append MapRepaintCheck into bank 30's blank tail (74 bytes free again after the
    #    Part-1 revert; PRG030_84D7 / Map_DoMap targets are reachable — 84D7 is same-bank,
    #    Map_DoMap is JMP-able). Anchored on the blank-tail note, after any prior hooks.
    _edit(
        prg030,
        "HubReturn:\n\tLDA #$08\t\t; World 9 (the hub)\n\tSTA World_Num\n"
        "\tJMP PRG030_84A0\t; re-init the world map (same target the original INC path used)\n",
        "HubReturn:\n\tLDA #$08\t\t; World 9 (the hub)\n\tSTA World_Num\n"
        "\tJMP PRG030_84A0\t; re-init the world map (same target the original INC path used)\n"
        + MAP_REPAINT_HOOK,
        already="MapRepaintCheck:",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["5a", "5b", "5c", "all"], default="5a")
    args = ap.parse_args()
    if args.phase in ("5a", "all"):
        phase_5a()
    if args.phase in ("5b", "all"):
        phase_5b()
    if args.phase in ("5c", "all"):
        phase_5c()
    print("done.")


if __name__ == "__main__":
    main()
