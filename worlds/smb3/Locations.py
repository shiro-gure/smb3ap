from typing import Dict, NamedTuple, Optional


class LocationData(NamedTuple):
    code: Optional[int]
    # Persistent-RAM detection hooks for the BizHawk client (DESIGN.md §5.1).
    # The client watches Map_Completions ($7D00-$7D3F); when (ram_addr, ram_bit)
    # transitions 0->1, that airship's boss is cleared and the check fires.
    #
    # These stay None until the per-airship bit is observed empirically: run the
    # client in discovery mode (SMB3Client.discovery = True, the default), beat
    # each airship in BizHawk, and read the logged "byte_offset=.., mask=.." line.
    # Then set ram_addr = 0x7D00 + byte_offset and ram_bit = mask here.
    ram_addr: Optional[int] = None  # absolute address in Map_Completions ($7D00+)
    ram_bit: Optional[int] = None   # bit mask within that byte


# The 7 airship-boss-defeat locations (Worlds 1-7). World 8 has no Koopaling
# airship boss — its climax is Bowser's Castle, which is the victory condition
# (an event location, defined in Regions.py), not a check.
#
# Codes are offsets from base_id (applied in __init__.py) and must stay stable.
# ram_addr/ram_bit come from the discovery pass (see README.md). World 1 was
# observed: clearing the W1 airship sets Map_Completions[$7D08] bit 0 ($01).
# Worlds 2-7 are still TODO — fill in as each airship is observed.
location_table: Dict[str, LocationData] = {
    "World 1 Airship - Boss Defeated": LocationData(1, ram_addr=0x7D08, ram_bit=0x01),
    "World 2 Airship - Boss Defeated": LocationData(2),
    "World 3 Airship - Boss Defeated": LocationData(3),
    "World 4 Airship - Boss Defeated": LocationData(4),
    "World 5 Airship - Boss Defeated": LocationData(5),
    "World 6 Airship - Boss Defeated": LocationData(6),
    "World 7 Airship - Boss Defeated": LocationData(7),
}

# Name of the Bowser's Castle victory location (event; code=None, no id).
BOWSERS_CASTLE = "Bowser's Castle"
