from . import SMB3TestBase


class TestBasic(SMB3TestBase):
    def test_seven_airship_locations(self) -> None:
        """The 7 airship-boss locations exist as real (id-bearing) checks."""
        for n in range(1, 8):
            loc = self.multiworld.get_location(
                f"World {n} Airship - Boss Defeated", self.player)
            self.assertIsNotNone(loc.address)

    def test_victory_is_event(self) -> None:
        """Bowser's Castle holds the locked Victory event (no id)."""
        loc = self.multiworld.get_location("Bowser's Castle", self.player)
        self.assertIsNone(loc.address)
        self.assertEqual(loc.item.name, "Victory")
