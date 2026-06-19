from dataclasses import dataclass

from Options import Choice, PerGameCommonOptions


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


@dataclass
class SMB3Options(PerGameCommonOptions):
    goal: Goal
    item_model: ItemModel
