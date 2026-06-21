from BaseClasses import Item, ItemClassification, Location, Region
from worlds.AutoWorld import World, WebWorld

from .Items import filler_item_names, item_table
from .Locations import (
    BASE_ID, BOWSERS_CASTLE, location_name_to_id, location_table,
)
from .Options import SMB3Options
from .Regions import region_table
from .Rules import set_rules


class SMB3Item(Item):
    game = "Super Mario Bros. 3"


class SMB3Location(Location):
    game = "Super Mario Bros. 3"


class SMB3Web(WebWorld):
    theme = "grass"
    # No tutorials override yet — the setup/game-info docs aren't written.
    # (adding games.md requires a setup doc + game_info doc before upstream
    # submission; tracked in NEXT_STEPS.md.) Leaving the default empty list here
    # avoids a dangling reference to a non-existent setup_en.md.


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
    location_name_to_id = location_name_to_id

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
        # event is a locked item placed separately, so it isn't counted here.
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
