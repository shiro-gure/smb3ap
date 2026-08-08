# SMB3 base-patch sources

This directory holds the **build-time** sources and tooling for the SMB3 base
patch (`../data/basepatch.bsdiff4`). None of it ships in the `.apworld`; it is how
we *produce* the base patch that `Rom.py` applies at generation time.

The base patch is a `bsdiff4` delta between the **vanilla SMB3 (U) (PRG1)** ROM and
a **reassembled, modified** copy of the Southbird disassembly. The player supplies
their own ROM; we never distribute one.

## Pipeline (assemble → diff → regenerate)

Prerequisites:
- The Southbird disassembly at `../../../disasm/` (a separate clone; gitignored).
  It ships a pristine `disasm/smb3.nes` (headered PRG1) used as the diff baseline.
- A native `nesasm` v3.1 (the repo's `disasm/nesasm.exe` is Windows-only; on macOS
  use the arm64 build at `tools/nesasm/nesasm`).
- Python 3 + `bsdiff4` (already an AP test dep).

Steps:

1. **Apply the ROM hooks to the disasm.** Currently just the on-map checkmark:
   ```sh
   python3 make_checkmark.py     # repaints CHR $88-$8B / $DC-$DF to a checkmark
   ```
   (Idempotent — re-running reproduces identical tiles.)

2. **Reassemble** the modified disasm into a patched ROM:
   ```sh
   cp -R ../../../disasm /tmp/smb3-build
   cd /tmp/smb3-build
   /path/to/nesasm smb3.asm          # emits smb3.nes next to smb3.asm
   ```
   Sanity: with **no** hooks applied, the reassembled `smb3.nes` is **byte-identical**
   to the pristine `disasm/smb3.nes` (the toolchain is byte-perfect for PRG1).

3. **Diff** the patched ROM against pristine vanilla and write the base patch:
   ```sh
   python3 - <<'PY'
   import bsdiff4
   van = open("/path/to/disasm/smb3.nes","rb").read()      # pristine
   pat = open("/tmp/smb3-build/smb3.nes","rb").read()       # reassembled + hooks
   open("../data/basepatch.bsdiff4","wb").write(bsdiff4.diff(van, pat))
   assert bsdiff4.patch(van, open("../data/basepatch.bsdiff4","rb").read()) == pat
   PY
   ```

4. **Verify** in the test suite (`worlds.smb3.test.test_rom`) and in BizHawk (see
   below). The tests assert the patch round-trips to the known patched CRC and that
   only the intended CHR bytes change.

## Reference hashes (SMB3 (U) (PRG1) [!])

| ROM | size | CRC32 (headerless) | MD5 (headerless) |
|---|---|---|---|
| vanilla PRG1 | 393232 (w/ 16B iNES header) | `2e6301ed` | `55b7111567c1709e849c574078699577` |
| + checkmark  | 393232 | `e88e6c2b` | — |

The current base patch changes **66 bytes** in two CHR clusters (`0x45894-0x458CC`
in chr022, `0x45DD4-0x45E0C` in chr023) — the completed-panel glyph tiles.

## Current hooks

- **On-map checkmark** (`make_checkmark.py`): vanilla marks a cleared overworld
  panel with an "M"/"L" glyph (CHR tiles `$88-$8B` / `$DC-$DF`). We repaint those
  CHR tiles to a checkmark. Both the live panel-flip animation
  (`Map_PanelCompletePats`, `PRG/prg011.asm`) and the on-reload map state
  (`Map_CompleteByML_Tiles`, `PRG/prg012.asm`) reference these exact indices, so
  the CHR edit alone applies everywhere with no ASM/table changes.

- **World-9 hub, part 5a — start in World 9** (`make_hub.py`): an ASM hook that
  starts a new game in World 9 (the Warp Zone) as a travel hub. Three non-shifting
  edits: (1) the new-game start-world byte `LDA #$00`→`#$08` (`prg024.asm:2399`,
  file `0x30CC3`); (2) retarget `JSR Map_Init` in `PRG030_84A0` to a new `HubInit`
  routine; (3) append `HubInit` into bank 30's trailing free space (`$9FB6`, 74
  blank bytes) — it runs `Map_Init` then, for World 9, fixes the two out-of-bounds
  hazards `World_Num=8` causes (a garbage start-Y from the 8-entry `Map_Y_Starts`,
  and junk map objects from the 8-entry `Map_List_Object_*` tables). Return-to-hub
  + world-select panels (5b) build on the same free-space technique.

**Two base patches** (both reassembled from the disasm, both diffed vs pristine
vanilla): `basepatch.bsdiff4` = checkmark only; `basepatch_hub.bsdiff4` = checkmark
+ hub. `Rom.py` picks which to apply based on the `hub_world` option. To regenerate
the hub patch: `python3 make_hub.py --phase 5a`, reassemble, then
`bsdiff4.diff(vanilla, hub_rom)` → `../data/basepatch_hub.bsdiff4`.

## BizHawk manual check

- **Checkmark:** load a generated `.apsmb3`-patched ROM, clear any level, and confirm
  the panel it leaves behind shows a **checkmark** (not an M/L). Check a few worlds —
  the mark inherits each world's map palette (`Map_Tile_ColorSets`, `PRG/prg012.asm`).
- **Hub (5a):** with a `hub_world`-on seed, start a **new game** — it should drop you
  directly onto the **World-9 (Warp Zone) map**, player standing on the path, with no
  glitched map objects. (Free travel / return-to-hub is 5b.)

## Tooling

- `pcxtool.py` — minimal PCX (8-bit RLE) reader/writer + NES CHR tile helpers
  (no Pillow). `python3 pcxtool.py <file.pcx> <tile_index> ...` dumps tiles as
  ASCII for inspection.
- `make_checkmark.py` — applies the checkmark hook to `disasm/CHR/chr022.pcx` and
  `chr023.pcx`.
- `make_hub.py` — applies the World-9 hub ASM hooks to the disasm PRG sources.
  `python3 make_hub.py --phase 5a` (start-in-World-9; `5b`/`all` follow). Idempotent.
- `gen_panels.py` — parses the disassembly's per-world structure tables
  (`disasm/PRG/maps/WorldNS.asm`) and regenerates the committed `../panels.py`:
  the completable overworld panels (levels + toad houses) keyed by
  `(world, byte_offset, bit_mask)`, the identity the game marks on completion.
  Run `python3 worlds/smb3/patch/gen_panels.py` to regenerate; review the diff.
  Fortresses are intentionally excluded (they keep the Phase-0 count-based path;
  see `known_bugs.md` BUG-002). The one flagged exclusion, `W5TDL` (World 5 Tower
  Downward), is a special tower level, not a standard panel.
