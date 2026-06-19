# Contributing to the SMB3 Archipelago APWorld

Thanks for your interest! This is an [Archipelago](https://archipelago.gg) (AP)
APWorld for **Super Mario Bros. 3 (NES, USA PRG0)** — the `Super Mario Bros. 3 (U)
(PRG0) [!]` ROM (CRC32 `a0b0b742`, headerless SHA1
`a611b90b4833b20a364bf06ee3be3b9093ea4df9`). It is an early client-only
proof-of-concept — see [`DESIGN.md`](DESIGN.md) for the architecture and
[`NEXT_STEPS.md`](NEXT_STEPS.md) for the roadmap.

> Note: the reference disassembly in `DESIGN.md` targets the **PRG1** revision, so a
> byte-for-byte reassembly will *not* match a PRG0 ROM. The current client works
> against PRG0 (it identifies the ROM by an internal signature, not a revision hash).

## What this repo contains

```
worlds/smb3/        # the APWorld source (the only code that ships)
  __init__.py       # SMB3World: items, locations, regions, rules
  Items.py Locations.py Regions.py Rules.py Options.py
  Client.py         # BizHawk client: reads SMB3 RAM, sends checks, grants items
  archipelago.json  # apworld manifest
  test/             # WorldTestBase tests
DESIGN.md           # full design + RAM research
NEXT_STEPS.md       # roadmap / milestone brief
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

The client (`Client.py`) attaches to a **vanilla** SMB3 US (PRG0) ROM in BizHawk via
the generic Lua connector — there is no ROM patch yet. BizHawk needs the
**Lua+LuaInterface** core (NLua fails). Load the connector from your own Archipelago's
`data/lua/connector_bizhawk_generic.lua` (it depends on sibling files). Client log
output appears in the **Archipelago BizHawk Client window**, not BizHawk's Lua console.

### Mapping airship checks (`/smb3_debug`)

The per-world airship-clear flag in `Map_Completions` is **positional** and must be
found empirically (the disassembly has no static flag). In the client, run
`/smb3_debug on` to enable verbose logging, beat an airship live (no save states —
they cause bulk RAM changes that look like many clears at once), and read the logged
`Map_Completions[$7Dxx] bit N` that flips at that moment. Record it as `ram_addr` /
`ram_bit` for that world in `Locations.py`.

## Pull requests

1. Fork and branch from `main`.
2. Keep changes focused; match the surrounding style.
3. Run the test suite (above) — `WorldTestBase` must stay green.
4. Don't commit the Archipelago clone, the disassembly, ROMs, `.apworld` builds, or
   any local venv (all gitignored).
5. Note any new RAM addresses with a source reference (the disassembly file:line).

Questions or design discussion: open an issue. See `DESIGN.md` first — it likely
already covers the area.
