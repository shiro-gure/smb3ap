# Known Bugs

A running log of known issues. Newest first.

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
