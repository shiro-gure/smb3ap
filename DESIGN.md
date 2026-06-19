# SMB3 Archipelago APWorld — Design Doc

**Status:** Design only. No implementation has started.
**Scope of this doc:** Phase 0 (the POC) in full detail, with Phase 1 (ALL FORTS) sketched as the follow-on.
**Date:** 2026-06-18

---

## 1. Project goal

Build an Archipelago (AP) **APWorld** for **Super Mario Bros. 3 (NES, USA Rev 2)** so SMB3 can
participate in an AP multiworld — its in-game events become *locations* that hand items to
other players, and its progression can be gated by *items* received from the multiworld.

This is greenfield: **no SMB3 APWorld exists in Archipelago today** (the `worlds/smb3` path 404s upstream).

### Reference material (already gathered)

| Piece | Role | Local path / URL |
|---|---|---|
| Archipelago framework | Host for the APWorld + client | https://github.com/ArchipelagoMW/Archipelago |
| **SMB3 disassembly** (captainsouthbird) | Authoritative ROM/RAM map; base for the ASM patch | `disasm/` (cloned) — https://github.com/captainsouthbird/smb3 |
| SMB3 web randomizer (ssjtroly) | JS *logic* reference only; **no multiworld support** | `../smb3-web-rando/` |

The disassembly assembles with **nesasm** (`disasm/nesasm.exe`), 32 PRG banks, fully labeled and commented.

---

## 2. Phasing

The original ruleset is staged. This doc commits only to **Phase 0**; later phases are recorded so the
architecture doesn't paint us into a corner.

| Phase | Content | Status |
|---|---|---|
| **Phase 0 (POC)** | Vanilla SMB3 structure. 7 airship-boss defeats (Worlds 1–7) = 7 AP locations. Goal = beat Bowser's Castle (vanilla). | **This doc** |
| Phase 1 | "ALL FORTS": fortress clears become additional AP locations. Goal = clear every fortress, then beat Bowser. | Sketched (§8) |
| Phase 2 | Hammer Bros. drop checks. | Deferred |
| Phase 3 | World 9 / Warp Zone start, world revisiting, question-block randomization, hammer-breakable map locks, checks-in-question-blocks. | Deferred |

**Why Phase 0 first:** it isolates *integration risk* (does the patch + BizHawk client + AP server loop
work at all?) from *game-design risk* (the ALL FORTS ruleset). Phase 0 gives a playable, verifiable
multiworld slice from the simplest native game events; forts then layer on as "more of the same."

---

## 3. Phase 0 — the POC, precisely

### 3.1 Locations (7)

| # | Location name | Trigger event | Detection (see §5) |
|---|---|---|---|
| 1 | World 1 Airship — Boss Defeated | Larry (W1 airship Koopaling) defeated | `Map_Completions` bit for the airship panel flips |
| 2 | World 2 Airship — Boss Defeated | Morton | same |
| 3 | World 3 Airship — Boss Defeated | Wendy | same |
| 4 | World 4 Airship — Boss Defeated | Iggy | same |
| 5 | World 5 Airship — Boss Defeated | Roy | same |
| 6 | World 6 Airship — Boss Defeated | Lemmy | same |
| 7 | World 7 Airship — Boss Defeated | Ludwig | same |

> World 8 has no Koopaling airship boss in this model — World 8's climax is Bowser's Castle itself, which is
> the **victory** condition (§3.3), not a location.

> **Note on "8 checks per boss":** the original rules said *8 checks in each airship boss*. We deliberately
> reduced this to **1 check per airship boss** for the POC, because an airship boss is a single completion
> event in SMB3 — there is no native "8 sub-checks" structure. One check per boss maps cleanly onto a real
> persistent game flag with zero contrivance.

### 3.2 Items

For a *vanilla-structure* POC the SMB3 side does not strictly need progression gating (the player can reach
all airships normally). Two viable models:

