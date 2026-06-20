from typing import Dict, List, NamedTuple, Optional


class LocationData(NamedTuple):
    code: Optional[int]


# --- Airships (Worlds 1-7) ---
# The 7 airship-boss-defeat locations. World 8 has no Koopaling airship boss — its
# climax is Bowser's Castle, which is the victory condition (an event location,
# defined in Regions.py), not a check.
#
# Codes are offsets from base_id (applied in __init__.py) and must stay stable.
# The airship code also IS the world number (1-7) — the client detects the clear
# via the Koopaling boss fight (no Map_Completions bit exists; see Client.py).
AIRSHIP_WORLDS = range(1, 8)


def airship_location_name(world: int) -> str:
    return f"World {world} Airship - Boss Defeated"


# --- Fortresses (Boom Boom) ---
# Per-world fortress counts (user-confirmed against the real game; W5's tower is
# NOT a fort). Easy to correct here if in-game testing shows a world differs.
FORTRESS_COUNTS: Dict[int, int] = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 2, 8: 1,
}

# Fortress location codes occupy a separate, stable id range so airship codes
# (1-7) never collide. code = FORTRESS_CODE_BASE + world*10 + index (index 1..N),
# leaving room for up to 9 fortresses per world.
FORTRESS_CODE_BASE = 100


def fortress_location_name(world: int, index: int) -> str:
    """index is 1-based within the world."""
    return f"World {world} Fortress {index} - Boom Boom Defeated"


def fortress_code(world: int, index: int) -> int:
    return FORTRESS_CODE_BASE + world * 10 + index


# --- The location table (name -> LocationData(code)) ---
location_table: Dict[str, LocationData] = {}
for _w in AIRSHIP_WORLDS:
    location_table[airship_location_name(_w)] = LocationData(_w)
for _w, _count in FORTRESS_COUNTS.items():
    for _i in range(1, _count + 1):
        location_table[fortress_location_name(_w, _i)] = LocationData(fortress_code(_w, _i))


def fortress_location_names(world: int) -> List[str]:
    """Ordered fortress location names for a world (empty if it has none)."""
    return [fortress_location_name(world, i)
            for i in range(1, FORTRESS_COUNTS.get(world, 0) + 1)]


# Name of the Bowser's Castle victory location (event; code=None, no id).
BOWSERS_CASTLE = "Bowser's Castle"
