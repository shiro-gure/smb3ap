from typing import TYPE_CHECKING

from worlds.generic.Rules import set_rule

from .Locations import access_item_name, gated_panels

if TYPE_CHECKING:
    from . import SMB3World


def set_rules(world: "SMB3World") -> None:
    """Access rules.

    Base (level_access off): worlds are reached via the region graph and no check is
    gated by a received item, so the graph itself carries all the logic. The only
    completion requirement is the Victory event.

    level_access on: each gated panel's clear-CHECK is reachable only once its Access
    item is received (MM2/MM3 stage-select gating). The hub already makes every world
    physically reachable (hub-and-spoke region graph), so the per-panel Access item is
    the real logical gate. Completion is still just the Victory event.
    """
    player = world.player

    if world.options.level_access:
        for _w, _off, _bit, base_location in gated_panels():
            item = access_item_name(base_location)
            set_rule(
                world.get_location(base_location),
                lambda state, i=item: state.has(i, player),
            )

    world.multiworld.completion_condition[player] = \
        lambda state: state.has("Victory", player)
