# SMB3 APWorld — source

This is the canonical, git-tracked source for the Super Mario Bros. 3 Archipelago
APWorld. It is **symlinked** into the Archipelago clone for development and testing:

```
Archipelago/worlds/smb3 -> ../../worlds/smb3   (symlink)
```

## Why it lives here and not in `Archipelago/worlds/smb3/`

`Archipelago/` is a cloned upstream repo with its own embedded `.git/`. Git refuses
to track files inside another repository's working tree, so the APWorld source can't
be committed from inside the clone. Keeping the source at the repo root and symlinking
it in gives one source of truth that is normally trackable, while Archipelago still
finds the world at the path it expects.

If the symlink is missing (e.g. fresh checkout), recreate it from the repo root:

```sh
ln -s ../../worlds/smb3 Archipelago/worlds/smb3
```

## Running the tests

Archipelago's deps aren't installed system-wide, and the default `python3` shim is
3.14 (AP targets 3.12). Set up a throwaway venv inside the (gitignored) clone:

```sh
cd Archipelago
python3.12 -m venv .venv-test
.venv-test/bin/pip install PyYAML schema jellyfish orjson bsdiff4 \
    typing_extensions platformdirs websockets colorama pathspec
PYTHONPATH=. .venv-test/bin/python -m unittest worlds.smb3.test.test_basic -v
```

The "Could not load world …" / `ModuleNotFoundError` lines for *other* worlds are
unrelated upstream worlds missing optional deps; they don't affect smb3.

## Scope (current): client-only POC

7 airship-boss locations (Worlds 1–7), victory = Bowser's Castle, item model A
(filler-only). **No ROM patch / no ASM** — the BizHawk client (`Client.py`) reads
*vanilla* SMB3 US (PRG1) RAM to detect progress and writes items into RAM. The ASM
base-patch track is deferred (see `DESIGN.md` §4/§8 and the plan notes).

### Playing it

1. **Generate** a seed that includes a "Super Mario Bros. 3" slot, and host it
   (local AP server is fine).
2. **BizHawk** (≥ 2.3.1): open your **vanilla SMB3 US (PRG1)** ROM — `Super Mario
   Bros. 3 (U) (PRG1) [!]` (file md5 `86d1982f…`, headerless CRC32 `2e6301ed`).
   Load the generic connector `connector_bizhawk_generic.lua` (ships with
   Archipelago) via the Lua console.
3. **Client:** launch the BizHawk client from the AP launcher and connect to the
   server with your slot name. It identifies the ROM by an internal signature.
4. Beating each **World N airship** sends that location check; beating **Bowser's
   Castle** sends victory. Received items currently grant **+1 life** each (POC).

### How airship detection works

There is no per-airship completion flag in SMB3 — beating an airship just advances
`World_Num` ($0727), the current-world index (`INC World_Num`,
`disasm/PRG/prg030.asm:2742`). The client watches it and sends the "World N Airship"
check once `World_Num >= N` (worlds 1–7). Run `/smb3_debug on` in the client to log
`World_Num` each pass. Exact for linear play; warp-whistle skips would mark skipped
airships as cleared (POC limitation).
