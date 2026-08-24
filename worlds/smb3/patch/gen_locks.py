#!/usr/bin/env python3
"""Derive SMB3 overworld PATH-LOCK topology: which level panels sit behind a fortress
lock, so the AP logic can require that fortress cleared before those panels.

Background (from the disasm):
  - The overworld is a grid of tiles; the player only walks on path/bridge tiles
    (Map_Object_Valid_* whitelists, prg010.asm:3342-3353). A "lock" is just a
    non-walkable tile ($54/$56/$E4 mini-fortress locks; a fortress panel $67/$EB is
    itself non-walkable) sitting on the path, so it blocks passage.
  - Beating a fortress sets a Map_Completions bit at the LOCK's grid cell, and the
    map reload swaps that lock tile to a walkable path (Map_Removable_Tiles ->
    Map_RemoveTo_Tiles, prg012.asm:135-143). So the fortress opens a specific lock cell.
  - The fortress<->lock-cell pairing is explicit data: FortressFX_MapLocation /
    FortressFX_MapLocationRow (prg010.asm:1593-1600), selected per world by
    FortressFX_Wx / FortressFXBase_ByWorld (prg010.asm:1608-1627).

We reconstruct "panel behind lock" with a flood-fill: build the walkable graph from
WorldNL.asm using the valid-tile adjacency, treat each fortress's lock cell as a wall,
and see which panels become unreachable from the world's entry when that lock is closed.

Output: a committed `worlds/smb3/locks.py` mapping each gated panel's base location
name -> the list of fortress base location names that must be cleared to reach it.
Regenerate with this script. NOT shipped in the .apworld.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DISASM = os.path.normpath(os.path.join(HERE, "..", "..", "..", "disasm"))
PRG = os.path.join(DISASM, "PRG")
MAPS = os.path.join(PRG, "maps")
OUT = os.path.normpath(os.path.join(HERE, "..", "locks.py"))

# --- tile semantics (from disasm/smb3.asm:3585-3637 + prg010.asm valid lists) --------
# Walkable tiles. The maps use PATH VARIANTS $44-$4A (the base $45 HORZPATH / $46 VERTPATH
# plus decorated variants that render/behave as path), bridges, water paths, sky paths,
# hand trap, and PIPE ($BC, walkable via our hub patch). A CLEARED fortress ($60/$E3
# rubble) is walkable too. We treat the whole $44-$4A path family as walkable because the
# game walks them all (the 9-entry valid-list is normalized at map-load).
WALKABLE = {
    0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A,  # path variants (HORZ/VERT + decorated)
    0xB1, 0xB2,  # DRAWBRIDGEV/H (treated open — W3 bridges are a separate counter; for
                 # *lock* topology we don't want to over-gate on the bridge counter)
    0xB3,  # BRIDGE
    0xAA, 0xAB, 0xAC, 0xB0, 0xB7, 0xB8, 0xB9, 0xBA,  # water paths
    0xDA, 0xDB,  # SKY horz/vert path (World 5 + our hub links)
    0xE6,  # HANDTRAP (World 8 — walkable but moving; passable for reachability)
    0xBC,  # PIPE
    0x60, 0xE3,  # FORTRUBBLE / ALTRUBBLE (a CLEARED fortress is walkable rubble)
    0x9D,  # RIVERVERT (gets bridged; treat as traversable so we don't over-gate on it)
}
# Panel / stop tiles that sit ON the path line and are TRAVERSABLE (you walk onto them
# and continue past): level panels $03-$0F, Toad House $50, START $E5, SPADE bonus $E8.
STOP_TILES = set(range(0x03, 0x10)) | {0x50, 0xE5, 0xE8}
# Lock tiles: block passage until their fortress is cleared. A fortress panel itself
# ($67/$EB) is non-walkable while intact; clearing turns it to rubble ($60/$E3).
LOCK_TILES = {0x54, 0x56, 0xE4}          # mini-fortress locks
FORT_TILES = {0x67, 0xEB}                # fortress panels (also block until cleared)

# Map_CompleteY (prg011.asm:4573): World_Map_Y high-nibble -> row index 0..6, else 7.
COMPLETE_Y = (0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80)


def _row_from_rowtype(rowtype_byte: int) -> int:
    """W*_ByRowType high nibble ($x0 Y value) -> grid row 0..8."""
    ymap = (rowtype_byte >> 4) << 4
    # Grid rows are (Y - $20) >> 4 == index into COMPLETE_Y for the top 7; rows 7/8 use
    # $90/$A0 (fall-through). Map directly: $20->0 ... $A0->8.
    return max(0, min(8, (ymap - 0x20) >> 4))


# --- parsing helpers -----------------------------------------------------------------

def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _byte_rows(text: str) -> list:
    """All `.byte $xx, ...` numeric rows in order (used for the map grid)."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*\.byte\s+(.*)", line)
        if not m:
            continue
        toks = [t.strip() for t in m.group(1).split(",")]
        vals = []
        ok = True
        for t in toks:
            t = t.split(";")[0].strip()
            if not t:
                continue
            if re.fullmatch(r"\$[0-9A-Fa-f]{1,2}", t):
                vals.append(int(t[1:], 16))
            else:
                ok = False
                break
        if ok and vals:
            rows.append(vals)
    return rows


