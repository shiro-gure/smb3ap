from dataclasses import dataclass

from Options import Choice, OptionGroup, PerGameCommonOptions, Toggle


class Goal(Choice):
    """The victory condition for this world.

    bowser: beat Bowser's Castle (vanilla World 8 climax). Currently the only goal.
    Additional goals (e.g. ALL FORTS) arrive in later phases — see DESIGN.md.
    """
    display_name = "Goal"
    option_bowser = 0
    default = 0


class ItemModel(Choice):
    """How SMB3 participates in the item pool.

    filler_only: the airship locations hold items for the multiworld; SMB3 itself
        receives only filler (extra lives, power-ups). No SMB3 progression is gated.
        This is the Phase 0 (POC) model.
    gated_worlds: define progression "World N Unlock" items that gate each world.
        Not yet implemented — deferred to Phase 1 (needs a map-lock ASM hook).
    """
    display_name = "Item Model"
    option_filler_only = 0
    option_gated_worlds = 1
    default = 0


class LevelChecks(Toggle):
    """Add a location check for every individual level and Toad House.

    off (default): only the airship-boss and fortress clears (plus Bowser) are
        location checks — the Phase 0 / Any% set.
    on: every numbered level (1-1, 1-2, …) and every Toad House also becomes a
        check, fired when you clear that panel. A "100%"-style set of checks. This
        only *adds* locations; the victory condition is still whatever Goal says.
    """
    display_name = "Level Checks"


@dataclass
class SMB3Options(PerGameCommonOptions):
    goal: Goal
    item_model: ItemModel
    level_checks: LevelChecks


# Organizes the webhost options page (and generated YAML templates) into sections.
# Any option not listed here lands in an auto-generated "Game Options" group, and
# the item/location options get their own prebuilt group — so we only name the
# game-specific ones. See Archipelago Options.py OptionGroup / get_option_groups.
smb3_option_groups = [
    OptionGroup("Goal", [
        Goal,
        ItemModel,
    ]),
    OptionGroup("Locations", [
        LevelChecks,
    ]),
]
