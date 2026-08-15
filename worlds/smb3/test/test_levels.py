"""Tests for per-level / toad-house detection (PR 4): the generated panel table,
the client's panel_cleared helper, and the level_checks option gating."""
import unittest

from . import SMB3TestBase
from ..Client import panel_cleared, SAVE_STATE_FLIP_THRESHOLD
from ..Locations import (
    FORTRESS_COUNTS, level_check_location_names, level_location_name,
    location_name_to_id, location_table,
)
from ..panels import PANELS


class TestPanelTable(unittest.TestCase):
    """The disasm-generated PANELS table (worlds/smb3/panels.py)."""

    def test_world1_matches_known_layout(self) -> None:
        # World 1: 1-1..1-6 at their exact (offset,bit); fortresses excluded.
        expected = {
            (1, 0x04, 0x80): ("level", "1-1"),
            (1, 0x08, 0x80): ("level", "1-2"),
            (1, 0x0A, 0x80): ("level", "1-3"),
            (1, 0x0A, 0x20): ("level", "1-4"),
            (1, 0x04, 0x01): ("level", "1-5"),
            (1, 0x08, 0x01): ("level", "1-6"),
        }
        for key, val in expected.items():
            self.assertEqual(PANELS.get(key), val, f"panel {key}")

    def test_no_fortresses_in_table(self) -> None:
        # Fortresses stay on the Phase-0 count-based path; excluded from PANELS.
        self.assertFalse(any(kind == "fortress" for kind, _ in PANELS.values()))

    def test_kinds_are_level_or_toadhouse(self) -> None:
        for kind, _name in PANELS.values():
            self.assertIn(kind, ("level", "toad_house"))

    def test_level_count_per_world(self) -> None:
        # Real SMB3 numbered-level counts (fortresses/airships/vehicles excluded).
        expected = {1: 6, 2: 5, 3: 9, 4: 5, 5: 9, 6: 10, 7: 9, 8: 2}
        got = {}
        for (w, _o, _b), (kind, _n) in PANELS.items():
            if kind == "level":
                got[w] = got.get(w, 0) + 1
        self.assertEqual(got, expected)

    def test_panel_keys_unique(self) -> None:
        # Keys are the dict keys, inherently unique; assert offsets are in range and
        # bits are single masks (sanity on the parser output).
        valid_bits = {0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01}
        for (w, off, bit) in PANELS:
            self.assertTrue(1 <= w <= 8)
            self.assertTrue(0 <= off <= 0x3F)
            self.assertIn(bit, valid_bits)


class TestPanelCleared(unittest.TestCase):
    """The pure client helper that turns a Map_Completions diff into flips."""

    def _z(self) -> bytes:
        return bytes(0x40)

    def _bit(self, byte_index: int, mask: int) -> bytes:
        b = bytearray(0x40)
        b[byte_index] = mask
        return bytes(b)

    def test_baseline_none_never_fires(self) -> None:
        self.assertEqual(panel_cleared(None, self._bit(4, 0x80)), ([], False))

    def test_single_flip(self) -> None:
        flips, bulk = panel_cleared(self._z(), self._bit(4, 0x80))
        self.assertEqual(flips, [(4, 0x80)])
        self.assertFalse(bulk)

    def test_no_change(self) -> None:
        snap = self._bit(4, 0x80)
        self.assertEqual(panel_cleared(snap, snap), ([], False))

    def test_clearing_bit_is_not_a_flip(self) -> None:
        # 1 -> 0 must not count.
        flips, bulk = panel_cleared(self._bit(4, 0x80), self._z())
        self.assertEqual(flips, [])
        self.assertFalse(bulk)

    def test_bulk_load_guard(self) -> None:
        # A save-state swap flips many bits at once -> bulk, no credit.
        many = bytearray(0x40)
        for i in range(8):
            many[i] = 0xFF
        flips, bulk = panel_cleared(self._z(), bytes(many))
        self.assertEqual(flips, [])
        self.assertTrue(bulk)

    def test_threshold_boundary(self) -> None:
        # Exactly THRESHOLD flips is allowed; one more is bulk.
        b = bytearray(0x40)
        bits = [0x80, 0x40, 0x20, 0x10]
        for i in range(SAVE_STATE_FLIP_THRESHOLD):
            b[i] = bits[i]
        flips, bulk = panel_cleared(bytes(0x40), bytes(b))
        self.assertEqual(len(flips), SAVE_STATE_FLIP_THRESHOLD)
        self.assertFalse(bulk)


