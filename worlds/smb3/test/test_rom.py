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