- **A — Filler only (recommended for first cut):** the 7 locations hold AP items for the multiworld; SMB3
  itself receives filler/junk (extra lives, power-ups) and a small set of "useful" items. No SMB3
  progression is gated by received items. Simplest; proves the loop.
- **B — Gated worlds (optional):** define "World N Unlock" progression items that gate entry to each world,
  forcing the generator to place them logically. More AP-idiomatic but needs a map-lock ASM hook; defer to
  Phase 1 unless desired.

**Recommendation:** ship Phase 0 with model **A**. The received-item handler still needs to *do something*
in-game (grant a life / power-up) to prove the receive path — see §5.3.

### 3.3 Victory condition

**Beat Bowser's Castle (vanilla).** Detected via `Player_RescuePrincess` (§5.2).

### 3.4 Regions & rules (Phase 0)

Minimal. One region per world (`World 1` … `World 8`) plus `Menu`. With item model A there are no item-based
access rules — each airship location is reachable once its world is reached, and in vanilla SMB3 worlds are
reached in sequence. Rules become meaningful only under model B / Phase 1.

---

## 4. Architecture — two tracks

The work splits cleanly. **No 6502 assembly happens at seed-generation time.** The ASM is built once,
ahead of time, into a base patch; Python only applies that patch and writes item bytes.

```
 ┌─────────────────────────── TRACK A (build once, ASM) ──────────────────────────┐
 │  disasm/ (nesasm source)                                                        │
 │     + custom AP hooks (location-flag writes, received-item handler, AP RAM)     │
 │     → assemble → base ROM                                                       │
 │     → diff vs vanilla US ROM → basepatch.bsdiff4   (shipped in the apworld)     │
 └────────────────────────────────────────────────────────────────────────────────┘

 ┌─────────────────────────── TRACK B (per-seed, Python) ─────────────────────────┐
 │  worlds/smb3/  (the APWorld)                                                    │
 │     __init__.py · Items.py · Locations.py · Regions.py · Rules.py · Options.py  │
 │     generate_output():  apply basepatch.bsdiff4  →  write item/location bytes   │
 │  + BizHawkClient subclass (uses the generic connector_bizhawk_generic.lua)      │
 └────────────────────────────────────────────────────────────────────────────────┘

 At play time:
   BizHawk ── generic Lua connector ──► SMB3 BizHawkClient (Python) ──► AP server
              (reads RAM flags, writes received items)
```

### 4.1 APWorld file layout (proposed)

```
worlds/smb3/
  __init__.py        # SMB3World(World): registers items/locations/regions, generate_output
  Items.py           # item id table, classifications (progression/filler)
  Locations.py       # the 7 airship locations + ids + ROM/RAM addresses
  Regions.py         # Menu + World 1..8 regions and connections
  Rules.py           # access rules (minimal in Phase 0)
  Options.py         # AP options (goal, item model A/B, etc.)
  Client.py          # SMB3BizHawkClient(BizHawkClient)
  data/
    basepatch.bsdiff4
  patch/             # Track A source (ASM hooks) — built, not run at gen time
    README.md        # how to assemble + regenerate basepatch.bsdiff4
```

### 4.2 Client target

**BizHawk + the generic connector** (`connector_bizhawk_generic.lua`, ships with AP). We write a Python
`BizHawkClient` subclass — **not** a bespoke Lua script. The client polls SMB3 RAM, reports newly-set
location flags to the server, and writes received items into RAM. BizHawk ≥ 2.3.1.

---

## 5. ROM/RAM research findings (from `disasm/`)

All addresses below are taken directly from the disassembly. These are the concrete hooks the client and
the ASM patch use. Cited as `file:line`.

### 5.1 Airship boss defeat → persistent location flag

The in-level defeat moment is well-defined:

- `ObjHit_Koopaling` counts hits; on the 3rd hit → **"Koopaling defeated!"** and `INC Level_GetWandState`
  (state 0→1). — `disasm/PRG/prg001.asm:3685`, `:3708`
- The wand grab runs the bonus/animation states, then `Koopaling_AirshipVanish` sets
  `Map_ReturnStatus = 0` (level cleared) and returns to the map. — `disasm/PRG/prg001.asm:4225`, `:4297`

