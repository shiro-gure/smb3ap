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


class LevelAccess(Toggle):
    """Gate ENTRY to each level behind a per-panel Access item (MM2/MM3 stage-select style).

    off (default): every panel you can reach is enterable immediately.
    on: you can always WALK the overworld, but you can't ENTER a level, fortress, or Toad
        House until you receive its "… Access" item from the multiworld. Clearing a panel
        still fires its check (from Level Checks). Requires Hub World + Level Checks — if
        this is on without both, generation raises an error (the entry-gate ROM hook is
        hub-only, and the gated panels come from Level Checks).
    """
    display_name = "Level Access (entry gating)"


class HubWorld(Toggle):
    """Start in World 9 (the Warp Zone) as a travel hub instead of World 1.

    off (default): a new game starts in World 1 and worlds are played in order
        (vanilla progression).
    on: a ROM hack starts you in World 9 as a hub. (Full free travel — a panel to
        every world, and returning to the hub after beating a world — arrives in a
        follow-up; this first step lands you cleanly in World 9.) Requires the
        patched ROM (the .apsmb3 already carries it).
    """
    display_name = "Hub World (start in World 9)"


@dataclass
class SMB3Options(PerGameCommonOptions):
    goal: Goal
    item_model: ItemModel
    level_checks: LevelChecks
    level_access: LevelAccess
    hub_world: HubWorld


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
        LevelAccess,
    ]),
    OptionGroup("World", [
        HubWorld,
    ]),
]