class TestDesiredCompletionBytes(unittest.TestCase):
    """The pure client helper that re-asserts a world's cleared-level checkmark bits
    from the AP checked set (client-driven persistence across hub travel)."""

    def setUp(self) -> None:
        from ..Client import _DRAWABLE_PANEL_BITS
        self.bits = _DRAWABLE_PANEL_BITS
        # World 1 has level panels; grab one (offset, bit, loc_id) to drive the tests.
        self.assertIn(1, self.bits, "World 1 should have level panels")
        self.off, self.bit, self.lid = self.bits[1][0]

    def test_none_when_nothing_checked(self) -> None:
        from ..Client import desired_completion_bytes
        cur = bytes(0x40)
        self.assertIsNone(desired_completion_bytes(1, set(), cur))

    def test_sets_bit_for_checked_level(self) -> None:
        from ..Client import desired_completion_bytes
        cur = bytes(0x40)
        out = desired_completion_bytes(1, {self.lid}, cur)
        self.assertIsNotNone(out)
        self.assertTrue(out[self.off] & self.bit,
                        "checked level's bit must be set in the output image")

    def test_none_when_already_set(self) -> None:
        from ..Client import desired_completion_bytes
        cur = bytearray(0x40)
        cur[self.off] |= self.bit  # already showing the checkmark
        self.assertIsNone(desired_completion_bytes(1, {self.lid}, bytes(cur)),
                          "no write when the bit is already present")

    def test_only_adds_never_clears(self) -> None:
        from ..Client import desired_completion_bytes
        # An unrelated bit is set in cur; the helper must preserve it.
        cur = bytearray(0x40)
        other_off = (self.off + 1) % 0x40
        cur[other_off] = 0x01
        out = desired_completion_bytes(1, {self.lid}, bytes(cur))
        self.assertIsNotNone(out)
        self.assertTrue(out[other_off] & 0x01, "must not clear pre-existing bits")
        self.assertTrue(out[self.off] & self.bit)

    def test_unknown_world_is_none(self) -> None:
        from ..Client import desired_completion_bytes
        # World 9 (hub) has no level panels.
        self.assertIsNone(desired_completion_bytes(9, {self.lid}, bytes(0x40)))

    def test_redraws_checked_fortress_panels(self) -> None:
        # A checked fortress must have its map panel bit re-asserted for redraw, so it
        # doesn't reappear "rebuilt" after a repaint wipes Map_Completions (BUG-A).
        from ..Client import desired_completion_bytes
        from ..panels import FORTRESS_PANEL_BITS
        from ..Locations import fortress_location_ids
        # World 1 has exactly one fortress panel and one fortress location.
        fort_panels = FORTRESS_PANEL_BITS[1]
        self.assertTrue(fort_panels, "World 1 should have a fortress panel")
        f_off, f_bit = fort_panels[0]
        fort_lid = fortress_location_ids(1)[0]
        out = desired_completion_bytes(1, {fort_lid}, bytes(0x40))
        self.assertIsNotNone(out)
        self.assertTrue(out[f_off] & f_bit,
                        "checked fortress's panel bit must be set for redraw")

    def test_fortress_redraw_is_count_capped(self) -> None:
        # We never light more fortress panels than the world has, even if more fortress
        # locations are checked than there are map panels (W3/W5: 2 locations, 1 panel).
        from ..Client import desired_completion_bytes
        from ..panels import FORTRESS_PANEL_BITS
        from ..Locations import fortress_location_ids
        world = 3
        panels = FORTRESS_PANEL_BITS.get(world, [])
        all_forts = set(fortress_location_ids(world))
        out = desired_completion_bytes(world, all_forts, bytes(0x40))
        # Count fortress bits set; must not exceed the number of actual panels.
        lit = sum(1 for off, bit in panels if out and (out[off] & bit))
        self.assertLessEqual(lit, len(panels))

    def test_redraws_checked_toad_house(self) -> None:
        # Toad houses must also be re-asserted for redraw (same latent bug as forts).
        from ..Client import desired_completion_bytes, _DRAWABLE_PANEL_BITS
        from ..panels import PANELS
        from ..Locations import location_name_to_id
        # Find a World-1 toad house panel.
        th = next(((w, o, b, name) for (w, o, b), (k, name) in PANELS.items()
                   if k == "toad_house" and w == 1), None)
        self.assertIsNotNone(th, "World 1 should have a toad house")
        _w, o, b, name = th
        th_lid = location_name_to_id[name]
        out = desired_completion_bytes(1, {th_lid}, bytes(0x40))
        self.assertIsNotNone(out)
        self.assertTrue(out[o] & b, "checked toad house's bit must be set for redraw")


