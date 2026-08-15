from typing import Dict, List, NamedTuple, Optional

from BaseClasses import ItemClassification

from .Locations import access_item_codes

filler = ItemClassification.filler
progression = ItemClassification.progression


class ItemData(NamedTuple):
    code: Optional[int]
    classification: ItemClassification


# Local item ids (offsets from base_id, applied in __init__.py). These ids are
# part of the wire format / spoiler log and MUST stay stable once shipped.
#
# `Victory` is intentionally NOT in this table: it is an event item with code=None,
# created inline and placed as a locked item on the Bowser's Castle location.
item_table: Dict[str, ItemData] = {
    "Extra Life":     ItemData(1, filler),
    "Super Mushroom": ItemData(2, filler),
    "Fire Flower":    ItemData(3, filler),
    "Super Leaf":     ItemData(4, filler),
}

# Level Access items (the level_access option) — one progression item per gated panel,
# gating ENTRY to that panel (levels + toad houses + fortress panels; see Locations.py).
# Their ids are ALWAYS defined (item_name_to_id must be static/complete for the world),
# but they're only created into the pool when level_access is on (see __init__.py).
for _name, _code in access_item_codes.items():
    item_table[_name] = ItemData(_code, progression)

# Pool of names eligible for random filler fill (model A: the filler-classified ones;
# Access items are progression and are added explicitly, not as random filler).
filler_item_names: List[str] = [
    name for name, data in item_table.items() if data.classification == filler
]
