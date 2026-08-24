from typing import TYPE_CHECKING

from worlds.generic.Rules import set_rule

from .Locations import (
    access_item_name, all_required_fortress_locations, fortress_beaten_event_name,
    gated_panels, required_fortress_events,
)

if TYPE_CHECKING:
    from . import SMB3World


def set_rules(world: "SMB3World") -> None:
    """Access rules.

    Base (level_access off): worlds are reached via the region graph and no check is
    gated by a received item, so the graph itself carries all the logic. The only
    completion requirement is the Victory event.

    level_access on: each gated panel's clear-CHECK requires (a) its Access item and
    (b) any fortress that physically gates the path to it being beaten (World 6 etc.,
    from the derived lock topology). The fortress-beaten EVENTS themselves require the
    fortress's own Access item plus its upstream fortress chain. Completion stays Victory.
    """
    player = world.player

    if world.options.level_access:
        # (1) Fortress-beaten event locations: require the fortress's own Access item AND
        #     the fortress's own upstream chain (a fortress can itself be behind a lock).
        for fort_loc in all_required_fortress_locations():
            fort_access = access_item_name(fort_loc)
            upstream = required_fortress_events(fort_loc)  # events gating THIS fortress
            reqs = [fort_access] + upstream
            set_rule(
                world.get_location(fortress_beaten_event_name(fort_loc)),
                lambda state, items=tuple(reqs): all(state.has(i, player) for i in items),
            )

        # (2) Every gated panel's clear-check: its Access item + the fortress-beaten
        #     events that gate the path to it.
        for _w, _off, _bit, base_location in gated_panels():
            access = access_item_name(base_location)
            fort_events = required_fortress_events(base_location)
            reqs = [access] + fort_events
            set_rule(
                world.get_location(base_location),
                lambda state, items=tuple(reqs): all(state.has(i, player) for i in items),
            )

    world.multiworld.completion_condition[player] = \
        lambda state: state.has("Victory", player)