The **persistent** record (what the client should watch, since `Level_GetWandState` is transient in-level
RAM) is:

- **`Map_Completions` — `$7D00`–`$7D3F` (Mario), `$7D40`–`$7D7F` (Luigi).** — `disasm/smb3.asm:2711`
  - Per-column bitfield. "Stores rows of completed levels **or other map alterations** (rock break,
    mini-fortress lock removal, etc.)." — `disasm/smb3.asm:2695-2699`
  - Bit layout per column (top→bottom of map): `$80,$40,$20,$10,$08,$04,$02, INVALID, $01`. Row 8 is
    invalid for a level panel.
  - Loaded/restored by `Map_Reload_with_Completions`. — `disasm/PRG/prg030.asm:560,715,2947`

**Detection approach:** map each airship panel to its (player, column, bit) in `Map_Completions`. When that
bit transitions 0→1, the world's airship boss is cleared → send the corresponding AP location check. The
exact column/bit per world is a small, mechanical lookup to finish during implementation (enter each
airship in a vanilla ROM, read `$7D00+` before/after). This is the **one remaining concrete unknown** for
Phase 0 and is low-risk.

> Fallback if per-panel mapping proves fiddly: an ASM hook in `Koopaling_AirshipVanish` writes a dedicated
> "airship N cleared" byte into our own AP RAM scratch region (see §5.4), which the client reads directly.
> This is cleaner and is the **recommended** approach since Track A already touches the ROM.

### 5.2 Victory — beat Bowser's Castle

- `Bowser_HandleIfDead` handles Bowser's death. — `disasm/PRG/prg001.asm:6043`
- After Bowser falls into the pit, the player walks to the door and presses **Up** →
  `STA Player_RescuePrincess` ("Flag for princess rescue!"), then `INC Level_ExitToMap`.
  — `disasm/PRG/prg001.asm:6299-6302`
- `Player_RescuePrincess` is consumed by the ending sequence. — `disasm/PRG/prg030.asm:2618`

**Detection approach:** client watches `Player_RescuePrincess`; non-zero ⇒ send AP victory
(`ClientStatus.CLIENT_GOAL`). Exact address to be read from the equates during implementation (it's a named
`.ds` var in the page-3/4/5/6 RAM block).

### 5.3 Granting received items

Persistent player state the patch/client can write to apply a received AP item:

- **`Player_Lives` — `$0736`–`$0737`** (Mario/Luigi). — `disasm/smb3.asm:2057` — grant extra lives.
- **`Inventory_Items` — `$7D80`–`$7D9B`** (Mario, 4×7 grid); `Inventory_Items2` `$7DA3`–`$7DBE` (Luigi).
  — `disasm/smb3.asm:2728,2733` — grant inventory power-ups (mushroom/flower/leaf/etc.).
- `Player_Suit` (`disasm/smb3.asm:869`), `Player_QueueSuit` (`:1696`) — current/queued suit, for immediate
  power-up grants.

**Recommended mechanism:** an ASM hook (Track A) runs each frame on the map/in-level, reads a "pending
item" byte from AP RAM scratch (written by the client), applies it (e.g. `INC Player_Lives` or push into
`Inventory_Items`), and clears the byte. This avoids the client racing the game's own writes to live state.

### 5.4 AP RAM scratch region (to define in Track A)

We need a few bytes of RAM the game never touches, for: pending-received-item, last-applied-item index
(dedup), and optional per-location "already sent" mirror. SMB3 has unused/`Unused`-tagged RAM (e.g.
`Map_UnusedPlayerVal` `$7F-$80`, `Map_UnusedGOFlag`) — the patch README will pick a safe, battery-backed
region in the `$7000`+ SRAM range adjacent to `Map_Completions`. Finalize during Track A.

### 5.5 Phase 1 preview — fortress clears (not built yet)

Already located, so the doc is future-proof:

