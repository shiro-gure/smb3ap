"""BizHawk client for Super Mario Bros. 3 (client-only POC, no ROM patch).

The client attaches to a *vanilla* SMB3 US (PRG1) ROM running in BizHawk via the
generic connector, reads RAM to detect progress, and writes received items
straight into RAM. There is no base patch — see worlds/smb3/README.md and the
project DESIGN.md for the (deferred) ASM track.

Addresses are CPU-space and read through the "System Bus" domain, which spans
both work RAM ($0736, $078D) and battery SRAM ($7D00+) uniformly on the NES core.
"""

import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from NetUtils import ClientStatus

from worlds._bizhawk.client import BizHawkClient

from .Locations import location_table
from . import BASE_ID

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext, BizHawkClientCommandProcessor

logger = logging.getLogger("SMB3")

# --- RAM addresses (resolved from disasm/, see plan + DESIGN.md §5) ---
MAP_COMPLETIONS = 0x7D00       # $7D00-$7D3F Mario persistent panel/alteration bitfield
MAP_COMPLETIONS_LEN = 0x40     # 64 columns (covers all 4 map screens)
PLAYER_RESCUE_PRINCESS = 0x078D  # non-zero after Bowser beaten -> victory
PLAYER_LIVES = 0x0736          # Mario lives (grant "Extra Life")

DOMAIN = "System Bus"

# SMB3 USA (PRG1) — the ROM the disassembly targets. md5 of the headered .nes
# file, kept for reference / a future settings hash-check.
SMB3_FILE_MD5 = "bb5c4b6d4d78c101f94bdb360af502f3"

# ROM identification signature: the ASCII string "SUPER MARIO 3" is baked into the
# PRG ROM. The "PRG ROM" domain has no iNES header, so this sits at PRG offset
# 0x3FFE3. We read just these bytes (not the whole 256KB) — the connector returns
# each response as one socket line and asyncio's readline caps at ~64KB, so a full
# ROM read overruns the buffer.
_SIG_ADDR = 0x3FFE3
_SIG_BYTES = b"SUPER MARIO 3"


def _airship_locations_with_bits() -> Dict[int, Tuple[int, int]]:
    """location_id -> (ram_addr, bitmask) for airships that have been mapped.
    Empty until the empirical discovery pass fills the bits into Locations.py."""
    out: Dict[int, Tuple[int, int]] = {}
    for name, data in location_table.items():
        if data.ram_addr is not None and data.ram_bit is not None:
            out[BASE_ID + data.code] = (data.ram_addr, data.ram_bit)
    return out


