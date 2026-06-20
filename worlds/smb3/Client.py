"""BizHawk client for Super Mario Bros. 3 (client-only POC, no ROM patch).

The client attaches to a *vanilla* SMB3 US (PRG1) ROM — `Super Mario Bros. 3 (U)
(PRG1) [!]` (No-Intro Rev A) — running in BizHawk via the generic connector, reads
RAM to detect progress, and writes received items straight into RAM. There is no
base patch — see worlds/smb3/README.md and the project DESIGN.md for the (deferred)
ASM track. This is the exact revision the captainsouthbird disassembly reassembles
to, so the disassembly is authoritative for these addresses.

The ROM is identified by an internal signature (below), so the client also tolerates
PRG0, but PRG1 is the supported/disassembly-matching revision.

Addresses are CPU-space, read through the "System Bus" domain, which spans work RAM
($0727, $0736, $078D) uniformly on the NES core.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from NetUtils import ClientStatus

from worlds._bizhawk.client import BizHawkClient

from .Locations import location_table
from . import BASE_ID

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext, BizHawkClientCommandProcessor

logger = logging.getLogger("SMB3")

# --- RAM addresses (resolved from disasm/, authoritative on PRG1) ---
# World_Num: current world index, 0 = World 1 .. 7 = World 8, 8 = World 9/Warp.
# Airships have NO completion bit (the airship's Map_Completions branch is dead
# code, disasm/PRG/prg011.asm:2010). Beating an airship routes through the king's
# room and does `INC World_Num` (disasm/PRG/prg030.asm:2742). So "World N airship
# cleared" == World_Num has advanced to >= N. World_Num = $0727 (disasm/smb3.asm:2031).
WORLD_NUM = 0x0727
PLAYER_RESCUE_PRINCESS = 0x078D  # non-zero after Bowser beaten -> victory
PLAYER_LIVES = 0x0736          # Mario lives (grant "Extra Life")

DOMAIN = "System Bus"

# Highest world that has a Koopaling airship (World 8's climax is Bowser, the goal).
MAX_AIRSHIP_WORLD = 7

# Super Mario Bros. 3 (U) (PRG1) [!] — the supported ROM.
# Headered .nes md5, kept for reference / a future settings hash-check:
SMB3_FILE_MD5 = "86d1982fea7342c0af9679ddf3869d8d"
# Headerless ROM CRC32 2e6301ed / SHA1 bb894d104c796f69ba16587eb66c0275f5c2fc02.

# ROM identification signature: the ASCII string "SUPER MARIO 3" is baked into the
# PRG ROM. The "PRG ROM" domain has no iNES header, so this sits at PRG offset
# 0x3FFE3. We read just these bytes (not the whole 256KB) — the connector returns
# each response as one socket line and asyncio's readline caps at ~64KB, so a full
# ROM read overruns the buffer.
_SIG_ADDR = 0x3FFE3
_SIG_BYTES = b"SUPER MARIO 3"


def _airship_location_ids() -> dict:
    """world number (1..7) -> AP location id, for airships."""
    return {data.code: BASE_ID + data.code for data in location_table.values()}


def cmd_smb3_debug(self: "BizHawkClientCommandProcessor", state: str = "") -> None:
    """Toggle SMB3 debug logging (per-pass heartbeat of World_Num/rescue/lives). Usage: /smb3_debug [on|off]"""
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
    # No patch file in the POC; we identify the ROM by signature in validate_rom.
    patch_suffix = None

    def __init__(self) -> None:
        super().__init__()
        # How many received items we've already applied to RAM (dedup).
        self.applied_items = 0
        # False until we've baselined applied_items against the server's
        # re-sent item list on (re)connect — see game_watcher.
        self.synced = False
        # One-time "watcher is running" announcement guard.
        self._watcher_announced = False
        # Verbose debug logging (per-pass heartbeat of World_Num/rescue/lives).
        # Off by default — toggle at runtime with the /smb3_debug client command.
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
            logger.warning("SMB3 client active: watching RAM. Beat an airship "
                           "(or Bowser) to send checks.")
            self._watcher_announced = True

        try:
            world_num, rescue, lives = await read(ctx.bizhawk_ctx, [
                (WORLD_NUM, 1, DOMAIN),
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
            logger.info(
                "SMB3 heartbeat #%d: World_Num=$%02X (world %d) rescue=$%02X lives=$%02X",
                self._pass, world_num[0], world_num[0] + 1, rescue[0], lives[0])

        try:
            # --- airship checks via World_Num ---
            # Beating World N's airship advances World_Num to N (0-indexed value
            # N, i.e. "now on World N+1"). So "World k airship cleared" once
            # World_Num >= k. Self-heals missed passes; for linear play this is
            # exact. (Caveat: warp-whistle skips would mark skipped airships as
            # checked without beating them — acceptable for the POC.)
            reached = world_num[0]  # 0-indexed current world
            checked: List[int] = []
            for world, loc_id in _airship_location_ids().items():
                if world <= MAX_AIRSHIP_WORLD and reached >= world \
                        and loc_id not in ctx.locations_checked:
                    checked.append(loc_id)
            if checked:
                logger.warning("SMB3: World_Num=%d -> sending airship checks for %s",
                               reached, sorted(checked))
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
