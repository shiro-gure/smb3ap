from typing import Dict, List, NamedTuple, Optional

from .Locations import BOWSERS_CASTLE


class RegionData(NamedTuple):
    # Region this connects from (None = connects from Menu). SMB3 worlds are
    # reached in sequence, so the map is a simple chain (DESIGN.md §3.4).
    connects_from: Optional[str]
    # Real (id-bearing) location names that live in this region.
    locations: List[str]


# Menu -> World 1 -> ... -> World 8. Worlds 1-7 each hold their airship check;
# World 8 holds the Bowser's Castle victory event (placed as a locked item).
region_table: Dict[str, RegionData] = {}
for _n in range(1, 8):
    region_table[f"World {_n}"] = RegionData(
        connects_from=None if _n == 1 else f"World {_n - 1}",
        locations=[f"World {_n} Airship - Boss Defeated"],
    )
region_table["World 8"] = RegionData(
    connects_from="World 7",
    locations=[BOWSERS_CASTLE],
)
