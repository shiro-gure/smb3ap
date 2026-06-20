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

### How airship detection works

SMB3 has **no per-airship completion flag** — beating an airship boss routes through
the king's room and just does `INC World_Num` (`disasm/PRG/prg030.asm:2742`); the
airship's `Map_Completions` "complete" branch is dead code (`prg011.asm:2010`). So the
client watches **`World_Num` ($0727)**, the current world index (0 = World 1 … 7 =
World 8), and sends the "World N Airship" check once `World_Num >= N`. This is exact
for linear play; warp-whistle skips would mark skipped airships as cleared (acceptable
for the POC). Use `/smb3_debug on` in the client to log `World_Num` each pass.

## Pull requests

1. Fork and branch from `main`.
2. Keep changes focused; match the surrounding style.
3. Run the test suite (above) — `WorldTestBase` must stay green.
4. Don't commit the Archipelago clone, the disassembly, ROMs, `.apworld` builds, or
   any local venv (all gitignored).
5. Note any new RAM addresses with a source reference (the disassembly file:line).

Questions or design discussion: open an issue. See `DESIGN.md` first — it likely
already covers the area.
