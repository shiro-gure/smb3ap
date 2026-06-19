from typing import Dict

from BaseClasses import Item, ItemClassification, Location, MultiWorld, Region, Tutorial
from worlds.AutoWorld import World, WebWorld

from .Items import filler_item_names, item_table
from .Locations import BOWSERS_CASTLE, location_table
from .Options import SMB3Options
from .Regions import region_table
from .Rules import set_rules

# Arbitrary unused id base for SMB3. Item/location codes in Items.py / Locations.py
# are offsets from this; the absolute ids must stay stable once shipped.
BASE_ID = 7700000


class SMB3Item(Item):
    game = "Super Mario Bros. 3"


class SMB3Location(Location):
    game = "Super Mario Bros. 3"


class SMB3Web(WebWorld):
    theme = "grass"
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up Super Mario Bros. 3 for Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Shiro"],
    )]


class SMB3World(World):
    """
    Super Mario Bros. 3 for the NES. Mario chases Bowser across eight worlds,
    defeating the seven Koopalings aboard their airships along the way.
    """

    game = "Super Mario Bros. 3"
    options_dataclass = SMB3Options
    options: SMB3Options
    web = SMB3Web()
    topology_present = True

    item_name_to_id = {name: BASE_ID + data.code for name, data in item_table.items()}
    location_name_to_id = {name: BASE_ID + data.code for name, data in location_table.items()}

    def create_item(self, name: str) -> SMB3Item:
        data = item_table[name]
        return SMB3Item(name, data.classification, BASE_ID + data.code, self.player)

    def create_event(self, name: str) -> SMB3Item:
        return SMB3Item(name, ItemClassification.progression, None, self.player)

    def get_filler_item_name(self) -> str:
        return self.random.choice(filler_item_names)

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)

        for name, data in region_table.items():
            region = Region(name, self.player, self.multiworld)
            region.add_locations(
                {loc: self.location_name_to_id.get(loc) for loc in data.locations},
                SMB3Location,
            )
            self.multiworld.regions.append(region)

        for name, data in region_table.items():
            source = menu if data.connects_from is None else self.get_region(data.connects_from)
            source.connect(self.get_region(name))

        # Victory: beating Bowser's Castle. Locked event, excluded from the pool.
        victory = self.get_location(BOWSERS_CASTLE)
        victory.place_locked_item(self.create_event("Victory"))

    def create_items(self) -> None:
        # Model A: one filler item per real (id-bearing) location. The Victory
        # event is a locked item, so it is not counted here — pool == 7 locations.
        real_location_count = len(location_table)
        self.multiworld.itempool += [
            self.create_item(self.get_filler_item_name())
            for _ in range(real_location_count)
        ]

    set_rules = set_rules


# Import the BizHawk client so it registers itself. Done at the bottom so that
# BASE_ID / SMB3World are already defined when Client.py imports from this module
# (avoids a circular import). See worlds/_bizhawk/README.md.
from .Client import SMB3Client  # noqa: E402, F401
