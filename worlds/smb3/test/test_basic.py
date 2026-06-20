from . import SMB3TestBase
from ..Locations import (
    FORTRESS_COUNTS, airship_location_name, fortress_location_name,
    location_table,
)


class TestBasic(SMB3TestBase):
    def test_seven_airship_locations(self) -> None:
        """The 7 airship-boss locations exist as real (id-bearing) checks."""
        for n in range(1, 8):
            loc = self.multiworld.get_location(
                airship_location_name(n), self.player)
            self.assertIsNotNone(loc.address)

    def test_fortress_locations_exist(self) -> None:
        """Every world's fortress locations exist as real checks, in its region."""
        for world, count in FORTRESS_COUNTS.items():
            for i in range(1, count + 1):
                loc = self.multiworld.get_location(
                    fortress_location_name(world, i), self.player)
                self.assertIsNotNone(loc.address)
                self.assertEqual(loc.parent_region.name, f"World {world}")

    def test_location_ids_unique(self) -> None:
        """No id collisions across airships + fortresses."""
        codes = [d.code for d in location_table.values() if d.code is not None]
        self.assertEqual(len(codes), len(set(codes)))

    def test_victory_is_event(self) -> None:
        """Bowser's Castle holds the locked Victory event (no id)."""
        loc = self.multiworld.get_location("Bowser's Castle", self.player)
        self.assertIsNone(loc.address)
        self.assertEqual(loc.item.name, "Victory")

    def test_itempool_balances_locations(self) -> None:
        """Filler pool size == number of real (id-bearing) locations."""
        real_locations = [loc for loc in self.multiworld.get_locations(self.player)
                          if loc.address is not None]
        self.assertEqual(len(self.multiworld.itempool), len(real_locations))