def parse_grid(world: int) -> list:
    """WorldNL.asm -> list of screens, each a 9-row x 16-col list of tile bytes.
    The file is screens of 9 rows (16 bytes each), terminated by a lone $FF."""
    text = _read(os.path.join(MAPS, f"World{world}L.asm"))
    rows = [r for r in _byte_rows(text) if not (len(r) == 1 and r[0] == 0xFF)]
    # each real row is 16 bytes; group into screens of 9 rows.
    grid_rows = [r for r in rows if len(r) == 16]
    screens = [grid_rows[i:i + 9] for i in range(0, len(grid_rows), 9)]
    return screens


# --- FortressFX table decode (fortress -> lock cell it opens) -------------------------

def _flat_bytes_after(label: str, text: str, count: int) -> list:
    """Read `count` byte values following a `label:` .byte line (single line)."""
    m = re.search(rf"{re.escape(label)}:\s*\.byte\s+(.*)", text)
    if not m:
        raise SystemExit(f"missing {label}")
    toks = [t.split(";")[0].strip() for t in m.group(1).split(",")]
    vals = [int(t[1:], 16) for t in toks if re.fullmatch(r"\$[0-9A-Fa-f]{1,2}", t)]
    return vals[:count]


def parse_fortress_fx() -> dict:
    """Return world(1-8) -> ordered list of lock cells (screen, col, row), one per
    fortress FX slot for that world, decoded from FortressFX_* (prg010.asm)."""
    text = _read(os.path.join(PRG, "prg010.asm"))
    # 17 FX slots (0..$10).
    map_loc = _flat_bytes_after("FortressFX_MapLocation", text, 17)
    map_row = _flat_bytes_after("FortressFX_MapLocationRow", text, 17)
    # Per-world slot lists.
    world_slots = {}
    for w in range(1, 9):
        m = re.search(rf"FortressFX_W{w}:\s*\.byte\s+(.*)", text)
        toks = [t.split(";")[0].strip() for t in m.group(1).split(",")]
        slots = [int(t[1:], 16) for t in toks if re.fullmatch(r"\$[0-9A-Fa-f]{1,2}", t)]
        world_slots[w] = slots
    out = {}
    for w, slots in world_slots.items():
        cells = []
        for s in slots:
            loc = map_loc[s]
            screen = loc & 0x0F
            col = (loc >> 4) & 0x0F
            row = _row_from_rowtype(map_row[s])
            cells.append((screen, col, row))
        out[w] = cells
    return out


# --- panel positions (reuse gen_panels parsing) --------------------------------------

sys.path.insert(0, HERE)
from gen_panels import _array_tokens, classify, row_to_bit  # noqa: E402

# The AP location naming (must match Locations.py exactly).
FORTRESS_COUNTS = {1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 2, 8: 1}


def level_loc_name(world: int, name: str) -> str:
    return f"World {world} Level {name}"


def fort_loc_name(world: int, index: int) -> str:
    return f"World {world} Fortress {index} - Cleared"


def parse_panels(world: int) -> list:
    """Return [(cell(screen,col,row), kind, base_location_name)] for the world's
    level/toad/fortress panels, matching gen_panels' classification + AP names."""
    text = _read(os.path.join(MAPS, f"World{world}S.asm"))
    rows = _array_tokens(text, f"W{world}_ByRowType", ".byte")
    cols = _array_tokens(text, f"W{world}_ByScrCol", ".byte")
    lays = _array_tokens(text, f"W{world}_LevelLayout", ".word")
    n = min(len(rows), len(cols), len(lays))
    out = []
    fort_seq = 0
    toad_seq = 0
    for i in range(n):
        got = classify(lays[i], world)
        if got is None:
            continue
        kind, name = got
        scrcol = int(cols[i].replace("$", ""), 16)
        screen = scrcol >> 4
        col = scrcol & 0x0F
        row = _row_from_rowtype(int(rows[i].replace("$", ""), 16))
        if kind == "fortress":
            fort_seq += 1
            base = fort_loc_name(world, fort_seq)
        elif kind == "toad_house":
            toad_seq += 1
            base = f"World {world} Toad House {toad_seq}"
        else:  # level
            base = level_loc_name(world, name)
        out.append(((screen, col, row), kind, base))
    return out


