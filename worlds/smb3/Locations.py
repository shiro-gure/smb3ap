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


# --- The location table (name -> LocationData) and the id lookup ---
location_table: Dict[str, LocationData] = {}
for _w in AIRSHIP_WORLDS:
    location_table[airship_location_name(_w)] = LocationData(_w)
for _w, _count in FORTRESS_COUNTS.items():
    for _i in range(1, _count + 1):
        location_table[fortress_location_name(_w, _i)] = LocationData(fortress_code(_w, _i))

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
