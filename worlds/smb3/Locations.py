from typing import Dict, List, NamedTuple, Optional

# Single source of truth for the SMB3 id space. Item codes (Items.py) and location
# codes (below) are offsets from this; the absolute ids are part of the wire format
# / spoiler log and MUST stay stable once shipped.
BASE_ID = 7700000


class LocationData(NamedTuple):
    code: Optional[int]


# --- Airships (Worlds 1-7) ---
# The 7 airship-boss-defeat locations. World 8 has no Koopaling airship boss — its
# climax is Bowser's Castle, which is the victory condition (an event location,
# defined in Regions.py), not a check.
#
# The airship code IS the world number (1-7); the client detects the clear via the
# Koopaling boss fight (no Map_Completions bit exists; see Client.py).
AIRSHIP_WORLDS = range(1, 8)


def airship_location_name(world: int) -> str:
    return f"World {world} Airship - Boss Defeated"


# --- Fortresses ---
# Per-world fortress counts (confirmed against the real game; W5's tower is NOT a
# fort). Easy to correct here if in-game testing shows a world differs.
FORTRESS_COUNTS: Dict[int, int] = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 2, 8: 1,
}

# Fortress location codes occupy a separate range so airship codes (1-7) never
# collide. code = FORTRESS_CODE_BASE + world*10 + index (index 1..N), leaving room
# for up to 9 fortresses per world.
FORTRESS_CODE_BASE = 100


def fortress_location_name(world: int, index: int) -> str:
    """index is 1-based within the world. Path-neutral: a fortress can be cleared
    by beating Boom Boom OR via a secret/alternate exit."""
    return f"World {world} Fortress {index} - Cleared"


def fortress_code(world: int, index: int) -> int:
    return FORTRESS_CODE_BASE + world * 10 + index


def fortress_location_names(world: int) -> List[str]:
    """Ordered fortress location names for a world (empty if it has none)."""
    return [fortress_location_name(world, i)
            for i in range(1, FORTRESS_COUNTS.get(world, 0) + 1)]


# Name of the Bowser's Castle victory location (event; code=None, no id).
BOWSERS_CASTLE = "Bowser's Castle"


# --- Levels & Toad Houses (the "Level Checks" option; see panels.py) ---
# panels.py is GENERATED from the disassembly (patch/gen_panels.py): the completable
# overworld panels keyed by (world, byte_offset, bit_mask) — the exact identity the
# game marks on completion. Levels + toad houses only; fortresses stay on their own
# count-based path (FORTRESS_COUNTS) and are excluded from panels.py (see BUG-002).
from .panels import PANELS  # noqa: E402

# Separate code ranges so nothing collides with airships (1-7) or fortresses
# (100-189). Codes are derived from the stable (world, offset, bit) key, so a level's
# id never shifts as long as the panel table is stable.
LEVEL_CODE_BASE = 10000       # levels:      10000 + world*256 + offset  (+ bit disambig)
TOADHOUSE_CODE_BASE = 20000   # toad houses: 20000 + world*256 + offset


def _panel_code(base: int, world: int, offset: int, bit: int) -> int:
    # offset is 0..0x3F, bit is one of 8 masks -> a small stable per-world index.
    bit_index = {0x80: 0, 0x40: 1, 0x20: 2, 0x10: 3,
                 0x08: 4, 0x04: 5, 0x02: 6, 0x01: 7}[bit]
    return base + world * 512 + offset * 8 + bit_index


def level_location_name(world: int, level_name: str) -> str:
    return f"World {world} Level {level_name}"


# Ordered lists of level / toad-house locations, built from the generated table.
# (kind, name) where kind in {'level','toad_house'}.
_level_locations: List[str] = []
_toadhouse_locations: List[str] = []
_panel_codes: Dict[str, int] = {}
for (_w, _off, _bit), (_kind, _pname) in sorted(PANELS.items()):
    if _kind == "level":
        _loc = level_location_name(_w, _pname)
        _level_locations.append(_loc)
        _panel_codes[_loc] = _panel_code(LEVEL_CODE_BASE, _w, _off, _bit)
    elif _kind == "toad_house":
        _loc = _pname  # already "World N Toad House K"
        _toadhouse_locations.append(_loc)
        _panel_codes[_loc] = _panel_code(TOADHOUSE_CODE_BASE, _w, _off, _bit)


def level_check_location_names() -> List[str]:
    """All optional 'Level Checks' locations (levels + toad houses), in order.
    Only placed into regions when the level_checks option is on."""
    return _level_locations + _toadhouse_locations


# level-check locations grouped by world (for placing into the World N regions).
_level_checks_by_world: Dict[int, List[str]] = {}
for (_w, _off, _bit), (_kind, _pname) in sorted(PANELS.items()):
    _loc = level_location_name(_w, _pname) if _kind == "level" else _pname
    _level_checks_by_world.setdefault(_w, []).append(_loc)


def level_check_locations_for_world(world: int) -> List[str]:
    """The optional level/toad-house location names in a given world."""
    return _level_checks_by_world.get(world, [])


# --- The location table (name -> LocationData) and the id lookup ---
location_table: Dict[str, LocationData] = {}
for _w in AIRSHIP_WORLDS:
    location_table[airship_location_name(_w)] = LocationData(_w)
for _w, _count in FORTRESS_COUNTS.items():
    for _i in range(1, _count + 1):
        location_table[fortress_location_name(_w, _i)] = LocationData(fortress_code(_w, _i))
# Level + toad-house locations. Their ids are ALWAYS defined (location_name_to_id
# must be static/complete for the world), but they're only PLACED into regions when
# the level_checks option is on (see __init__.create_regions).
for _loc, _code in _panel_codes.items():
    location_table[_loc] = LocationData(_code)

# The single name -> absolute id map everyone imports (mirrors mm2's
# lookup_location_to_id). BASE_ID is applied exactly once, here.
location_name_to_id: Dict[str, int] = {
    name: BASE_ID + data.code for name, data in location_table.items()
}


# --- Pure id helpers (used by both __init__.py and the client) ---

def airship_location_id(world: int) -> Optional[int]:
    """AP location id for a world's airship, or None if that world has none."""
    return location_name_to_id.get(airship_location_name(world))


def fortress_location_ids(world: int) -> List[int]:
    """Ordered AP location ids for a world's fortresses (empty if none)."""
    return [location_name_to_id[name] for name in fortress_location_names(world)]
