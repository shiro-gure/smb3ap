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
# ram_addr/ram_bit are TODO: fill in from the discovery pass (see README.md).
location_table: Dict[str, LocationData] = {
    f"World {n} Airship - Boss Defeated": LocationData(n)
    for n in range(1, 8)
}

# Name of the Bowser's Castle victory location (event; code=None, no id).
BOWSERS_CASTLE = "Bowser's Castle"
