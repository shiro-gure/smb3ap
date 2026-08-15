# Known Bugs

A running log of known issues. Newest first.

---

## BUG-008 — A Hammer Bro the player did NOT beat is cleared from the map after revisiting

**Logged:** 2026-08-15
**Area:** roaming-enemy persistence (`worlds/smb3/Client.py` — `newly_defeated_bro_slots` /
`_defeated_bro_slots` / `reblank_defeated_slots`)
**Severity:** Low-Med — a Hammer Bro (and its item/coin-ship reward) can be lost without earning it;
gameplay/reward bug, not a crash. AP checks unaffected (bros aren't checks).
**Status:** Open — reported in-game 2026-08-15 (user did NOT defeat the bro; on revisiting the world it
was gone). Introduced by the PR-5c bro-persistence feature (commit `441dcf2`).

### What
The client persists a defeated roaming enemy by recording, per world, which `Map_Objects_IDs` ($7F15)
SLOT went from a BRO id → `$00`, then re-blanking that slot on revisit so a beaten bro stays gone. The
symptom: a bro the player never beat gets recorded as defeated and is wrongly re-blanked on return.

### Root-cause hypotheses (to confirm in-game / from the disasm)
1. **Marching bros move/relocate slots.** Overworld Hammer Bros march around (`Map_Operation = $0B`,
   "Hammer bros march around", `disasm/PRG/prg011.asm:~1413/1602`). If the engine relocates a bro to a
   different slot (or transiently blanks slot _i_ while re-placing it), `newly_defeated_bro_slots` sees
   slot _i_ go BRO→`$00` and records a false "defeat". On revisit the fresh bro in slot _i_ is then
   re-blanked. This best matches "didn't beat him but he's gone."
2. **Ambush-survived / walked-away.** If a bro's slot blanks when the player enters/leaves its ambush
   without winning (e.g. the encounter ends without the defeat write at `prg011.asm:2037-2038`), that
   also reads as a defeat. Need to confirm whether any non-victory path blanks the slot.
3. **Transient blank during Map_Init/travel.** A pass that reads the object table mid-repopulation could
   catch a slot at `$00` momentarily; the world-unchanged guard should prevent this, but verify the
   guard holds across the `Map_Operation` states around travel.

### Fix directions (not yet implemented)
- **Gate detection on an actual defeat signal, not just slot→$00.** Only record a defeat when the blank
  coincides with the vanilla defeat path — e.g. the player is standing on that object (`Map_HideObj` /
  the clear-FX `Map_ClearLevelFXCnt` active, `prg011.asm:2000-2040`), or `Map_Operation` is the
  enter/clear state — rather than any BRO→$00 transition. This rejects marching/relocation blanks.
- **Identity-match instead of slot-match.** Track the bro's (id + position) and only treat it as defeated
  when it disappears at rest, not when it moves. Requires reading `Map_Objects_Y/XLo/XHi` too.
- **Only re-blank slots confirmed dead at a settled map** (`Map_Operation == $0D`) and cross-check the
  position matches the recorded one.
- Interim: consider disabling bro re-blank while a world's bros are still marching, or requiring two
  consecutive settled passes showing the slot dead before recording it.

### Repro
1. `hub_world:true`. Enter a world with a Hammer Bro; do NOT beat it (walk past / let it march / leave).
2. Travel back to the hub, then re-enter that world.
3. Observe the bro is gone (wrongly re-blanked) even though it was never defeated.

---

## BUG-007 — Player sprite is slightly misaligned with the map grid

**Logged:** 2026-08-15
**Area:** hub landing / map player position (`worlds/smb3/patch/make_hub.py` `HubInit`; disasm map-coord path)
**Severity:** Low — cosmetic only; movement, pipe entry, and level entry all work.
**Status:** Open — deferred (user wants to fix later; not blocking).

### What
On the world map the player (Mario/Luigi) sprite sits slightly off from the panel/path tile grid — the
sprite is not pixel-aligned with the tile the player logically occupies. Not breaking: the player can
still walk, enter pipes, and enter levels normally; it's purely a visual offset.

### Where to look when we fix it
- `HubInit` sets the hub landing coords directly: `Map_Entered_X = $60`, `Map_Entered_Y = $50`
  (`worlds/smb3/patch/make_hub.py`). The comment there already notes the pipe graphic is drawn a row
  higher than the standing cell — a likely source of a half-tile visual offset. Check whether the chosen
  `$60/$50` lands the sprite centered on the tile vs. the vanilla map-coord convention.
- Coordinate convention (authoritative): `Map_GetTile` uses `col = World_Map_X >> 4`,
  `tile_row = (World_Map_Y - $10) >> 4` (`disasm/PRG/prg010.asm:3295-3298`). If the sprite draw uses a
  different Y base than the tile lookup, that's the misalignment.
- Confirm whether the offset is hub-specific (only on the World-9 landing / custom pipe) or general to
  all worlds after travel. If hub-only, it's a `HubInit` coord fix; if general, look at the shared map
  reload tail (`PRG030_84D7`) restoring player position.
- Repro: note the exact world/tile where it's most visible (user first saw it on the hub) so the fix can
  be verified against that spot.

---

## BUG-006 — Toad houses don't stay used after warp-whistle + revisit

**Logged:** 2026-08-08
**Area:** hub travel / completion persistence (`worlds/smb3/Client.py`; disasm toad-house path)
**Severity:** Low — cosmetic/gameplay (a toad house can be re-run for another item).
**Status:** FIXED 2026-08-15 (PR 5c) — the client re-assertion now covers toad houses, not just
levels. `_DRAWABLE_PANEL_BITS` includes `kind == "toad_house"` and `desired_completion_bytes` re-asserts
their `Map_Completions` bits on every map load (including the warp-whistle→hub→back path), so a used toad
house stays marked. Caveat: this restores the bit only for toad-house locations the AP client knows are
checked — i.e. when `level_checks` is on (toad houses become AP locations then). Verify in-game on the
whistle path. Original hypothesis below (now the implemented fix).

### What
User reports: after using a **warp whistle** and revisiting a world, a previously-used toad house is no
longer marked used and can be re-entered/re-run. Two things to confirm/untangle:
1. **Whistle scope:** PR 5c dropped the planned infinite whistle; a *vanilla* warp whistle still exists
   in-game (item $0C) and warps to World 9. Confirm the user's "warp whistle" is the vanilla item (not a
   reintroduced hub whistle) and the exact path (whistle → hub → travel back → toad house un-used).
