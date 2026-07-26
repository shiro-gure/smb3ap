"""ROM output for the SMB3 world.

Phase 0 was a client-only POC (no ROM patch). This module adds the base-patch
pipeline: the player supplies a legally obtained SMB3 (U) (PRG1) ROM; we apply a
precomputed base patch (`data/basepatch.bsdiff4`, produced by reassembling the
Southbird disassembly with our edits — see `patch/README.md`) plus any per-seed
byte tokens, and emit an `.apsmb3` patch the client turns back into a ROM.

Modeled on mm2's APProcedurePatch/APTokenMixin (worlds/mm2/rom.py) — the modern
AP pattern. Only patched modes (the on-map checkmark, the hub, the shuffles) need
this; the original patchless client behavior is unaffected.
"""
import hashlib
import os
from typing import TYPE_CHECKING, Iterable, Optional

import settings
import Utils
from worlds.Files import APProcedurePatch, APTokenMixin, APTokenTypes

if TYPE_CHECKING:
    from . import SMB3World

# SMB3 (U) (PRG1) [!] — the disassembly's target revision. Hashes are of the
# 393216-byte headerless PRG (the 16-byte iNES header stripped), matching how
# read_headerless_nes_rom normalizes input.
PRG1_MD5 = "55b7111567c1709e849c574078699577"
PRG1_CRC32 = 0x2E6301ED

# The canonical iNES header for this ROM (16 PRG pages, 16 CHR pages, mapper 4).
INES_HEADER = bytes.fromhex("4e45531a101040000000000000000000")


class SMB3ProcedurePatch(APProcedurePatch, APTokenMixin):
    game = "Super Mario Bros. 3"
    hash = [PRG1_MD5]
    patch_file_ending = ".apsmb3"
    result_file_ending = ".nes"
    name: bytearray

    procedure = [
        ("apply_bsdiff4", ["basepatch.bsdiff4"]),
        ("apply_tokens", ["token_patch.bin"]),
    ]

    @classmethod
    def get_source_data(cls) -> bytes:
        return get_base_rom_bytes()

    def write_byte(self, offset: int, value: int) -> None:
        self.write_token(APTokenTypes.WRITE, offset, value.to_bytes(1, "little"))

    def write_bytes(self, offset: int, value: Iterable[int]) -> None:
        self.write_token(APTokenTypes.WRITE, offset, bytes(value))


def patch_rom(world: "SMB3World", patch: SMB3ProcedurePatch) -> None:
    """Assemble the patch: the base patch (checkmark + future hooks) plus any
    per-seed byte tokens (shuffles, hub tables — added in later PRs)."""
    import pkgutil
    patch.write_file("basepatch.bsdiff4", pkgutil.get_data(__name__, "data/basepatch.bsdiff4"))
    # Per-seed token writes go here in later PRs (shuffle tables, hub layout).
    # Always emit the (possibly empty) token binary so apply_tokens has its input.
    patch.write_file("token_patch.bin", patch.get_token_binary())


def read_headerless_nes_rom(rom: bytes) -> bytes:
    """Strip a 16-byte iNES header if present."""
    if rom[:4] == b"NES\x1a":
        return rom[16:]
    return rom


def get_base_rom_bytes(file_name: str = "") -> bytes:
    """Load, validate, and return the HEADERED base ROM (the base patch is
    diffed against the headered ROM). Cached after first read."""
    base_rom_bytes: Optional[bytes] = getattr(get_base_rom_bytes, "base_rom_bytes", None)
    if not base_rom_bytes:
        file_name = get_base_rom_path(file_name)
        with open(file_name, "rb") as f:
            headerless = read_headerless_nes_rom(f.read())

        basemd5 = hashlib.md5(headerless).hexdigest()
        if basemd5 != PRG1_MD5:
            raise ValueError(
                f"Supplied ROM does not match the known MD5 for SMB3 (U) (PRG1). "
                f"Got {basemd5}, expected {PRG1_MD5}. Use the correct game/version."
            )
        base_rom_bytes = INES_HEADER + headerless
        setattr(get_base_rom_bytes, "base_rom_bytes", base_rom_bytes)
    return base_rom_bytes


def get_base_rom_path(file_name: str = "") -> str:
    options: settings.Settings = settings.get_settings()
    if not file_name:
        file_name = options["smb3_options"]["rom_file"]
    if not os.path.exists(file_name):
        file_name = Utils.user_path(file_name)
    return file_name
