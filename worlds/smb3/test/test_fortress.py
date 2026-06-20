"""Unit tests for the pure fortress/airship detection helpers in Client.py.

These don't need a running emulator or a generated world — they exercise the
location-id math and the count-based "next unchecked fortress" logic that the
BizHawk client uses to decide which check to send.
"""
import unittest

from ..Locations import FORTRESS_COUNTS
from ..Client import (
    airship_location_id, fortress_location_ids, next_unchecked_fortress,
    MAX_AIRSHIP_WORLD,
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


if __name__ == "__main__":
    unittest.main()
