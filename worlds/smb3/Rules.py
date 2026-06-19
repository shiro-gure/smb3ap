from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import SMB3World


def set_rules(world: "SMB3World") -> None:
    """Phase 0 / item model A access rules.

    Worlds are reached in sequence and no airship check is gated by a received
    item, so the region chain itself (set up in create_regions) carries all the
    logic. The only completion requirement is the Victory event.
    """
    player = world.player
    world.multiworld.completion_condition[player] = \
        lambda state: state.has("Victory", player)
