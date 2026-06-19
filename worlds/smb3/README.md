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
*vanilla* SMB3 US (PRG0) RAM to detect progress and writes items into RAM. The ASM
base-patch track is deferred (see `DESIGN.md` §4/§8 and the plan notes).

### Playing it

1. **Generate** a seed that includes a "Super Mario Bros. 3" slot, and host it
   (local AP server is fine).
2. **BizHawk** (≥ 2.3.1): open your **vanilla SMB3 US (PRG0)** ROM — `Super Mario
   Bros. 3 (U) (PRG0) [!]` (file md5 `bb5c4b6d…`, headerless CRC32 `a0b0b742`).
   Load the generic connector `connector_bizhawk_generic.lua` (ships with
   Archipelago) via the Lua console.
3. **Client:** launch the BizHawk client from the AP launcher and connect to the
   server with your slot name. It identifies the ROM by PRG hash and attaches.
4. Beating **Bowser's Castle** sends victory. Received items currently grant **+1
   life** each (POC item handling).

### Airship-check discovery (one-time)

The exact `Map_Completions` bit per airship isn't a static constant — the game
computes it from the panel's map position. `SMB3Client.discovery` is `True` by
default: when you beat an airship boss, the client logs a line like

```
SMB3 discovery: Map_Completions[$7D0A] bit 6 set (byte_offset=10, mask=$40)
```

Record that and set `ram_addr=0x7D0A`, `ram_bit=0x40` for that world in
`Locations.py`. Once filled in, beating that airship will fire its AP check. (World
1 alone is enough to prove the loop; W2–7 follow the same procedure.)
