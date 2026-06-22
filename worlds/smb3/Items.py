from typing import Dict, List, NamedTuple, Optional

from BaseClasses import ItemClassification

filler = ItemClassification.filler


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

# Pool of names eligible for random filler fill (model A: all of them).
filler_item_names: List[str] = [
    name for name, data in item_table.items() if data.classification == filler
]
