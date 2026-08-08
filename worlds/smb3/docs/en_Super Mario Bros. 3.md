# Super Mario Bros. 3

## Where is the options page?

The [player options page for this game](../player-options) contains all the options you need to configure and export a
config file.

## What does randomization do to this game?

This is an early implementation. Right now SMB3 participates in a multiworld as a **source of location checks**:
clearing the seven airship bosses (the Koopalings) and the fortresses across Worlds 1–8 sends checks to the
multiworld, and the goal is to beat Bowser's Castle. SMB3 itself receives only filler items (extra lives, power-ups) —
no SMB3 progression is gated yet. Larger randomization (a World-9 hub with free travel, per-level checks, and
world/level/boss shuffles) is in progress; see the project design notes.

## What Super Mario Bros. 3 items can appear in other players' worlds?

The location checks (airship and fortress clears) hold items for the multiworld, which may belong to any player. SMB3's
own item pool is currently filler:

- Extra Life
- Super Mushroom
- Fire Flower
- Super Leaf

## What is considered a location check in Super Mario Bros. 3?

- Defeating a Koopaling aboard a World 1–7 **airship**.
- Clearing a **fortress** — by beating Boom Boom **or** by taking a secret/alternate exit (both count).
- With the **Level Checks** option on: clearing **every individual level** (1-1, 1-2, …) and every
  **Toad House** is also a check (a 100%-style location set). Off by default.

Beating Bowser's Castle is the victory condition, not a check. The Level Checks option only *adds*
locations; it does not change the win condition.

## When the player receives an item, what happens?

Received filler items are applied to the game's RAM as you play (e.g. extra lives are added to your life count). There
is no on-screen item message yet.

## What is the Hub World option?

With **Hub World** on, a ROM hack starts you in **World 9 (the Warp Zone)** as a travel hub instead of
World 1. (This first version lands you cleanly in World 9; full free travel — a panel to every world and
returning to the hub after beating one — arrives in a follow-up.) Off by default; requires the patched
ROM (the `.apsmb3` carries it). Note: currently, on each warp the in-game "cleared panel" checkmarks
reset — your Archipelago checks are unaffected (the server remembers them).

## What is the checkmark on the map?

When you clear a level or fortress, its overworld panel is marked with a **checkmark** (✓) — a small cosmetic ROM patch
replacing the vanilla "M"/"L" completion glyph, so cleared panels are easy to spot at a glance.

## Which ROM do I need?

`Super Mario Bros. 3 (USA) (Rev 1)` — the **PRG1 / Rev A** revision. This is the revision the disassembly and the
patch target; a PRG0 ROM will be rejected during generation. No ROM is distributed — supply your own legally obtained
copy.