# --- flood-fill reachability with certain cells walled off ----------------------------

def _neighbors(cell, n_screens):
    """4-neighbours across the concatenated screens. Columns 0..15 within a screen;
    moving off the right edge of screen s enters screen s+1 col 0 (screens are laid
    left-to-right in play). Rows 0..8."""
    sc, col, row = cell
    res = []
    # left / right (may cross screen boundary)
    if col > 0:
        res.append((sc, col - 1, row))
    elif sc > 0:
        res.append((sc - 1, 15, row))
    if col < 15:
        res.append((sc, col + 1, row))
    elif sc < n_screens - 1:
        res.append((sc + 1, 0, row))
    # up / down (within a screen)
    if row > 0:
        res.append((sc, col, row - 1))
    if row < 8:
        res.append((sc, col, row + 1))
    return res


def _reachable(grid, start_cells, passable, walls):
    """BFS over cells; a cell is enterable if it's in `passable` and not in `walls`."""
    n = len(grid)
    seen = set()
    stack = [c for c in start_cells if c in passable and c not in walls]
    seen.update(stack)
    while stack:
        cur = stack.pop()
        for nb in _neighbors(cur, n):
            sc, col, row = nb
            if nb in seen:
                continue
            if nb in walls:
                continue
            if nb in passable:
                seen.add(nb)
                stack.append(nb)
    return seen


def _path_cells(grid) -> set:
    """All traversable cells: WALKABLE path tiles + STOP tiles (panels you walk onto and
    continue past). Fortress/lock tiles are excluded here and handled as toggleable walls."""
    cells = set()
    for sc in range(len(grid)):
        for row in range(9):
            for col in range(16):
                t = grid[sc][row][col]
                if t in WALKABLE or t in STOP_TILES:
                    cells.add((sc, col, row))
    return cells


def _panel_reachable(cell, reachable_paths, n_screens) -> bool:
    """A panel is reachable if any of its 4-neighbour cells is a reachable path cell.
    (You stand on a panel by stepping onto it from an adjacent path.)"""
    return any(nb in reachable_paths for nb in _neighbors(cell, n_screens))


