from typing import Dict, NamedTuple, Optional


class LocationData(NamedTuple):
    code: Optional[int]


# The 7 airship-boss-defeat locations (Worlds 1-7). World 8 has no Koopaling
# airship boss — its climax is Bowser's Castle, which is the victory condition
# (an event location, defined in Regions.py), not a check.
#
# Codes are offsets from base_id (applied in __init__.py) and must stay stable.
# The code also IS the world number (1-7) — the client uses it to detect the
# clear: beating an airship has no Map_Completions bit (the airship's "complete"
# branch is dead code, disasm/PRG/prg011.asm:2010); the only persistent signal is
# World_Num ($0727) incrementing past that world. So "World N Airship" is checked
# when World_Num >= N. See Client.py.
location_table: Dict[str, LocationData] = {
    f"World {n} Airship - Boss Defeated": LocationData(n)
    for n in range(1, 8)
}

# Name of the Bowser's Castle victory location (event; code=None, no id).
BOWSERS_CASTLE = "Bowser's Castle"
