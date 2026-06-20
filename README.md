# Super Mario Bros. 3 — Archipelago APWorld

An [Archipelago](https://archipelago.gg) (AP) APWorld for **Super Mario Bros. 3
(NES, USA PRG1 / Rev A)**, letting SMB3 participate in an AP multiworld: in-game events
become *locations* that hand items to other players.

> **Status: early client-only proof-of-concept.** It generates valid seeds and a
> BizHawk client reads a vanilla ROM's RAM to detect progress and grant items. There is
> no ROM patch yet. See [`DESIGN.md`](DESIGN.md) for the architecture and roadmap.

## What works today

- Generates a solo/multiworld seed with 7 airship-boss locations (Worlds 1–7) and a
  Bowser's Castle victory condition.
- A BizHawk client (`worlds/smb3/Client.py`) connects to a vanilla **`Super Mario
  Bros. 3 (U) (PRG1) [!]`** ROM, sends each World N airship check as you clear it, the
  victory check on beating Bowser, and grants received items as extra lives.
- Airship clears are detected via the king's-room cinematic flag (no per-airship
  completion flag exists in the game); see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
  detection details.

## Layout

| Path | What |
|---|---|
| `worlds/smb3/` | the APWorld (the code that ships as a `.apworld`) |
| `DESIGN.md` | architecture, RAM research + roadmap |
| `CONTRIBUTING.md` | dev setup, building/testing, and how airship detection works |

The Archipelago framework and the SMB3 disassembly are reference-only and not included
(gitignored).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, the test harness, building the
`.apworld`, and how airship detection works. You'll need your own legally obtained
SMB3 (U) (PRG1) ROM — none is distributed here.