def analyze_world(world: int) -> dict:
    """Return {panel_base_location -> [gating fortress base locations]} for the world.

    Model: movement graph = WALKABLE path cells only. A lock cell is a path cell that is
    BLOCKED until its fortress clears (removed from the graph). A panel is reachable iff
    adjacent to a reachable path cell. A panel is 'behind' fortress F iff it's unreachable
    with F's lock closed but reachable once opened."""
    grid = parse_grid(world)
    panels = parse_panels(world)
    fx_cells = parse_fortress_fx()[world][:FORTRESS_COUNTS.get(world, 0)]
    n = len(grid)

    # base_passable already includes path + stop (panel) tiles. Locks and intact fortress
    # cells are toggleable walls: opening a fortress removes its lock wall AND its own
    # fortress-panel wall (rubble becomes walkable).
    base_passable = _path_cells(grid)
    lock_cells = list(fx_cells)

    # Fortress panels in clear-order (sorted by cell = reading order ~ clear order).
    fort_panels = [(cell, base) for (cell, k, base) in panels if k == "fortress"]
    fort_panels.sort()
    fort_cells = {cell for (cell, _b) in fort_panels}

    # Start = world entry: X=$20 (col 2, screen 0), Y from Map_Y_Starts.
    y_starts = {1: 0x40, 2: 0xA0, 3: 0xA0, 4: 0x40, 5: 0x80, 6: 0x60, 7: 0x30, 8: 0x50}
    start_row = max(0, min(8, (y_starts[world] - 0x20) >> 4))
    start = (0, 2, start_row)
    starts = [start] + _neighbors(start, n)

    def reach(open_forts: set) -> set:
        """open_forts = set of fortress indices whose lock+panel are opened. An opened
        lock/fortress cell becomes a walkable path (its Map_RemoveTo tile), so we ADD it
        to the passable set (removing it from walls isn't enough — it wasn't a path tile)."""
        passable = set(base_passable)
        for i in open_forts:
            if i < len(lock_cells):
                passable.add(lock_cells[i])          # lock -> path
            if i < len(fort_panels):
                passable.add(fort_panels[i][0])      # fortress -> walkable rubble
        return _reachable(grid, starts, passable, set())

    n_forts = min(len(lock_cells), len(fort_panels))

    # A fortress's lock is "openable" once you can physically REACH it (a neighbour of its
    # lock cell or its own fortress panel is reachable given the currently-open set). Open
    # fortresses in dependency order (closure), recording each one's PREREQUISITE chain
    # (the fortresses that had to be open first). A panel behind a chain requires them all.
    fort_prereqs = [set() for _ in range(n_forts)]
    opened: set = set()
    changed = True
    while changed:
        changed = False
        cur_reach = reach(opened)
        for i in range(n_forts):
            if i in opened:
                continue
            targets = (_neighbors(lock_cells[i], n)
                       + _neighbors(fort_panels[i][0], n)
                       + [fort_panels[i][0]])
            if any(t in cur_reach for t in targets):
                fort_prereqs[i] = set(opened)  # everything open now was a prerequisite
                opened.add(i)
                changed = True

    # For each openable fortress, the panels it NEWLY reveals (vs. having only its
    # prereqs open) require that fortress AND its whole prerequisite chain.
    result = {}
    order = sorted(range(n_forts), key=lambda i: (len(fort_prereqs[i]), i))
    for i in order:
        if i not in opened:
            continue  # a fortress whose lock is never reachable (shouldn't happen)
        with_i = set(fort_prereqs[i]) | {i}
        newly = reach(with_i) - reach(set(fort_prereqs[i]))
        chain = sorted(with_i, key=lambda j: (len(fort_prereqs[j]), j))
        chain_names = [fort_panels[j][1] for j in chain]
        for (cell, kind, base) in panels:
            if kind == "fortress":
                continue
            if cell in newly:
                result.setdefault(base, [])
                for name in chain_names:
                    if name not in result[base]:
                        result[base].append(name)

    # Fortress -> fortress prerequisites (a fortress can sit behind another's lock, e.g.
    # 6-F2 behind 6-F1). Record each fortress's prereq fortresses so the logic requires
    # the upstream chain before that fortress can be beaten.
    for i in range(n_forts):
        prereqs = sorted(fort_prereqs[i], key=lambda j: (len(fort_prereqs[j]), j))
        if prereqs:
            fbase = fort_panels[i][1]
            result.setdefault(fbase, [])
            for j in prereqs:
                name = fort_panels[j][1]
                if name not in result[fbase]:
                    result[fbase].append(name)
    return result


def emit(all_locks: dict) -> None:
    lines = [
        '"""GENERATED by worlds/smb3/patch/gen_locks.py — DO NOT EDIT BY HAND.',
        "",
        "SMB3 overworld path-lock topology: each gated level/toad-house panel that sits",
        "behind one or more fortress locks -> the fortress clear(s) required to reach it.",
        "Derived by flood-filling WorldNL.asm with fortress lock cells (FortressFX_*)",
        "walled off. Used by Rules.py so level_access never routes progression behind an",
        'unreachable panel. Regenerate with gen_locks.py."""',
        "",
        "# base location name -> [required 'World N Fortress K - Cleared' events]",
        "PANEL_REQUIRES_FORTRESS = {",
    ]
    for base in sorted(all_locks):
        reqs = all_locks[base]
        if not reqs:
            continue
        reqs_str = ", ".join(repr(r) for r in reqs)
        lines.append(f"    {base!r}: [{reqs_str}],")
    lines.append("}")
    lines.append("")
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


# Worlds whose fortress locks genuinely DEAD-END the path (no alternate route), verified
# in-game. Only these are gated. The flood-fill also flags World 1/2 (vanilla fortress
# gates), but in practice those worlds are traversable, so we exclude them. Add a world
# here only after confirming in-game that a fortress there actually blocks progression.
GATED_WORLDS = {6}


def main() -> None:
    all_locks = {}
    for world in range(1, 9):
        w_locks = analyze_world(world)
        if world in GATED_WORLDS:
            all_locks.update(w_locks)
        status = "GATED" if world in GATED_WORLDS else "traversable (not gated)"
        print(f"World {world}: {len(w_locks)} candidate gated panels — {status}")
        if world in GATED_WORLDS:
            for base, reqs in sorted(w_locks.items()):
                print(f"    {base}  <-  {reqs}")
    emit(all_locks)
    print(f"\nwrote {OUT}: {len(all_locks)} gated panels "
          f"(worlds gated: {sorted(GATED_WORLDS)})")


if __name__ == "__main__":
    main()