2. **Root cause hypothesis:** toad-house "used" state is the same `Map_Completions` bit that travel wipes
   (world-agnostic bitfield; see BUG-003). The client re-asserts *level* checkmarks only
   (`_LEVEL_PANEL_BITS` filters `kind == "level"`), NOT toad houses — so a used toad house's bit is not
   restored after travel, and its panel reverts to enterable/unused. If we want toad houses to "stay
   used" across travel, the client must also re-assert toad-house bits (but toad houses are NOT AP
   locations unless level_checks is on, and "used" is a play-state we may not be tracking server-side).
   Decide: persist toad-house used-state (needs a client-side record of which were used) vs accept reset.

---

## BUG-005 — Cleared fortresses reset their (rubble/cleared) state after travel

**Logged:** 2026-08-08
**Area:** hub travel / completion persistence (`worlds/smb3/Client.py`; disasm fortress repaint)
**Severity:** Low-Med — cosmetic on the map; AP fortress checks are safe (server-side).
**Status:** FIXED 2026-08-15 (PR 5c). `gen_panels.py` now emits `FORTRESS_PANEL_BITS` (world → ordered
[(offset,bit)]); `desired_completion_bytes` re-asserts fortress bits by count — it lights the first N
fortress panels of a world where N = how many of that world's fortress locations are checked (count-based
to match `FORTRESS_COUNTS`; never more panels than exist, covering the W3/W5 "2 locations, 1 panel" case
from BUG-002). The reload repaints the rubble/cleared tile from the restored bit — no `$16` enterable
treatment needed (forts stay non-enterable rubble, which is correct). Fix direction below is what shipped.

### What
After completing a fortress and traveling away/back, the fortress panel reverts to its pre-clear
(uncleared) look instead of staying as the cleared/rubble tile — same root cause as BUG-003 (the
world-agnostic `Map_Completions` bitfield is wiped on every world load). The PR 5c client re-assertion
(`desired_completion_bytes`) restores only **level** checkmark bits (`_LEVEL_PANEL_BITS`, `kind ==
"level"`), so fortress bits are not restored and the fortress panel resets.

### Fix direction
Extend the client re-assertion to also set fortress panels' `Map_Completions` bits for the current
world from the AP checked set. Caveats: (a) fortresses are NOT in the `PANELS` table (excluded by design
— see BUG-002); their (offset,bit) coords would need to come from a fortress panel table (the parser saw
them, gen_panels.py:153-161, but drops them). (b) The fortress repaint tile is the rubble/removable tile
(`Map_Removable_Tiles`/`Map_RemoveTo_Tiles`, prg012.asm:135-143), NOT the M/L checkmark — setting the
bit should make `Map_Reload_with_Completions` repaint the rubble correctly (verify it doesn't need the
enterable-$16 treatment; forts are meant to become non-enterable rubble, which is fine). User request:
"forts after completion should be similar to checkmark tiles" — i.e. persist like levels do.

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