def cmd_smb3_debug(self: "BizHawkClientCommandProcessor", state: str = "") -> None:
    """Toggle SMB3 debug logging (per-pass heartbeat + raw RAM). Usage: /smb3_debug [on|off]"""
    handler = getattr(self.ctx, "client_handler", None)
    if handler is None or handler.game != SMB3Client.game:
        logger.warning("This command can only be used when playing Super Mario Bros. 3.")
        return
    state = state.strip().lower()
    if state in ("on", "true", "1"):
        handler.debug = True
    elif state in ("off", "false", "0"):
        handler.debug = False
    else:
        handler.debug = not handler.debug  # no arg = toggle
    logger.info("SMB3 debug logging %s.", "ON" if handler.debug else "OFF")


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
        # One-time "watcher is running" announcement guard.
        self._watcher_announced = False
        # Verbose debug logging (per-pass heartbeat + raw RAM dump). Off by
        # default — toggle at runtime with the /smb3_debug client command.
        self.debug = False
        # Diagnostics: last early-skip reason logged (avoid spamming), and a
        # pass counter driving the periodic heartbeat.
        self._last_skip: Optional[str] = None
        self._pass = 0

    async def validate_rom(self, ctx: "BizHawkClientContext") -> bool:
        from worlds._bizhawk import read, get_memory_size, RequestFailedError
        try:
            size = await get_memory_size(ctx.bizhawk_ctx, "PRG ROM")
            if size < 0x40000:  # SMB3 PRG is 256KB
                return False
            # Read just the "SUPER MARIO 3" signature to confirm the ROM, so we
            # don't attach to and clobber the RAM of some other NES game.
            sig = (await read(
                ctx.bizhawk_ctx,
                [(_SIG_ADDR, len(_SIG_BYTES), "PRG ROM")]))[0]
        except RequestFailedError:
            return False
        if sig != _SIG_BYTES:
            return False

        ctx.game = self.game
        ctx.items_handling = 0b111  # full remote items
        ctx.want_slot_data = False
        # Register the /smb3_debug command (idempotent across re-validations).
        if "smb3_debug" not in ctx.command_processor.commands:
            ctx.command_processor.commands["smb3_debug"] = cmd_smb3_debug
        return True

    def on_package(self, ctx: "BizHawkClientContext", cmd: str, args: dict) -> None:
        # Re-baseline item dedup whenever a fresh connection is established, since
        # the server re-sends the full received-items list on Connected.
        if cmd == "Connected":
            self.synced = False
            self._watcher_announced = False

    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        from worlds._bizhawk import read, guarded_write, RequestFailedError

        # Log (once) why we bail before doing any work — these are the usual
        # reasons "nothing happens": not connected to the server, or no slot yet.
        if ctx.server is None:
            if self._last_skip != "no server":
                logger.warning("SMB3 watcher idle: not connected to AP server yet.")
                self._last_skip = "no server"
            return
        if ctx.slot is None:
            if self._last_skip != "no slot":
                logger.warning("SMB3 watcher idle: connected but not authenticated "
                               "(no slot) — enter your slot name.")
                self._last_skip = "no slot"
            return
        self._last_skip = None

        # One-time proof the watcher is actually running.
        if not self._watcher_announced:
            logger.warning("SMB3 client active: watching RAM. Beat an airship to "
                           "log its Map_Completions bit (discovery mode).")
            self._watcher_announced = True

        try:
            completions, rescue, lives = await read(ctx.bizhawk_ctx, [
                (MAP_COMPLETIONS, MAP_COMPLETIONS_LEN, DOMAIN),
                (PLAYER_RESCUE_PRINCESS, 1, DOMAIN),
                (PLAYER_LIVES, 1, DOMAIN),
            ])
        except RequestFailedError as exc:
            logger.warning("SMB3 read failed (will retry): %s", exc)
            return
        except Exception:
            # An unhandled exception here would otherwise silently kill the whole
            # BizHawk watcher loop (the context does not wrap this call), so we
            # log it loudly and keep the loop alive.
            logger.exception("SMB3 watcher crashed during read")
            return

        # Heartbeat (debug only): every N passes, prove we're alive and show what
        # we read. Toggle with /smb3_debug. Off by default to avoid log spam.
        self._pass += 1
        if self.debug and self._pass % 30 == 1:
            nonzero = [(i, completions[i]) for i in range(MAP_COMPLETIONS_LEN)
                       if completions[i]]
            logger.info(
                "SMB3 heartbeat #%d: rescue=$%02X lives=$%02X "
                "Map_Completions nonzero bytes=%s",
                self._pass, rescue[0], lives[0],
                ", ".join(f"[{i}]=$%02X" % v for i, v in nonzero) or "none")

        try:
            # --- discovery: log newly-set bits to map airships to (byte,bit) ---
            if self.discovery and self.prev_completions is not None:
                for i in range(MAP_COMPLETIONS_LEN):
                    newly = completions[i] & ~self.prev_completions[i]
                    if newly:
                        for bit in range(8):
                            if newly & (1 << bit):
                                logger.warning(
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

            # --- victory --- (AP dedups server-side, sets finished_game on confirm)
            if not ctx.finished_game and rescue[0] != 0:
                logger.warning("SMB3: Player_RescuePrincess set — sending victory.")
                await ctx.send_msgs([{
                    "cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])

            # --- grant received items (POC: every filler item == +1 life) ---
            #
            # POC limitation: dedup state lives only on the client (no ROM scratch
            # byte without ASM). On (re)connect the server re-sends every prior
            # item, so we baseline applied_items the first pass and only grant
            # items that arrive after that. Items received while disconnected are
            # not retroactively granted.
            received = ctx.items_received
            if not self.synced:
                self.applied_items = len(received)
                self.synced = True
            elif len(received) > self.applied_items:
                to_apply = len(received) - self.applied_items
                new_lives = min(0x99, lives[0] + to_apply)
                ok = await guarded_write(
                    ctx.bizhawk_ctx,
                    [(PLAYER_LIVES, [new_lives], DOMAIN)],
                    [(PLAYER_LIVES, [lives[0]], DOMAIN)],  # guard: lives unchanged
                )
                if ok:
                    logger.warning("SMB3: granted %d item(s) -> lives $%02X",
                                   to_apply, new_lives)
                    self.applied_items = len(received)
        except Exception:
            logger.exception("SMB3 watcher crashed after read")
