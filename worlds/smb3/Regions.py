from typing import Dict, List, NamedTuple, Optional

from .Locations import (
    BOWSERS_CASTLE, airship_location_name, fortress_location_names,
)


class RegionData(NamedTuple):
    # Region this connects from (None = connects from Menu). SMB3 worlds are
    # reached in sequence, so the map is a simple chain (DESIGN.md §3.4).
    connects_from: Optional[str]
    # Real (id-bearing) location names that live in this region.
    locations: List[str]


# Menu -> World 1 -> ... -> World 8. Each world region holds that world's fortress
# locations (Boom Boom). Worlds 1-7 also hold their airship check; World 8 holds the
# Bowser's Castle victory event (placed as a locked item) instead of an airship.
region_table: Dict[str, RegionData] = {}
for _n in range(1, 9):
    _locs: List[str] = list(fortress_location_names(_n))
    if _n <= 7:
        _locs.append(airship_location_name(_n))
    else:
        _locs.append(BOWSERS_CASTLE)
    region_table[f"World {_n}"] = RegionData(
        connects_from=None if _n == 1 else f"World {_n - 1}",
        locations=_locs,
    )
