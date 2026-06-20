# Contributing to the SMB3 Archipelago APWorld

Thanks for your interest! This is an [Archipelago](https://archipelago.gg) (AP)
APWorld for **Super Mario Bros. 3 (NES, USA PRG1 / Rev A)** — the `Super Mario Bros. 3
(U) (PRG1) [!]` ROM (headerless CRC32 `2e6301ed`, SHA1
`bb894d104c796f69ba16587eb66c0275f5c2fc02`). It is an early client-only
proof-of-concept — see [`DESIGN.md`](DESIGN.md) for the architecture and roadmap.

> This PRG1 ROM is byte-for-byte identical to what the captainsouthbird disassembly
> reassembles to, so the disassembly is authoritative for all RAM addresses here (and
> a future ASM/base-patch track would reassemble cleanly). The client identifies the
> ROM by an internal signature, so it also tolerates PRG0, but PRG1 is supported.

## What this repo contains

```
worlds/smb3/        # the APWorld source (the only code that ships)
  __init__.py       # SMB3World: items, locations, regions, rules
  Items.py Locations.py Regions.py Rules.py Options.py
  Client.py         # BizHawk client: reads SMB3 RAM, sends checks, grants items
  archipelago.json  # apworld manifest
  test/             # WorldTestBase tests
DESIGN.md           # full design, RAM research + roadmap
```

The Archipelago framework itself and the SMB3 disassembly are **not** in this repo —
they are large upstream clones used only for reference and are gitignored.

## Development setup

You need a local checkout of [Archipelago](https://github.com/ArchipelagoMW/Archipelago).
The APWorld source lives here at `worlds/smb3/`, but Archipelago expects to find it at
`Archipelago/worlds/smb3/`. **Symlink it in** (Archipelago is an embedded git repo, so
the source can't live inside it and be tracked here):

```sh
ln -s /path/to/this-repo/worlds/smb3 /path/to/Archipelago/worlds/smb3
```

### Running the tests

Archipelago targets Python 3.12. The world tests only need a subset of AP's deps
(not kivy/cython). A throwaway venv inside the Archipelago clone works well:

```sh
cd /path/to/Archipelago
python3.12 -m venv .venv-test
.venv-test/bin/pip install PyYAML schema jellyfish orjson bsdiff4 \
    typing_extensions platformdirs websockets colorama pathspec
PYTHONPATH=. .venv-test/bin/python -m unittest worlds.smb3.test.test_basic -v
```

`ModuleNotFoundError` / "Could not load world" lines for *other* worlds are unrelated
upstream worlds missing optional deps — they don't affect `smb3`.

## Building & installing the `.apworld`

To test in a real Archipelago install, package the world as a `.apworld` (a zip whose
top-level entry is the `smb3/` folder), then drop it in your install's
`custom_worlds/` (source checkout) or the user `worlds/` dir (packaged app):

```sh
# from a clean staging copy, excluding test/ and __pycache__
( cd "$(mktemp -d)" && cp -r /path/to/this-repo/worlds/smb3 smb3 \
  && rm -rf smb3/test smb3/__pycache__ \
  && zip -rq smb3.apworld smb3 )
```

The manifest (`archipelago.json`) must include `compatible_version` and `version` for
loose `.apworld` loading in packaged builds, or the app rejects it as "Invalid or
missing manifest file."

## Playing / the BizHawk client

The client (`Client.py`) attaches to a **vanilla** SMB3 US (PRG1) ROM in BizHawk via
the generic Lua connector — there is no ROM patch yet. BizHawk needs the
**Lua+LuaInterface** core (NLua fails). Load the connector from your own Archipelago's
`data/lua/connector_bizhawk_generic.lua` (it depends on sibling files). Client log
output appears in the **Archipelago BizHawk Client window**, not BizHawk's Lua console.

### How boss detection works (airships + fortresses)

SMB3 has **no persistent per-clear flag** for airships (the airship's `Map_Completions`
"complete" branch is dead code, `disasm/PRG/prg011.asm:2010`), so the client detects each
boss fight in-level with adaptive polling. **`Level_ObjectID` ($0671–$0678)** holds the 8
active actor IDs; when a boss object appears there the client boosts its poll rate (the
defeat windows are brief), latched per-encounter so the lingering boss object doesn't
re-trigger.

**Airships (Koopaling):** when `OBJ_BOSS_KOOPALING = $0E` is on screen, watch
`Level_GetWandState` ($07BD): `0` = alive, `≥ 1` = final hit / defeated
(`disasm/PRG/prg001.asm:3061-3073`). On `≥ 1`, send the "World N Airship" check for the
current world (`World_Num + 1`; `World_Num` increments only later in the king's room).

**Fortresses (Boom Boom):** when Boom Boom (`$4B` jumping / `$4C` flying) is on screen,
watch `Map_DoFortressFX` ($0745). It is set nonzero *only* by the post-Boom-Boom "?" ball
on a fortress clear, then zeroed by the map FX (`disasm/PRG/prg003.asm:1769-1773`,
`prg010.asm:1842`) — so a **0→nonzero edge = a fortress was just beaten** in the current
world (`World_Num + 1`). Per-fortress identity is brittle to decode, so the client credits
fortresses per world in **clear-order** (count-based): the Nth fortress cleared maps to that
world's Nth fortress location. SMB3 has no Boom-Boom-bypassing fortress exit, so this one
signal covers every completion path. Fortress counts per world: W1:1, W2:1, W3:2, W4:2,
W5:2, W6:3, W7:2, W8:1 (= 14).

All checks dedup via `checked_locations`. Use `/smb3_debug on` to log these RAM values each
pass. (An earlier airship approach watched the transient `Cine_ToadKing` $05FD cinematic
flag, but at the 0.5s poll it was missed every time — hence the object + adaptive-poll model.)

## Pull requests

1. Fork and branch from `main`.
2. Keep changes focused; match the surrounding style.
3. Run the test suite (above) — `WorldTestBase` must stay green.
4. Don't commit the Archipelago clone, the disassembly, ROMs, `.apworld` builds, or
   any local venv (all gitignored).
5. Note any new RAM addresses with a source reference (the disassembly file:line).

Questions or design discussion: open an issue. See `DESIGN.md` first — it likely
already covers the area.
