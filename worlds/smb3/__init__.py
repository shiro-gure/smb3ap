import os
from typing import ClassVar, Optional

import settings
from BaseClasses import Item, ItemClassification, Location, Region, Tutorial
from worlds.AutoWorld import World, WebWorld

from .Items import filler_item_names, item_table
from .Locations import (
    BASE_ID, BOWSERS_CASTLE, location_name_to_id, location_table,
)
from .Options import SMB3Options, smb3_option_groups
from .Presets import smb3_options_presets
from .Regions import region_table
from .Rom import PRG1_MD5, SMB3ProcedurePatch, patch_rom
from .Rules import set_rules


class SMB3Settings(settings.Group):
    class RomFile(settings.UserFilePath):
        """File name of the SMB3 (U) (PRG1) ROM."""
        description = "Super Mario Bros. 3 (USA) (PRG1) ROM File"
        copy_to: Optional[str] = "Super Mario Bros. 3 (USA) (Rev 1).nes"
        md5s = [PRG1_MD5]

    rom_file: RomFile = RomFile(RomFile.copy_to)


class SMB3Item(Item):
    game = "Super Mario Bros. 3"


class SMB3Location(Location):
    game = "Super Mario Bros. 3"


class SMB3Web(WebWorld):
    theme = "grass"

    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up the Super Mario Bros. 3 randomizer connected to an "
        "Archipelago Multiworld.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Shiro"],
    )

    tutorials = [setup_en]
    option_groups = smb3_option_groups
    options_presets = smb3_options_presets


class SMB3World(World):
    """
    Super Mario Bros. 3 for the NES. Mario chases Bowser across eight worlds,
    defeating the seven Koopalings aboard their airships along the way.
    """

    game = "Super Mario Bros. 3"
    options_dataclass = SMB3Options
    options: SMB3Options
    settings: ClassVar[SMB3Settings]
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

    def generate_output(self, output_directory: str) -> None:
        # Emit an .apsmb3 patch (base patch = on-map checkmark; per-seed tokens
        # added in later PRs). Skipped gracefully when no base ROM is configured
        # (e.g. CI, or the patchless Any%/Vanilla flow) so generation still works.
        # We LOG the skip (instead of silently producing nothing) so a missing
        # rom_file is never a silent mystery — the patch just wouldn't appear.
        import logging
        logger = logging.getLogger("Super Mario Bros. 3")
        try:
            from .Rom import get_base_rom_path
            get_base_rom_path()
        except (FileNotFoundError, KeyError, ValueError) as exc:
            logger.info(
                "SMB3 (%s): no usable base ROM (%s). Skipping .apsmb3 patch — set "
                "host.yaml 'smb3_options: rom_file:' to your PRG1 ROM to get the "
                "patched (checkmark) ROM.", self.player_name, exc)
            return

        patch = SMB3ProcedurePatch(player=self.player, player_name=self.player_name)
        patch_rom(self, patch)
        out_base = self.multiworld.get_out_file_name_base(self.player)
        patch.write(os.path.join(output_directory, f"{out_base}{patch.patch_file_ending}"))

    set_rules = set_rules


# Import the BizHawk client so it registers itself. Done at the bottom so that
# BASE_ID / SMB3World are already defined when Client.py imports from this module
# (avoids a circular import). See worlds/_bizhawk/README.md.
from .Client import SMB3Client  # noqa: E402, F401
