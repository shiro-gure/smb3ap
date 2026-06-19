# Super Mario Bros. 3 — Archipelago APWorld

An [Archipelago](https://archipelago.gg) (AP) APWorld for **Super Mario Bros. 3
(NES, USA PRG0)**, letting SMB3 participate in an AP multiworld: in-game events
become *locations* that hand items to other players.

> **Status: early client-only proof-of-concept.** It generates valid seeds and a
> BizHawk client reads a vanilla ROM's RAM to detect progress and grant items. There is
> no ROM patch yet, and only the World 1 airship check is mapped so far. See
> [`DESIGN.md`](DESIGN.md) for the architecture and [`NEXT_STEPS.md`](NEXT_STEPS.md) for
> the roadmap.

## What works today

- Generates a solo/multiworld seed with 7 airship-boss locations (Worlds 1–7) and a
  Bowser's Castle victory condition.
- A BizHawk client (`worlds/smb3/Client.py`) connects to a vanilla **`Super Mario
  Bros. 3 (U) (PRG0) [!]`** ROM, sends the victory check on beating Bowser, and grants
  received items as extra lives.
- World 1's airship check fires from a real RAM flag; Worlds 2–7 still need their flags
  mapped (see the discovery workflow in [`CONTRIBUTING.md`](CONTRIBUTING.md)).

## Layout

| Path | What |
|---|---|
| `worlds/smb3/` | the APWorld (the code that ships as a `.apworld`) |
| `DESIGN.md` | architecture + RAM research |
| `NEXT_STEPS.md` | roadmap / milestones |
| `CONTRIBUTING.md` | dev setup, building/testing, and how to add airship mappings |

The Archipelago framework and the SMB3 disassembly are reference-only and not included
(gitignored).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, the test harness, building the
`.apworld`, and the airship-check discovery process. You'll need your own legally
obtained SMB3 (U) (PRG0) ROM — none is distributed here.
