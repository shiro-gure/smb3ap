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
\t; Land on a WALKABLE World-9 node. Map_Init forces X=$20 (a framing/wall tile
\t; with no adjacent path -> player stuck), and read a garbage Y past the 8-entry
\t; Map_Y_Starts. Overwrite both: X=$60,Y=$40 is a $BC pipe node flanked by $DA
\t; path on both sides, so left/right movement works immediately. Movement tiles
\t; are $DA/$DB (NOT $D7, which is cosmetic). PRG030_84A0 copies Map_Entered_*
\t; into World_Map_*.
\tLDX Player_Current
\tLDA #$40
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
    print("phase 5b — return-to-hub + world-select panels: (not yet implemented)")
    raise SystemExit("phase 5b is a follow-up; run --phase 5a for now")


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
