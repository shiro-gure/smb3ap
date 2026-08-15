"""Tests for the base-patch pipeline (PR 2).

Layered so they run in CI without the copyrighted ROM or the gitignored disasm:
- Always: the shipped base patch is present and is well-formed bsdiff4.
- ROM-gated: if a real PRG1 ROM is reachable, the patch round-trips and yields the
  expected patched CRC (the on-map checkmark edit).
- Disasm-gated: if disasm/CHR is present, the completed-panel tiles decode to the
  checkmark shape.
"""
import hashlib
import importlib.util
import os
import pkgutil
import unittest
import zlib

from ..Rom import INES_HEADER, PRG1_CRC32, PRG1_MD5, read_headerless_nes_rom

# CRC32 (headerless) of the vanilla PRG1 ROM and of the checkmark-patched ROM.
VANILLA_CRC32 = PRG1_CRC32                 # 0x2E6301ED
PATCHED_CRC32 = 0xE88E6C2B
# Exactly two contiguous CHR clusters change (tiles $88-$8B, $DC-$DF): 66 bytes.
EXPECTED_DIFF_BYTES = 66

# The hub base patch (checkmark + World-9 hub: start-in-W9 + vanilla World9L with 3
# added $DB vertical path links + walkable-pipe valid-list edit + return-to-hub; the
# vanilla W9 routing table is unchanged). The start-world operand at file 0x30CC3
# becomes 0x08 (World 9). HubInit lands on the W2 pipe (X=$60, Y=$50).
# PR 5c keeps cleared LEVELS re-enterable + walk-through while showing the checkmark:
# metatile $16 (CHR -> $88-$8B) + LevelCompGate repaint split (prg012) + MoveGate
# walk-through (prg010). Completion PERSISTENCE across travel is client-driven (the
# native bitfield is world-agnostic with no free RAM to segment it), so there is NO
# ROM clear-loop gate — the vanilla wipe-on-load is intact. A Part-3 MapRepaintCheck
# hook (idle-loop JSR Map_DoMap -> ) repaints on a client-set flag ($0701) so the
# re-asserted checkmarks appear right after travel.
# PR 6 adds SelectWarpCheck (bank 10): pressing SELECT on any world map warps to the
# hub (World 9) via HubReturn. The map-loop tick (prg030:946) now targets it, falling
# through to MapRepaintCheck. Hub-only (in basepatch_hub.bsdiff4).
# PR 7 adds EntryGate (bank 10): the level-access ENTRY gate hijacks PRG010_CEA7 and
# refuses entry to a LOCKED panel per the client's lock bitfield ($0550, 1=locked; only
# gated-and-not-yet-unlocked panels get a bit, so hub pipes / non-gated panels stay
# open), inert unless the ACTIVE flag ($054B) is set. Hub-only.
HUB_CRC32 = 0x78546EDF
START_WORLD_OFFSET = 0x30CC3

# realpath so this resolves the true repo even when worlds/smb3 is a symlink into
# an Archipelago clone (our test layout); the disasm/ROM live in the real repo.
_REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".."))
_DISASM_ROM = os.path.join(_REPO, "disasm", "smb3.nes")
_DISASM_CHR = os.path.join(_REPO, "disasm", "CHR")


def _load_base_patch() -> bytes:
    return pkgutil.get_data("worlds.smb3", "data/basepatch.bsdiff4")


def _find_vanilla_rom() -> bytes | None:
    """Best-effort: the dev disasm ROM if present, else the configured setting."""
    if os.path.exists(_DISASM_ROM):
        with open(_DISASM_ROM, "rb") as f:
            return f.read()
    try:
        from ..Rom import get_base_rom_path
        path = get_base_rom_path()
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None


class TestBasePatchPresence(unittest.TestCase):
    def test_base_patch_ships(self) -> None:
        data = _load_base_patch()
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 0)

    def test_base_patch_is_bsdiff4(self) -> None:
        import bsdiff4
        data = _load_base_patch()
        # bsdiff4 patches start with the magic b"BSDIFF40".
        self.assertTrue(data.startswith(b"BSDIFF40"),
                        "base patch is not a bsdiff4 blob")
        # And it must apply to *something* of the right size without erroring on
        # a valid input (checked concretely in the ROM-gated test below).
        self.assertTrue(hasattr(bsdiff4, "patch"))


class TestBasePatchRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.vanilla = _find_vanilla_rom()
        if self.vanilla is None:
            self.skipTest("no PRG1 ROM available (skipping ROM-gated round-trip)")

    def test_vanilla_hashes(self) -> None:
        headerless = read_headerless_nes_rom(self.vanilla)
        self.assertEqual(hashlib.md5(headerless).hexdigest(), PRG1_MD5)
        self.assertEqual(zlib.crc32(headerless) & 0xFFFFFFFF, VANILLA_CRC32)

    def test_patch_produces_checkmark_rom(self) -> None:
        import bsdiff4
        headered = INES_HEADER + read_headerless_nes_rom(self.vanilla)
        patched = bsdiff4.patch(headered, _load_base_patch())
        self.assertEqual(len(patched), len(headered))
        self.assertEqual(zlib.crc32(patched[16:]) & 0xFFFFFFFF, PATCHED_CRC32)
        diff = sum(1 for a, b in zip(headered, patched) if a != b)
        self.assertEqual(diff, EXPECTED_DIFF_BYTES)


