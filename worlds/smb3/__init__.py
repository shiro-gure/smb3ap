import os
from typing import ClassVar, Optional

import settings
from BaseClasses import Item, ItemClassification, Location, Region, Tutorial
from Options import OptionError
from worlds.AutoWorld import World, WebWorld

from .Items import filler_item_names, item_table
from .Locations import (
    BASE_ID, BOWSERS_CASTLE, access_item_names, all_required_fortress_locations,
    fortress_beaten_event_name, level_access_item_names,
    level_check_location_names, level_check_locations_for_world,
    location_name_to_id, location_table,
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

    def generate_early(self) -> None:
        # level_access needs the entry-gate ROM hook (hub-only) AND the per-panel
        # clear-checks (level_checks). Refuse a combo that can't actually work rather
        # than silently mis-generating.
        if self.options.level_access:
            missing = []
            if not self.options.hub_world:
                missing.append("hub_world")
            if not self.options.level_checks:
                missing.append("level_checks")
            if missing:
                raise OptionError(
                    f"SMB3 ({self.player_name}): 'level_access' requires "
                    f"{' and '.join(missing)} to also be enabled "
                    f"(the entry-gate ROM hook is hub-only, and gated panels come from "
                    f"level_checks). Enable them, or turn off level_access."
                )

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)

        level_checks_on = bool(self.options.level_checks)
        # With level_access, the hub makes every world reachable, so the AP region graph
        # becomes hub-and-spoke (Menu -> each World directly) instead of the vanilla
        # linear chain. Access to a panel's CHECK is gated on its Access item in Rules.
        hub_and_spoke = bool(self.options.level_access)
        for name, data in region_table.items():
            region = Region(name, self.player, self.multiworld)
            locs = list(data.locations)
            # Optional per-level / toad-house checks only exist when the option is
            # on. Their ids are always defined in location_name_to_id, but we only
            # PLACE them here so the Any%/Vanilla pool is unchanged when it's off.
            if level_checks_on and name.startswith("World "):
                world_num = int(name.split()[1])
                locs += level_check_locations_for_world(world_num)
            region.add_locations(
                {loc: self.location_name_to_id.get(loc) for loc in locs},
                SMB3Location,
            )
            self.multiworld.regions.append(region)

        for name, data in region_table.items():
            if hub_and_spoke:
                source = menu  # every world reachable from the hub
            else:
                source = menu if data.connects_from is None else self.get_region(data.connects_from)
            source.connect(self.get_region(name))

        # Victory: beating Bowser's Castle. Locked event, excluded from the pool.
        victory = self.get_location(BOWSERS_CASTLE)
        victory.place_locked_item(self.create_event("Victory"))

        # level_access: fortress-beaten EVENTS for fortresses that gate a path (World 6
        # etc.). Each is an event location in the fortress's world region, holding a
        # "<fortress> Beaten (event)" item; downstream levels require it in Rules. The
        # event location's access rule (its own Access item + upstream chain) is set in
        # set_rules. This lets logic model "you must beat 6-F1 to reach 6-5".
        if self.options.level_access:
            for fort_loc in all_required_fortress_locations():
                world_num = int(fort_loc.split()[1])
                region = self.get_region(f"World {world_num}")
                ev_name = fortress_beaten_event_name(fort_loc)
                ev_loc = SMB3Location(self.player, ev_name, None, region)
                region.locations.append(ev_loc)
                ev_loc.place_locked_item(self.create_event(ev_name))

    def create_items(self) -> None:
        # Model A: one item per real (id-bearing) location actually PLACED.
        # location_table always defines the optional level/toad-house ids, so
        # subtract them when the level_checks option is off (they aren't placed).
        # The Victory event is a locked item placed separately, not counted here.
        placed_count = len(location_table)
        if not self.options.level_checks:
            placed_count -= len(level_check_location_names())

        # With level_access on, the 89 Access items are PROGRESSION items that fill 89 of
        # those slots (they replace filler, keeping total items == placed locations so the
        # multiworld stays balanced). generate_early guarantees level_checks is on here,
        # so all 89 gated panels' clear-checks are placed and there's room for them.
        #
        # BOOTSTRAP: with level_access, the only checks reachable with no items are the
        # airships/Bowser — but you can't physically reach an airship without playing
        # (locked) levels. So we PRECOLLECT a few random numbered-level Access items into
        # the starting inventory (levels only, so you begin with a real playable level).
        # Those items are already "found", so they're NOT also placed in the pool; filler
        # backfills their slots to keep the pool balanced.
        pool = []
        if self.options.level_access:
            access_names = list(access_item_names())
            n_start = min(int(self.options.level_access_starting_unlocks),
                          len(level_access_item_names()))
            starters = self.random.sample(level_access_item_names(), n_start)
            for name in starters:
                self.multiworld.push_precollected(self.create_item(name))
            starter_set = set(starters)
            pool += [self.create_item(name) for name in access_names
                     if name not in starter_set]
        remaining = placed_count - len(pool)
        pool += [self.create_item(self.get_filler_item_name()) for _ in range(remaining)]
        self.multiworld.itempool += pool

    def fill_slot_data(self) -> dict:
        # The client needs to know when to drive the entry-gate (level_access) so it can
        # arm the ROM hook's ACTIVE flag; and hub_world so it only writes hub-only RAM.
        return {
            "level_access": int(bool(self.options.level_access)),
            "hub_world": int(bool(self.options.hub_world)),
            "level_checks": int(bool(self.options.level_checks)),
        }

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
