# Known Bugs

A running log of known issues. Newest first.

---

## BUG-004 — World 8 vehicle / pyramid panels are not AP checks and are non-re-enterable (follow-up)

**Logged:** 2026-08-08
**Area:** panel classification (`worlds/smb3/patch/gen_panels.py` `_EXCLUDE`) + re-entry (shared with PR 5c)
**Severity:** Low — by-design today; logged as a scope decision, not a regression.
**Status:** Open — deferred follow-up (raised while validating PR 5c in-game).

### What
World 8's map is mostly **non-numbered-level panels**: tanks (`W8T1L`/`W8T2L`), the battleship
(`W8BSL`), the airship (`W8AirshipL`), hand-traps / "pyramids" (`W8H1L`-`W8H3L`), and Bowser's castle
(`W8BCL`). Only **8-1 (`W801L`) and 8-2 (`W802L`)** are treated as normal levels; those two DO fire as
AP checks and were verified in-game. The vehicle/pyramid panels are (a) intentionally excluded from AP
locations by `gen_panels.py` `_EXCLUDE`, and (b) non-re-enterable after clear (same completion-tile
coupling as levels — see PR 5c).

### Scope to decide (not a straight bugfix)
1. Should any of the vehicle/pyramid panels become **AP location checks**? (Airships already have their
   own detection path; tanks/battleship/hand-traps currently have none.)
2. Should they be **re-enterable** after clear? If yes, they can reuse the PR 5c level-repaint
   decoupling — BUT the level path is discriminated from toad houses at `prg012.asm:355` (quadrant
   range) vs `:343` (`Map_Completable_Tiles`); World-8 vehicles route via their own structure-table
   types, so confirm which repaint branch they hit before extending.
3. **Bowser's Castle (`W8BCL`) is the victory goal** — it must NOT become a repeatable check or a
   re-enterable "cleared" panel. Exclude it explicitly from any of the above.

---

## BUG-003 — Hub World: warp clears the on-map completion bitfield (checkmarks reset)

**Logged:** 2026-08-08
**Area:** World-9 hub (`worlds/smb3/patch/make_hub.py`; disasm map-init path)
**Severity:** Low — cosmetic in-game only; **AP checks are NOT affected** (server-side; client re-syncs).
**Status:** FIXED in PR 5c — but **client-driven**, not a ROM gate. First attempt gated the ROM clear
loop (`Hub_Persist`); that BLED one world's checkmarks onto another world's panels, because
`Map_Completions` ($7D00-$7D7F) is a single **world-agnostic** 128-byte bitfield and there is **no free
persistent ROM RAM** to segment it per world (the only large WRAM block is the level-decompression
buffer `Tile_Mem`). So the ROM gate was reverted; the vanilla wipe-on-load is intact. Instead the AP
**client** is the persistent per-world store: on each world's map it re-asserts THAT world's cleared-level
checkmark bits from the AP checked set (`Client.py` `desired_completion_bytes` + a guarded write). The
ROM keeps the PR 5c level-repaint so a re-asserted bit paints the enterable `$16` checkmark tile
(re-enterable + walk-through). Visual note: repaint runs on the next map reload (enter a level and
return), so right after travel the board refreshes on the first level dip. Original deferred note below.

### What
The World-9 warp path (and the planned return-to-hub) route through `PRG030_84A0`, whose clear loop
(`disasm/PRG/prg030.asm:560-566`) **zeroes the entire `Map_Completions` bitfield** ($7D00-$7D7F — the
only copy; SMB3 has no SRAM). So travelling hub→World→hub→World **resets the in-game cleared-panel
checkmarks** each trip. Because the AP server records checks as they fire (and the client re-sends on
reconnect), **multiworld progress is safe** — only the cosmetic on-map state resets.

### Fix directions (when we do true persistence)
- Snapshot `$7D00-$7D7F` to free RAM before the clear and restore after the reload; or
- Branch warps to a non-clearing re-init entry (`~PRG030_84D7`, right after the clear loop) and clear
  only on a genuine new game.

---

## BUG-002 — `FORTRESS_COUNTS` (W3, W5) may not match distinct overworld fortress panels

**Logged:** 2026-07-27
**Area:** fortress locations (`worlds/smb3/Locations.py` — `FORTRESS_COUNTS`)
**Severity:** Low — shipped fortress detection works in-game; this is a data-model question.
**Status:** Open — surfaced by the PR 4 panel parser (`worlds/smb3/patch/gen_panels.py`);
deliberately NOT changed in PR 4 (would churn wire-format location ids).

### What
`FORTRESS_COUNTS = {1:1,2:1,3:2,4:2,5:2,6:3,7:2,8:1}` (total 14). The disasm structure-table
parser finds only **12 distinct fortress *overworld panels*** — Worlds 3 and 5 each expose **one**
fortress map panel (`W3F1L` at offset $08/bit $08; `W5F1L` at $04/$08). The `W3F2L`/`W5F2L` symbols
that made us think "2" are **alternate internal room layouts** of the same fortress (`Fortress/3-F2A.asm`
= "Alternate level layout"), not a second map panel. Worlds 4 and 6 genuinely have distinct extra
fortress panels (`W4F1/2L`, `W6F1/2/3L`).