- `Map_DoFortressFX` — "Bust locks, build bridges, whatever after Mini-Fortress is toppled." Set after Boom
  Boom is defeated (value selected by Boom Boom's Y-Hi). — `disasm/smb3.asm:2072`,
  `disasm/PRG/prg003.asm:1771,1955-1957`
- Fortress lock removal is **also recorded in `Map_Completions`** (§5.1 — "mini-fortress lock removal"), so
  Phase 1 fortress checks reuse the exact same detection channel as the airship checks. Clean.

---

## 6. Generation flow (Track B, per seed)

`SMB3World.generate_output()`:
1. Load the player's vanilla US SMB3 ROM (provided locally per AP convention; not distributed).
2. Apply `data/basepatch.bsdiff4` → AP-aware base ROM.
3. Write item placements: for each of the 7 airship locations, write the byte identifying *what AP item*
   sits there (so the patched game/client knows what to award the local player when that location is the
   player's own item) and the metadata the client needs.
4. Emit the patched ROM (`.apsmb3` patch file per AP packaging).

No assembler is invoked here — only bsdiff apply + byte writes.

---

## 7. Risks & open items

| Item | Risk | Mitigation |
|---|---|---|
| Per-airship column/bit in `Map_Completions` | Low | Empirically read `$7D00+` before/after each airship; OR use the §5.1 ASM-flag fallback (recommended). |
| `Player_RescuePrincess` exact address | Low | Named var; grab from equates during impl. |
| AP RAM scratch placement | Low–Med | Pick safe SRAM bytes in Track A; document in patch README. |
| Track A toolchain (nesasm build reproducibility) | Med | Pin `disasm/nesasm.exe`; script the assemble→diff in `patch/README.md`; verify byte-for-byte vanilla reassembly first. |
| Vanilla ROM region/rev | Med | Disasm targets **USA Rev 2**; require that exact ROM (hash-check at gen time). |

---

## 8. Milestone sequencing (after this doc)

1. **Skeleton APWorld** — `Items/Locations/Regions/Options/Rules` that *generate a valid seed* (no real
   detection yet). Validates structure against AP's test base.
2. **Track A v0** — reassemble the disasm byte-for-byte (prove the toolchain), then add the smallest hook:
   write an "airship cleared" flag to AP RAM scratch on `Koopaling_AirshipVanish`. Produce
   `basepatch.bsdiff4`.
3. **Client v0** — `SMB3BizHawkClient` that connects via the generic connector and *reads* the airship
   flags + `Player_RescuePrincess`, sends location checks + victory.
4. **Vertical slice** — one airship: defeat W1 boss → AP location check appears on the server. End-to-end.
5. **Fill out** — all 7 airships + received-item grant (§5.3) + victory. Phase 0 complete & playable.
6. **Phase 1** — add fortress locations (reuse `Map_Completions`), change goal to ALL FORTS.

---

## 9. Key addresses quick-reference

| Name | Address | Purpose |
|---|---|---|
| `Map_Completions` (Mario) | `$7D00`–`$7D3F` | **Persistent** completed-panel + map-alteration bitfield (airship & fortress checks) |
| `Map_Completions` (Luigi) | `$7D40`–`$7D7F` | same, P2 |
| `Player_RescuePrincess` | (named var, TBD) | Victory flag — set after Bowser |
| `Player_Lives` | `$0736`–`$0737` | Grant extra lives (received items) |
| `Inventory_Items` (Mario) | `$7D80`–`$7D9B` | Grant inventory power-ups |
| `Player_Suit` / `Player_QueueSuit` | (named vars) | Immediate power-up grant |
| `Map_ReturnStatus` | `$06xx` | 0 = level cleared (in-level signal) |
| `Map_DoFortressFX` | (named var) | Phase 1: fortress toppled FX |
| `Level_GetWandState` | (named var) | In-level Koopaling-defeat state (transient) |

*Addresses without a hex value are named `.ds` variables in `disasm/smb3.asm`; resolve to absolute
addresses during implementation by tracing the equate block.*
