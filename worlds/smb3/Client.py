"""BizHawk client for Super Mario Bros. 3 (client-only POC, no ROM patch).

The client attaches to a *vanilla* SMB3 US (PRG1) ROM running in BizHawk via the
generic connector, reads RAM to detect progress, and writes received items
straight into RAM. There is no base patch — see worlds/smb3/README.md and the
project DESIGN.md for the (deferred) ASM track.

Addresses are CPU-space and read through the "System Bus" domain, which spans
both work RAM ($0736, $078D) and battery SRAM ($7D00+) uniformly on the NES core.
"""

import hashlib
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from NetUtils import ClientStatus

from worlds._bizhawk.client import BizHawkClient

from .Locations import location_table
from . import BASE_ID

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext

logger = logging.getLogger("SMB3")

# --- RAM addresses (resolved from disasm/, see plan + DESIGN.md §5) ---
MAP_COMPLETIONS = 0x7D00       # $7D00-$7D3F Mario persistent panel/alteration bitfield
MAP_COMPLETIONS_LEN = 0x40     # 64 columns (covers all 4 map screens)
PLAYER_RESCUE_PRINCESS = 0x078D  # non-zero after Bowser beaten -> victory
PLAYER_LIVES = 0x0736          # Mario lives (grant "Extra Life")

DOMAIN = "System Bus"

# SMB3 USA (PRG1) — the ROM the disassembly targets.
# Headered .nes file md5 (for reference / settings hash-check):
SMB3_FILE_MD5 = "bb5c4b6d4d78c101f94bdb360af502f3"
# PRG ROM md5 (no iNES header) — what validate_rom hashes via the "PRG ROM" domain:
_PRG_MD5 = "11bde2e78a4c4f9e65899b4ada1b8667"


def _airship_locations_with_bits() -> Dict[int, Tuple[int, int]]:
    """location_id -> (ram_addr, bitmask) for airships that have been mapped.
    Empty until the empirical discovery pass fills the bits into Locations.py."""
    out: Dict[int, Tuple[int, int]] = {}
    for name, data in location_table.items():
        if data.ram_addr is not None and data.ram_bit is not None:
            out[BASE_ID + data.code] = (data.ram_addr, data.ram_bit)
    return out


class SMB3Client(BizHawkClient):
    game = "Super Mario Bros. 3"
    system = "NES"
    # No patch file in the POC; we identify the ROM by hash in validate_rom.
    patch_suffix = None

    def __init__(self) -> None:
        super().__init__()
        # Snapshot of Map_Completions from the previous watcher pass, so we can
        # detect 0->1 bit transitions and (in discovery mode) log them.
        self.prev_completions: Optional[bytes] = None
        # How many received items we've already applied to RAM (dedup).
        self.applied_items = 0
        # False until we've baselined applied_items against the server's
        # re-sent item list on (re)connect — see game_watcher.
        self.synced = False
        # When True, log every newly-set Map_Completions bit to help map the
        # 7 airships to (byte, bit). Toggle by editing this or via a command.
        self.discovery = True

    async def validate_rom(self, ctx: "BizHawkClientContext") -> bool:
        from worlds._bizhawk import read, get_memory_size, RequestFailedError
        try:
            size = await get_memory_size(ctx.bizhawk_ctx, "PRG ROM")
            if size < 0x40000:  # SMB3 PRG is 256KB
                return False
            # Hash the PRG ROM to confirm this is the SMB3 ROM we expect.
            rom = (await read(ctx.bizhawk_ctx, [(0, 0x40000, "PRG ROM")]))[0]
        except RequestFailedError:
            return False
        # Match the known SMB3 US (PRG1) PRG-ROM hash so we don't attach to and
        # clobber the RAM of some other NES game.
        if hashlib.md5(rom).hexdigest() != _PRG_MD5:
            return False

        ctx.game = self.game
        ctx.items_handling = 0b111  # full remote items
        ctx.want_slot_data = False
        return True

    def on_package(self, ctx: "BizHawkClientContext", cmd: str, args: dict) -> None:
        # Re-baseline item dedup whenever a fresh connection is established, since
        # the server re-sends the full received-items list on Connected.
        if cmd == "Connected":
            self.synced = False

    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        from worlds._bizhawk import read, guarded_write

        if ctx.server is None or ctx.slot is None:
            return

        completions, rescue, lives = await read(ctx.bizhawk_ctx, [
            (MAP_COMPLETIONS, MAP_COMPLETIONS_LEN, DOMAIN),
            (PLAYER_RESCUE_PRINCESS, 1, DOMAIN),
            (PLAYER_LIVES, 1, DOMAIN),
        ])

        # --- discovery: log newly-set bits so we can map airships to (byte,bit) ---
        if self.discovery and self.prev_completions is not None:
            for i in range(MAP_COMPLETIONS_LEN):
                newly = completions[i] & ~self.prev_completions[i]
                if newly:
                    for bit in range(8):
                        if newly & (1 << bit):
                            logger.info(
                                "SMB3 discovery: Map_Completions[$%04X] bit %d set "
                                "(byte_offset=%d, mask=$%02X)",
                                MAP_COMPLETIONS + i, bit, i, 1 << bit)
        self.prev_completions = completions

        # --- send location checks for mapped airship bits ---
        checked: List[int] = []
        for loc_id, (addr, mask) in _airship_locations_with_bits().items():
            if loc_id in ctx.locations_checked:
                continue
            if completions[addr - MAP_COMPLETIONS] & mask:
                checked.append(loc_id)
        if checked:
            await ctx.send_msgs([{"cmd": "LocationChecks", "locations": checked}])

        # --- victory --- (AP dedups server-side and sets finished_game on confirm)
        if not ctx.finished_game and rescue[0] != 0:
            await ctx.send_msgs([{
                "cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])

        # --- grant received items (POC: every filler item == +1 life) ---
        #
        # POC limitation: dedup state lives only on the client (no ROM scratch
        # byte without ASM). On (re)connect the server re-sends every prior item,
        # so we baseline applied_items to the current count the first pass and
        # only grant items that arrive *after* that. Trade-off: items received
        # while the client was disconnected are not retroactively granted.
        received = ctx.items_received
        if not self.synced:
            self.applied_items = len(received)
            self.synced = True
        elif len(received) > self.applied_items:
            to_apply = len(received) - self.applied_items
            new_lives = min(0x99, lives[0] + to_apply)  # SMB3 caps lives display
            ok = await guarded_write(
                ctx.bizhawk_ctx,
                [(PLAYER_LIVES, [new_lives], DOMAIN)],
                [(PLAYER_LIVES, [lives[0]], DOMAIN)],  # guard: lives unchanged
            )
            if ok:
                self.applied_items = len(received)