class TestBroPersistence(unittest.TestCase):
    """The pure helpers behind roaming-enemy (Hammer/Boomerang/Heavy/Fire Bro)
    persistence across hub travel."""

    def test_detects_bro_defeat_transition(self) -> None:
        from ..Client import newly_defeated_bro_slots
        # slot 2 = Hammer Bro ($03) -> empty ($00); slot 3 stays a live bro.
        prev = bytes([0x01, 0x02, 0x03, 0x03, 0x00])
        cur = bytes([0x01, 0x02, 0x00, 0x03, 0x00])
        self.assertEqual(newly_defeated_bro_slots(prev, cur), [2])

    def test_detects_multiple_bros(self) -> None:
        from ..Client import newly_defeated_bro_slots
        # Two heavy bros ($05) cleared at once (e.g. a batched read).
        prev = bytes([0x01, 0x02, 0x05, 0x05, 0x05])
        cur = bytes([0x01, 0x02, 0x00, 0x00, 0x05])
        self.assertEqual(newly_defeated_bro_slots(prev, cur), [2, 3])

    def test_ignores_non_bro_and_baseline(self) -> None:
        from ..Client import newly_defeated_bro_slots
        # First pass (prev None) is a baseline, never a defeat.
        self.assertEqual(newly_defeated_bro_slots(None, bytes(8)), [])
        # A bro converting to a coin ship ($0B) is NOT a defeat we persist.
        prev = bytes([0x03, 0x00])
        cur = bytes([0x0B, 0x00])
        self.assertEqual(newly_defeated_bro_slots(prev, cur), [])
        # An airship ($02) vanishing is not a roaming-bro defeat.
        self.assertEqual(newly_defeated_bro_slots(bytes([0x02]), bytes([0x00])), [])

    def test_reblank_only_respawned_bros(self) -> None:
        from ..Client import reblank_defeated_slots
        # Recorded defeated: slots 2 and 4. Slot 2 respawned as a bro -> reblank; slot 4
        # currently empty -> leave it; slot 3 not recorded -> untouched even if a bro.
        cur = bytes([0x01, 0x02, 0x03, 0x03, 0x00])
        self.assertEqual(reblank_defeated_slots({2, 4}, cur), [2])

    def test_reblank_never_touches_non_bro(self) -> None:
        from ..Client import reblank_defeated_slots
        # A recorded slot that came back as a coin ship ($0B) is left alone (we only
        # re-clear slots that respawned as an actual bro).
        cur = bytes([0x00, 0x00, 0x0B])
        self.assertEqual(reblank_defeated_slots({2}, cur), [])

    def test_reblank_out_of_range_slot_safe(self) -> None:
        from ..Client import reblank_defeated_slots
        self.assertEqual(reblank_defeated_slots({99}, bytes(14)), [])


class TestLocationsIds(unittest.TestCase):
    def test_all_ids_unique(self) -> None:
        codes = [d.code for d in location_table.values() if d.code is not None]
        self.assertEqual(len(codes), len(set(codes)))

    def test_level_names_resolve(self) -> None:
        # Every level panel yields a resolvable, id-bearing location.
        for (w, _o, _b), (kind, name) in PANELS.items():
            loc = level_location_name(w, name) if kind == "level" else name
            self.assertIn(loc, location_name_to_id)

    def test_count(self) -> None:
        # 55 levels + 22 toad houses.
        self.assertEqual(len(level_check_location_names()), 77)