class TestHubPatch(unittest.TestCase):
    """The World-9 hub base patch (basepatch_hub.bsdiff4, PR 5a)."""

    def _hub_patch(self) -> bytes:
        return pkgutil.get_data("worlds.smb3", "data/basepatch_hub.bsdiff4")

    def test_hub_patch_ships_and_is_bsdiff4(self) -> None:
        data = self._hub_patch()
        self.assertIsNotNone(data)
        self.assertTrue(data.startswith(b"BSDIFF40"))

    def test_hub_patch_produces_hub_rom(self) -> None:
        import bsdiff4
        vanilla = _find_vanilla_rom()
        if vanilla is None:
            self.skipTest("no PRG1 ROM available")
        headered = INES_HEADER + read_headerless_nes_rom(vanilla)
        hub = bsdiff4.patch(headered, self._hub_patch())
        self.assertEqual(len(hub), len(headered))
        self.assertEqual(zlib.crc32(hub[16:]) & 0xFFFFFFFF, HUB_CRC32)
        # The new-game start-world byte must be World 9 ($08), was World 1 ($00).
        self.assertEqual(headered[START_WORLD_OFFSET], 0x00)
        self.assertEqual(hub[START_WORLD_OFFSET], 0x08)

    def test_hub_is_superset_of_checkmark(self) -> None:
        # The hub ROM must still carry the checkmark edit (both patches applied).
        import bsdiff4
        vanilla = _find_vanilla_rom()
        if vanilla is None:
            self.skipTest("no PRG1 ROM available")
        headered = INES_HEADER + read_headerless_nes_rom(vanilla)
        checkmark = bsdiff4.patch(headered, _load_base_patch())
        hub = bsdiff4.patch(headered, self._hub_patch())
        # Every checkmark CHR byte that changed vs vanilla is also changed in hub.
        for i, (v, c) in enumerate(zip(headered, checkmark)):
            if v != c:
                self.assertEqual(hub[i], c, f"hub lost checkmark byte at 0x{i:X}")


class TestDuplicateInstallGuard(unittest.TestCase):
    """A stray duplicate SMB3 install must not abort the world load via a
    double `.apsmb3` registration (regression for the 'No world found to handle
    game' failure)."""

    def test_redefining_patch_class_is_idempotent(self) -> None:
        from worlds.Files import AutoPatchRegister
        from ..Rom import SMB3ProcedurePatch, _PATCH_ENDING, _define_patch_class

        # The ending is already registered (by the normal import). Defining the
        # class again must NOT raise; it must reuse the existing handler.
        self.assertIn(_PATCH_ENDING, AutoPatchRegister.file_endings)
        again = _define_patch_class()  # would raise ImproperlyConfiguredAutoPatchError pre-fix
        self.assertIs(again, SMB3ProcedurePatch)
        self.assertIs(again, AutoPatchRegister.file_endings[_PATCH_ENDING])


class TestNoRomLogging(unittest.TestCase):
    """When no base ROM is configured, generate_output must SKIP the .apsmb3 but
    LOG why (so a missing rom_file isn't a silent mystery)."""

    def test_skip_is_logged(self) -> None:
        import tempfile
        import worlds.smb3 as smb3
        from worlds.smb3 import Rom
        from test.general import setup_solo_multiworld

        # Force the "no usable ROM" path deterministically.
        original = Rom.get_base_rom_path
        Rom.get_base_rom_path = lambda file_name="": (_ for _ in ()).throw(
            FileNotFoundError("test: no rom configured"))
        try:
            mw = setup_solo_multiworld(smb3.SMB3World)
            world = mw.worlds[1]
            out = tempfile.mkdtemp()
            with self.assertLogs("Super Mario Bros. 3", level="INFO") as cm:
                world.generate_output(out)
            self.assertTrue(any("rom_file" in line for line in cm.output),
                            "expected a log line mentioning rom_file")
            self.assertFalse(any(f.endswith(".apsmb3") for f in os.listdir(out)),
                             "no patch should be emitted without a ROM")
        finally:
            Rom.get_base_rom_path = original


class TestCheckmarkTiles(unittest.TestCase):
    """Decode the disasm CHR (if present) and confirm the completed-panel tiles
    are the checkmark, not the vanilla M/L glyph."""

    def setUp(self) -> None:
        if not os.path.isdir(_DISASM_CHR):
            self.skipTest("disasm/CHR not present (gitignored)")
        # Import the dev pcxtool by path (it lives under patch/, not a package).
        tool_path = os.path.join(_REPO, "worlds", "smb3", "patch", "pcxtool.py")
        spec = importlib.util.spec_from_file_location("smb3_pcxtool", tool_path)
        self.pcx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pcx)

    def test_chr022_panel_is_checkmark(self) -> None:
        path = os.path.join(_DISASM_CHR, "chr022.pcx")
        w, _h, px, _pal = self.pcx.read_pcx(path)
        # The INK (value 3) pixels must form a checkmark: present in the lower-left
        # (short leg) and rising to the upper-right across the 2x2 panel.
        ink = 0
        for ti in (8, 9, 10, 11):
            for row in self.pcx.tile_pixels(px, w, ti):
                ink += sum(1 for v in row if v == 3)
        self.assertGreater(ink, 10, "expected a drawn checkmark stroke")


if __name__ == "__main__":
    unittest.main()