### Nuance / why not fixed now
BUG-001's in-game log shows the user saw "W3 fortress 1 + fortress 2" fire. With count-based crediting,
a **second completion of the same W3 panel** (e.g. via the alternate exit/room) credits the world's
second fortress location — so a 2-count may actually reflect "the same panel cleared two ways" rather
than two panels. Whether that's the intended AP model is a **design decision**, and changing counts
changes fortress location ids (part of the wire format). Left as-is; the PR 4 panel table therefore
**excludes fortresses entirely** and only adds levels + toad houses.

### Fix directions
- Decide the intended model: one AP check per fortress *panel* (→ counts 1,1,1,2,1,3,2,1 = 12) vs.
  one per *completion path* (keeps 14, needs the alt-exit to be a real distinct signal). Ties into the
  "alternate exits as independent checks / 100% mode" idea in DESIGN.md §10.
- If counts change, treat it as a wire-format migration (ids shift) and re-verify fortress detection
  in-game (the same panels the user already validated).

---

## BUG-001 — Save-state reload / bulk Map_Completions change false-fires fortress detection

**Logged:** 2026-06-20
**Area:** fortress detection (`worlds/smb3/Client.py` — `fortress_cleared`)
**Severity:** Low for normal forward play; surfaces with save states, warps, and revisits.
**Status:** Open — root cause confirmed from in-game logs (2026-06-20); fix not yet implemented.

### Summary
When using save states, reloading a state in a world with fortresses can make the client emit a
(false) "fortress cleared" detection. Because fortress crediting is count-based / clear-order, a
false detection maps to "the next uncredited fortress" — i.e. it can credit the wrong / an extra
fortress location.

### Root cause (confirmed from logs 2026-06-20)
`fortress_cleared(prev, cur, tile)` returns True when **any** `Map_Completions` bit goes 0→1 between
passes **while `World_Map_Tile` is a fortress rubble tile** (`$60`/`$E3`). A **save-state reload
replaces the entire `Map_Completions` block at once**, so if the loaded state has more set bits than
the client's `_prev_completions` snapshot, that reads as a fresh 0→1 transition. If the player happens
to be on a rubble tile at that instant, it mis-fires.

Evidence in the log:
- `completions_set` jumps non-incrementally on reloads: `6 → 0 → 11 → 0 → 4 → 6 …` (heartbeats
  ~#1111–#1471) — the bitfield is being wholesale swapped, not changed one panel at a time.
- After World 3's two real fortresses were correctly credited (20:55:02 and 20:55:03), repeated
  `World 3 fortress cleared but no unchecked fortress location remains (map_tile=$60)` fired from
  20:57:11 onward — spurious detections from reload-induced bulk changes while on a `$60` tile. It was
  **harmless only because W3's fortresses were already credited**; with an uncredited fortress it
  would have false-credited the wrong/next one.

So BUG-001 is really: *bulk (non-incremental) `Map_Completions` changes produce false fortress-clear
edges*, and the count-based credit then attributes the false edge to "the next fortress."

### Secondary observation (related, log-confirmed)
World indexing is unreliable around warps / the World 9 warp zone. Heartbeats show `World_Num`
bouncing `$08 (world 9) → $05 (world 6) → $08 → $04 (world 5)` with `completions_set` resetting to 0.
Since fortress crediting uses the *current* world (`World_Num + 1`), crediting is fragile while the
player is warping or in the hub. This reinforces that count-based + `World_Num`-keyed crediting is the
wrong long-term model; a positional (which specific panel bit → which world+fortress) mapping is more
robust.

### What works (not affected)
Normal forward play credits correctly, including multiple fortresses in one world in order
(verified in-game: W1 fortress, W3 fortress 1 + fortress 2, all airships, fired correctly with proper
`New Check: <name>` logging). The bug only manifests with save-state reloads / bulk RAM swaps.

### Repro
1. Be in a world with a fortress; be on or near a fortress rubble tile, or mid-world.
2. Save a state, then load a state whose `Map_Completions` differs (e.g. more panels cleared).
3. On reload, if `World_Map_Tile` reads rubble (`$60`/`$E3`), the client logs a (false) "fortress
   cleared" — and would credit the next uncredited fortress in that world if one exists.

### Fix directions (not yet implemented)
- **Quick guard — ignore bulk swaps:** if more than one `Map_Completions` bit changes in a single
  pass (or `completions_set` drops then jumps), treat it as a load/sync and re-baseline
  `_prev_completions` without crediting. Cheap; directly kills the false edge.
- **Proper fix — positional crediting:** map the *specific* flipped `(col, bit)` → the specific
  world+fortress (positional formula), instead of count-based "next in current world." Removes the
  `World_Num` dependency and is revisit-safe. Needs the per-fortress panel coordinates.
- **Decide revisit semantics by design** (ties into the World-9-hub / 100%-mode plans —
  see DESIGN.md §10 and NEXT_STEPS.md).
- **Durable end-state:** the ASM-written persistent per-clear bitfield (DESIGN.md §10 / NEXT_STEPS.md)
  makes detection sticky and reload/warp/revisit-safe.