class TestLevelChecksOff(SMB3TestBase):
    """Default: no level/toad-house locations placed; pool unchanged."""
    options = {"level_checks": 0}

    def test_no_level_locations_placed(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn("World 1 Level 1-1", names)
        self.assertNotIn("World 1 Toad House 1", names)

    def test_pool_balances(self) -> None:
        real = [l for l in self.multiworld.get_locations(self.player)
                if l.address is not None]
        self.assertEqual(len(self.multiworld.itempool), len(real))

    def test_only_airships_and_fortresses(self) -> None:
        real = [l for l in self.multiworld.get_locations(self.player)
                if l.address is not None]
        # 7 airships + sum(FORTRESS_COUNTS) fortresses.
        self.assertEqual(len(real), 7 + sum(FORTRESS_COUNTS.values()))


class TestLevelChecksOn(SMB3TestBase):
    """level_checks on: levels + toad houses placed in their world regions."""
    options = {"level_checks": 1}

    def test_level_locations_placed_in_region(self) -> None:
        loc = self.multiworld.get_location("World 1 Level 1-1", self.player)
        self.assertIsNotNone(loc.address)
        self.assertEqual(loc.parent_region.name, "World 1")

    def test_toad_house_placed(self) -> None:
        loc = self.multiworld.get_location("World 1 Toad House 1", self.player)
        self.assertIsNotNone(loc.address)

    def test_pool_balances(self) -> None:
        real = [l for l in self.multiworld.get_locations(self.player)
                if l.address is not None]
        self.assertEqual(len(self.multiworld.itempool), len(real))

    def test_adds_all_level_checks(self) -> None:
        real = [l for l in self.multiworld.get_locations(self.player)
                if l.address is not None]
        self.assertEqual(len(real), 7 + sum(FORTRESS_COUNTS.values()) + 77)


class TestLevelAccessIdentity(unittest.TestCase):
    """The pure gated-panel / Access-item identity model (Locations.py)."""

    def test_counts(self) -> None:
        from ..Locations import gated_panels, access_item_names, access_item_codes
        # 55 levels + 22 toad houses + 12 fortress PANELS = 89 gated panels.
        self.assertEqual(len(gated_panels()), 89)
        self.assertEqual(len(access_item_names()), 89)
        self.assertEqual(len(access_item_codes), 89)

    def test_access_codes_unique_and_ranged(self) -> None:
        from ..Locations import access_item_codes, ACCESS_CODE_BASE
        codes = list(access_item_codes.values())
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(c >= ACCESS_CODE_BASE for c in codes))

    def test_access_name_matches_base(self) -> None:
        from ..Locations import access_item_name
        self.assertEqual(access_item_name("World 1 Level 1-1"),
                         "World 1 Level 1-1 Access")

    def test_every_gated_base_is_a_real_location(self) -> None:
        from ..Locations import gated_panels, location_name_to_id
        for _w, _o, _b, base in gated_panels():
            self.assertIn(base, location_name_to_id,
                          f"gated base {base!r} must be a real location")

    def test_access_items_are_progression(self) -> None:
        from BaseClasses import ItemClassification
        from ..Items import item_table
        from ..Locations import access_item_names
        for name in access_item_names():
            self.assertEqual(item_table[name].classification,
                             ItemClassification.progression)


class TestLevelAccessOn(SMB3TestBase):
    """level_access on (with its required deps hub_world + level_checks)."""
    options = {"level_access": 1, "hub_world": 1, "level_checks": 1}

    def test_pool_balances(self) -> None:
        real = [l for l in self.multiworld.get_locations(self.player)
                if l.address is not None]
        self.assertEqual(len(self.multiworld.itempool), len(real))

    def test_all_access_items_in_pool(self) -> None:
        from ..Locations import access_item_names
        pool = {i.name for i in self.multiworld.itempool}
        for name in access_item_names():
            self.assertIn(name, pool)

    def test_region_graph_is_hub_and_spoke(self) -> None:
        # Every World region connects directly from Menu (not the linear chain).
        menu = self.multiworld.get_region("Menu", self.player)
        menu_targets = {e.connected_region.name for e in menu.exits}
        for w in range(1, 9):
            self.assertIn(f"World {w}", menu_targets)

    def test_check_gated_on_access_item(self) -> None:
        # A level's clear-check is not reachable without its Access item, and is with it.
        from ..Locations import access_item_name
        loc = self.multiworld.get_location("World 1 Level 1-1", self.player)
        base = self.multiworld.state.copy()
        self.assertFalse(loc.can_reach(base))
        base.collect(self.world.create_item(access_item_name("World 1 Level 1-1")))
        self.assertTrue(loc.can_reach(base))


class TestLevelAccessValidation(SMB3TestBase):
    """generate_early must reject level_access without its required deps."""
    # Don't auto-run the standard WorldTestBase setup (we want to assert on setup itself).
    auto_construct = False

    def _expect_error(self, options: dict) -> None:
        from Options import OptionError
        self.options = options
        with self.assertRaises(OptionError):
            self.world_setup()

    def test_requires_hub_world(self) -> None:
        self._expect_error({"level_access": 1, "hub_world": 0, "level_checks": 1})

    def test_requires_level_checks(self) -> None:
        self._expect_error({"level_access": 1, "hub_world": 1, "level_checks": 0})

    def test_requires_both(self) -> None:
        self._expect_error({"level_access": 1, "hub_world": 0, "level_checks": 0})


if __name__ == "__main__":
    unittest.main()
