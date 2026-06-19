# Next Steps — turnkey brief for a fresh session

This file lets a cold session pick up the work without prior chat context. Read [DESIGN.md](DESIGN.md)
first — it has the full architecture, scope, and the disassembly-derived RAM addresses.

---

## Where things stand

- **DESIGN.md** is finalized. Scope is **Phase 0 (POC)**: 7 airship-boss defeats (Worlds 1–7) = 7 AP
  locations; victory = beat Bowser's Castle (vanilla). Phases 1–3 are deferred (sketched in DESIGN §2, §8).
- **`git init` done.** One safety commit exists. `Archipelago/` and `disasm/` are **gitignored** (large
  upstream clones, reference-only).
- **Reference clones present in the repo (gitignored):**
  - `disasm/` — captainsouthbird SMB3 disassembly (nesasm). RAM addresses already mined; see DESIGN §5 & §9.
  - `Archipelago/` — the framework. Develop the apworld inside `Archipelago/worlds/smb3/`.

## Reference worlds to model against (already cloned)

- **`Archipelago/worlds/tloz/`** — Legend of Zelda 1 (NES). Best **structure** template:
  `__init__.py`, `Items.py`, `Locations.py`, `Rules.py`, `Options.py`, `Rom.py`, `z1_base_patch.bsdiff4`.
- **`Archipelago/worlds/mm2/`** and **`mm3/`** — Mega Man 2/3 (NES). Best **BizHawk client** precedent
  (they subclass `worlds/_bizhawk/client.py`'s `BizHawkClient`). Model `Client.py` on these.
- **`Archipelago/worlds/_bizhawk/`** — the `BizHawkClient` base + README. Read the README before writing
  the client.

---

## MILESTONE 1 (do this now): Skeleton APWorld — pure Python, generates a valid seed

**Goal / done-criterion:** `Archipelago/worlds/smb3/` generates a solo seed with no errors via AP's
`WorldTestBase`. **No ROM patching, no client, no real detection yet** — structure only.

### Build

Create `Archipelago/worlds/smb3/`:

1. **`Options.py`** — `goal` (default: beat Bowser's Castle), `item_model` toggle (A = filler-only
   [recommended default], B = gated worlds). See DESIGN §3.2.
2. **`Items.py`** — item id table + classifications. Model A: filler (extra life, power-ups) + a `Victory`
   event item. Keep ids stable/documented.
3. **`Locations.py`** — the **7** airship locations (World 1–7 "Airship — Boss Defeated") + ids +
   placeholder fields for ROM/RAM addresses (filled in a later milestone). See DESIGN §3.1.
4. **`Regions.py`** — `Menu` + `World 1`–`World 7` regions and connections.
5. **`Rules.py`** — minimal access rules (model A) + victory completion condition
   (`multiworld.completion_condition`).
6. **`__init__.py`** — `SMB3World(World)`: game name, item/location name-to-id maps, `create_items`,
   `create_regions`, `set_rules`, options dataclass wiring. Match the **current** AP API as seen in `tloz`
   — do not code from memory; read `tloz/__init__.py` first.

### Validate

- Run the apworld's tests against `WorldTestBase` (see how `tloz`/`mm2` wire their `test/`), or generate a
  solo seed. Generation must succeed with 7 locations and a reachable victory.

### Out of scope for Milestone 1 (deferred)

- The ASM base patch (Track A), `basepatch.bsdiff4`, the BizHawk `Client.py`, and any real in-game
  detection. Those are Milestones 2–5 in DESIGN §8.

---

## After Milestone 1

Follow DESIGN §8 sequencing: (2) Track A v0 — reassemble disasm byte-for-byte, then add the first
"airship cleared" flag hook → `basepatch.bsdiff4`; (3) Client v0; (4) vertical slice (1 airship end-to-end);
(5) fill out all 7 + item grant + victory; (6) Phase 1 (ALL FORTS).

## Working agreements

- Commit logical chunks (the repo is git-tracked now). Don't commit `Archipelago/` or `disasm/`.
- Keep DESIGN.md and this file in sync if scope changes.
- When in doubt about the AP API, read a current reference world in `Archipelago/worlds/` rather than
  assuming — the API moves.
