"""Unit tests for the pure fortress/airship detection helpers in Client.py.

These don't need a running emulator or a generated world — they exercise the
location-id math and the count-based "next unchecked fortress" logic that the
BizHawk client uses to decide which check to send.
"""
import unittest

from ..Locations import FORTRESS_COUNTS
from ..Client import (
    airship_location_id, fortress_location_ids, next_unchecked_fortress,
    fortress_cleared, FORT_RUBBLE_TILES, MAP_COMPLETIONS_LEN, MAX_AIRSHIP_WORLD,
)


class TestAirshipIds(unittest.TestCase):
    def test_worlds_1_to_7_have_ids(self) -> None:
        ids = [airship_location_id(w) for w in range(1, MAX_AIRSHIP_WORLD + 1)]
        self.assertTrue(all(i is not None for i in ids))
        self.assertEqual(len(set(ids)), len(ids))  # unique

    def test_world_8_has_no_airship(self) -> None:
        self.assertIsNone(airship_location_id(8))


class TestFortressIds(unittest.TestCase):
    def test_counts_match_table(self) -> None:
        for world, count in FORTRESS_COUNTS.items():
            self.assertEqual(len(fortress_location_ids(world)), count)

    def test_total_is_fourteen(self) -> None:
        total = sum(len(fortress_location_ids(w)) for w in range(1, 9))
        self.assertEqual(total, 14)

    def test_ids_unique_across_worlds(self) -> None:
        all_ids = [i for w in range(1, 9) for i in fortress_location_ids(w)]
        self.assertEqual(len(set(all_ids)), len(all_ids))

    def test_world_with_no_fortress_returns_empty(self) -> None:
        # No world currently has 0, but the helper must be safe for one.
        self.assertEqual(fortress_location_ids(99), [])


class TestNextUncheckedFortress(unittest.TestCase):
    """The count-based clear-order credit logic."""

    def test_first_clear_credits_first_fortress(self) -> None:
        ids = fortress_location_ids(6)  # W6 has 3
        self.assertEqual(next_unchecked_fortress(6, set()), ids[0])

    def test_second_clear_credits_second_fortress(self) -> None:
        ids = fortress_location_ids(6)
        # First already checked -> next is the second.
        self.assertEqual(next_unchecked_fortress(6, {ids[0]}), ids[1])

    def test_clearing_all_in_order(self) -> None:
        ids = fortress_location_ids(3)  # W3 has 2
        checked = set()
        credited = []
        for _ in range(len(ids) + 1):  # one extra attempt past the end
            nxt = next_unchecked_fortress(3, checked)
            if nxt is None:
                break
            credited.append(nxt)
            checked.add(nxt)
        self.assertEqual(credited, ids)  # exactly the world's fortresses, in order

    def test_exhausted_returns_none(self) -> None:
        ids = fortress_location_ids(2)  # W2 has 1
        self.assertIsNone(next_unchecked_fortress(2, set(ids)))

    def test_single_world_in_isolation(self) -> None:
        # Crediting W4's fortresses must not consume W5's, even though they're
        # cleared in the same playthrough.
        w4 = fortress_location_ids(4)
        w5 = fortress_location_ids(5)
        # Pretend both W4 fortresses are done; W5 should still start fresh.
        self.assertEqual(next_unchecked_fortress(5, set(w4)), w5[0])


class TestFortressCleared(unittest.TestCase):
    """The Map_Completions panel-bit diff + rubble-tile gate (covers Boom Boom
    AND secret-exit fortress completions)."""

    RUBBLE = FORT_RUBBLE_TILES[0]      # $60
    ALT_RUBBLE = FORT_RUBBLE_TILES[1]  # $E3
    NORMAL_TILE = 0x80                 # a normal "complete" panel tile

    def _zeros(self) -> bytes:
        return bytes(MAP_COMPLETIONS_LEN)

    def _with_bit(self, byte_index: int, mask: int) -> bytes:
        b = bytearray(MAP_COMPLETIONS_LEN)
        b[byte_index] = mask
        return bytes(b)

    def test_first_pass_baseline_never_fires(self) -> None:
        # prev is None on the first pass / right after connect.
        self.assertFalse(fortress_cleared(None, self._with_bit(4, 0x10), self.RUBBLE))

    def test_bit_flip_on_rubble_is_clear(self) -> None:
        prev = self._zeros()
        cur = self._with_bit(4, 0x10)  # one bit went 0 -> 1
        self.assertTrue(fortress_cleared(prev, cur, self.RUBBLE))

    def test_bit_flip_on_alt_rubble_is_clear(self) -> None:
        prev = self._zeros()
        cur = self._with_bit(7, 0x80)
        self.assertTrue(fortress_cleared(prev, cur, self.ALT_RUBBLE))

    def test_bit_flip_on_normal_tile_is_not_fortress(self) -> None:
        # A normal level clear flips a panel bit too, but not on a rubble tile.
        prev = self._zeros()
        cur = self._with_bit(4, 0x10)
        self.assertFalse(fortress_cleared(prev, cur, self.NORMAL_TILE))

    def test_no_change_is_not_clear(self) -> None:
        snap = self._with_bit(4, 0x10)
        self.assertFalse(fortress_cleared(snap, snap, self.RUBBLE))

    def test_bit_clearing_is_not_clear(self) -> None:
        # 1 -> 0 (e.g. a reset) must not count as a clear.
        prev = self._with_bit(4, 0x10)
        cur = self._zeros()
        self.assertFalse(fortress_cleared(prev, cur, self.RUBBLE))

    def test_additional_bit_alongside_existing(self) -> None:
        # A new bit set while another stays set still counts (0->1 on the new one).
        prev = self._with_bit(4, 0x10)
        cur = bytearray(prev)
        cur[6] = 0x02  # new bit in a different column
        self.assertTrue(fortress_cleared(prev, bytes(cur), self.RUBBLE))


if __name__ == "__main__":
    unittest.main()
