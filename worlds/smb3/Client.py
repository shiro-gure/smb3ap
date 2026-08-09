"""BizHawk client for Super Mario Bros. 3.

The client attaches to an SMB3 US (PRG1) ROM — `Super Mario Bros. 3 (U) (PRG1) [!]`
(No-Intro Rev A) — running in BizHawk via the generic connector, reads RAM to detect
progress, and writes received items straight into RAM. This is the exact revision the
captainsouthbird disassembly reassembles to, so the disassembly is authoritative for
these addresses.

The world can now emit an `.apsmb3` patch (base patch = the on-map checkmark; ROM.py
+ generate_output), which the launcher/client applies before booting BizHawk. The
client accepts both an unpatched vanilla ROM and an .apsmb3-patched one — detection is
identical either way (the checkmark is a CHR-only change).

The ROM is identified by an internal signature (below), so the client also tolerates
PRG0, but PRG1 is the supported/disassembly-matching revision.

Addresses are CPU-space, read through the "System Bus" domain, which spans work RAM
($0727, $0736, $078D) uniformly on the NES core.
"""

import logging
from typing import TYPE_CHECKING, AbstractSet, Optional

from NetUtils import ClientStatus

from worlds._bizhawk.client import BizHawkClient

from .Locations import airship_location_id, fortress_location_ids, location_name_to_id
from .Locations import level_location_name
from .panels import PANELS

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext, BizHawkClientCommandProcessor

logger = logging.getLogger("SMB3")

# Build/revision stamp — bump on each client change so the loaded build is
# unambiguous in the log (catches a stale apworld on the play machine).
CLIENT_REV = "2026-08-08-hub-persist"

# --- RAM addresses (resolved from disasm/, authoritative on PRG1) ---
# Airships have NO persistent completion bit (the airship's Map_Completions branch
# is dead code, disasm/PRG/prg011.asm:2010). We detect a boss defeat in-level:
#
# - Level_ObjectID ($0671-$0678, 8 slots): "all active actor IDs"
#   (disasm/smb3.asm:1881). The Koopaling boss is OBJ_BOSS_KOOPALING = $0E
#   (disasm/smb3.asm:3283; dispatched via this ID, disasm/PRG/prg001.asm:84). So
#   "$0E present in these 8 bytes" == a Koopaling is on screen (we're in the fight).
# - Level_GetWandState ($07BD): the post-defeat state machine. 0 = boss alive;
#   1 = final hit landed / Koopaling flies off (= DEFEATED); 2-7 = wand/vanish/fall
#   sequence (disasm/PRG/prg001.asm:3061-3073, :3708). So >= 1 == boss beaten.
# - World_Num ($0727): current world index, 0 = World 1 (disasm/smb3.asm:2031).
#   The airship just beaten = World_Num + 1 (World_Num increments later, in the
#   king's room, disasm/PRG/prg030.asm:2742 — not yet during the fight).
LEVEL_OBJECTID = 0x0671        # 8 slots; scan for the on-screen Koopaling
LEVEL_OBJECTID_LEN = 8
OBJ_BOSS_KOOPALING = 0x0E      # airship Koopaling boss
LEVEL_GETWANDSTATE = 0x07BD    # 0 = Koopaling alive; >= 1 = Koopaling defeated
WORLD_NUM = 0x0727             # current world index (0 = World 1); for which-world
PLAYER_RESCUE_PRINCESS = 0x078D  # non-zero after Bowser beaten -> victory
PLAYER_LIVES = 0x0736          # Mario lives (grant "Extra Life")

# Fortress clear signal — the persistent Map_Completions panel bit.
# EVERY alive level completion (normal level, fortress-by-Boom-Boom, AND
# fortress-by-secret-exit) funnels through Map_MarkLevelComplete, which sets the
# cleared panel's bit in Map_Completions (disasm/PRG/prg011.asm:1849,4628). So a
# 0->1 bit flip there == a level/fortress panel was just cleared, regardless of how.
# To tell a FORTRESS clear from a normal level, check World_Map_Tile: the game sets
# it to rubble ($60/$E3) for a fortress immediately before marking the panel
# (disasm/PRG/prg011.asm:1845-1849; the same test the game uses, :4632-4637). This
# bit is sticky/persistent (flips on the map during the clear animation), so we poll
# at the normal rate and diff pass-to-pass — no adaptive polling needed. (Lock/bridge
# FX bits also flip in Map_Completions, but never on a rubble tile, so they're
# excluded by the tile gate; disasm/PRG/prg010.asm:1550-1567.)
MAP_COMPLETIONS = 0x7D00       # $7D00-$7D3F Mario completed-panel bitfield
MAP_COMPLETIONS_LEN = 0x40
WORLD_MAP_TILE = 0x00E5        # tile under the player on the world map
# Player overworld position (per-player arrays; player 0 = Mario). Logged in the
# debug heartbeat to read exact hub coordinates while standing on a pipe.
WORLD_MAP_X = 0x0079           # map X (col = X>>4)
WORLD_MAP_Y = 0x0075           # map Y (row = (Y-$10)>>4)
WORLD_MAP_XHI = 0x0077         # map screen (high X)
FORT_RUBBLE_TILES = (0x60, 0xE3)  # TILE_FORTRUBBLE / TILE_ALTRUBBLE => fortress

# A completed panel's identity is (world, byte_offset, bit_mask), where byte_offset
# is exactly the Map_Completions BYTE INDEX the game writes — Map_MarkLevelComplete
# stores at Map_Completions[(XHi<<4)|(X>>4)] (disasm/PRG/prg011.asm:4602-4630) — so
# the index of a flipped byte already IS the panel offset; we don't need to read the
# player's map position. A save-state reload swaps the whole bitfield at once; if
# more than this many bits flip 0->1 in one pass, treat it as a bulk load and
# re-baseline instead of crediting (BUG-001 guard).
SAVE_STATE_FLIP_THRESHOLD = 3  # >this many 0->1 flips in one pass = a bulk load

DOMAIN = "System Bus"

# Watcher poll intervals (seconds). Normal is the BizHawk default; we tighten it
# only while a Koopaling is on screen, so the brief defeat state is caught.
POLL_NORMAL = 0.5
POLL_BOOST = 0.1

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


# --- Detection-policy helpers (pure; unit-tested in test/test_fortress.py).
# Location id/name math lives in Locations.py and is imported above. ---

def next_unchecked_fortress(world: int, checked: "AbstractSet[int]") -> Optional[int]:
    """The next fortress location id for `world` not already in `checked`, in
    clear-order — or None if all of the world's fortresses are already checked.
    Count-based: the Nth fortress cleared in a world maps to that world's Nth
    fortress location."""
    for loc_id in fortress_location_ids(world):
        if loc_id not in checked:
            return loc_id
    return None


def fortress_cleared(prev: "Optional[bytes]", cur: "bytes",
                     world_map_tile: int) -> bool:
    """True iff a FORTRESS panel was just cleared this watcher pass.

    A fortress clear (by Boom Boom OR a secret exit) sets a Map_Completions panel
    bit while the player stands on a rubble tile. So: some bit in `cur` went 0->1
    vs `prev`, AND `world_map_tile` is a fortress rubble tile. `prev` None (first
    pass / just connected) is a baseline, never a clear. Pure — unit-tested."""
    if prev is None:
        return False
    if world_map_tile not in FORT_RUBBLE_TILES:
        return False
    # Any bit that is set in cur but was clear in prev (0 -> 1).
    for p, c in zip(prev, cur):
        if c & ~p:
            return True
    return False


def panel_cleared(prev: "Optional[bytes]", cur: "bytes"):
    """Return the list of (byte_offset, bit_mask) panels whose Map_Completions bit
    just went 0->1 this pass — the identity Map_MarkLevelComplete uses. Used for
    per-level / toad-house detection (the Level Checks option).

    Returns (flips, bulk): `flips` is the list of newly-set (offset, bit); `bulk` is
    True when an implausibly large number of bits flipped at once, i.e. a save-state
    reload / bulk RAM swap (BUG-001 guard) — the caller should re-baseline WITHOUT
    crediting. `prev` None (first pass) yields ([], False): a baseline, never a clear.
    Pure — unit-tested."""
    if prev is None:
        return [], False
    flips = []
    for byte_offset, (p, c) in enumerate(zip(prev, cur)):
        newly = c & ~p
        if newly:
            for bit in (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01):
                if newly & bit:
                    flips.append((byte_offset, bit))
    if len(flips) > SAVE_STATE_FLIP_THRESHOLD:
        return [], True  # bulk load — re-baseline, don't credit
    return flips, False


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
    # .apsmb3 patches (base patch = on-map checkmark, + future hooks) are applied
    # by the launcher/client, which then boots BizHawk with the patched ROM. We
    # still identify the ROM by the "SUPER MARIO 3" signature in validate_rom
    # (unchanged by the CHR-only checkmark patch), so the client accepts BOTH an
    # unpatched vanilla ROM (Any%/Vanilla) and an .apsmb3-patched ROM.
    patch_suffix = ".apsmb3"

    def __init__(self) -> None:
        super().__init__()
        # True while a Koopaling is on screen and we've boosted the poll rate.
        self._boss_active = False
        # True once we've handled the current on-screen boss encounter (credited
        # or stood down); prevents re-boost/re-log while the boss object lingers
        # post-defeat. Cleared when no boss is on screen.
        self._boss_handled = False
        # Previous Map_Completions snapshot, to detect a 0->1 panel-bit flip
        # (fortress clear). None until baselined on the first pass after connect.
        self._prev_completions: Optional[bytes] = None
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
        ctx.watcher_timeout = POLL_NORMAL  # boosted dynamically during boss fights
        # Register the /smb3_debug command (idempotent across re-validations).
        if "smb3_debug" not in ctx.command_processor.commands:
            ctx.command_processor.commands["smb3_debug"] = cmd_smb3_debug
        return True

    async def _send_check(self, ctx: "BizHawkClientContext", loc_id: int) -> None:
        """Send a location check and log it the standard AP way (mm2 pattern):
        record it in ctx.locations_checked (so it survives reconnects) and print a
        human-readable 'New Check: <name> (n/total)' confirmation."""
        ctx.locations_checked.add(loc_id)
        name = ctx.location_names.lookup_in_game(loc_id)
        total = len(ctx.missing_locations) + len(ctx.checked_locations)
        logger.info("New Check: %s (%d/%d)", name, len(ctx.locations_checked), total)
        await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [loc_id]}])

    def on_package(self, ctx: "BizHawkClientContext", cmd: str, args: dict) -> None:
        # Re-baseline item dedup whenever a fresh connection is established, since
        # the server re-sends the full received-items list on Connected.
        if cmd == "Connected":
            self.synced = False
            self._watcher_announced = False
            # Reset boss-fight state; poll rate restores to normal next pass.
            self._boss_active = False
            self._boss_handled = False
            self._prev_completions = None
            ctx.watcher_timeout = POLL_NORMAL

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

        # One-time proof the watcher is actually running. Includes the build rev
        # so a stale apworld on the play machine is obvious in the log.
        if not self._watcher_announced:
            logger.warning("SMB3 client active (build %s): watching RAM. Beat an "
                           "airship, fortress, or Bowser to send checks.", CLIENT_REV)
            self._watcher_announced = True

        try:
            object_ids, wand_state, completions, world_map_tile, world_num, \
                rescue, lives, map_x, map_y, map_xhi = await read(ctx.bizhawk_ctx, [
                    (LEVEL_OBJECTID, LEVEL_OBJECTID_LEN, DOMAIN),
                    (LEVEL_GETWANDSTATE, 1, DOMAIN),
                    (MAP_COMPLETIONS, MAP_COMPLETIONS_LEN, DOMAIN),
                    (WORLD_MAP_TILE, 1, DOMAIN),
                    (WORLD_NUM, 1, DOMAIN),
                    (PLAYER_RESCUE_PRINCESS, 1, DOMAIN),
                    (PLAYER_LIVES, 1, DOMAIN),
                    (WORLD_MAP_X, 1, DOMAIN),
                    (WORLD_MAP_Y, 1, DOMAIN),
                    (WORLD_MAP_XHI, 1, DOMAIN),
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

        koopaling_on_screen = OBJ_BOSS_KOOPALING in object_ids

        # Heartbeat (debug only): every N passes, prove we're alive and show what
        # we read. Toggle with /smb3_debug. Off by default to avoid log spam.
        self._pass += 1
        if self.debug and self._pass % 30 == 1:
            completions_set = sum(bin(b).count("1") for b in completions)
            logger.info(
                "SMB3 heartbeat #%d: World_Num=$%02X (world %d) koopaling=%s "
                "wand_state=$%02X map_tile=$%02X map_X=$%02X map_Y=$%02X map_XHi=$%02X "
                "(col %d,row %d) completions_set=%d rescue=$%02X lives=$%02X",
                self._pass, world_num[0], world_num[0] + 1, koopaling_on_screen,
                wand_state[0], world_map_tile[0], map_x[0], map_y[0], map_xhi[0],
                map_x[0] >> 4, (map_y[0] - 0x10) >> 4 if map_y[0] >= 0x10 else 0,
                completions_set, rescue[0], lives[0])

        try:
            # --- adaptive poll-rate boost while the Koopaling is on screen ---
            # The airship clear signal (Level_GetWandState) is brief, so boost the
            # poll rate during the fight. The Koopaling lingers after defeat, so
            # latch per-encounter (_boss_handled) to boost+log only once and not
            # re-trigger until it leaves. (Fortresses use the sticky Map_Completions
            # bit and don't need a boost.)
            if not koopaling_on_screen:
                # No Koopaling present: clean slate; ensure normal poll rate.
                if self._boss_active or self._boss_handled:
                    self._boss_active = False
                    self._boss_handled = False
                    ctx.watcher_timeout = POLL_NORMAL
            elif not self._boss_handled and not self._boss_active:
                self._boss_active = True
                ctx.watcher_timeout = POLL_BOOST
                logger.info("SMB3: Koopaling on screen — boosting poll rate.")

            # --- airship check via the Koopaling defeat state ---
            # Level_GetWandState >= 1 == Koopaling beaten; world = World_Num + 1
            # (World_Num increments later, in the king's room). Dedup via
            # checked_locations. Latch so the lingering Koopaling doesn't refire.
            if koopaling_on_screen and not self._boss_handled and wand_state[0] >= 1:
                world = world_num[0] + 1
                loc_id = airship_location_id(world)
                already = ctx.checked_locations | ctx.locations_checked
                if world <= MAX_AIRSHIP_WORLD and loc_id is not None \
                        and loc_id not in already:
                    logger.info("SMB3: World %d Koopaling defeated (wand_state=$%02X)",
                                world, wand_state[0])
                    await self._send_check(ctx, loc_id)
                self._boss_handled = True
                self._boss_active = False
                ctx.watcher_timeout = POLL_NORMAL

            # --- fortress check via the Map_Completions panel-bit diff ---
            # A fortress clear (Boom Boom OR secret exit) flips a Map_Completions
            # panel bit while the player is on a rubble tile. fortress_cleared()
            # detects that 0->1 transition; we credit the current world's next
            # uncredited fortress (count-based, clear-order). The bit is sticky, but
            # we only act on the transition, so it fires once. Baseline _prev on
            # connect so a connect-while-already-cleared doesn't retro-fire.
            if fortress_cleared(self._prev_completions, completions, world_map_tile[0]):
                world = world_num[0] + 1  # World_Num not incremented for fortresses
                already = ctx.checked_locations | ctx.locations_checked
                loc_id = next_unchecked_fortress(world, already)
                if loc_id is not None:
                    logger.info("SMB3: World %d fortress cleared (map_tile=$%02X)",
                                world, world_map_tile[0])
                    await self._send_check(ctx, loc_id)
                else:
                    logger.warning("SMB3: World %d fortress cleared but no unchecked "
                                   "fortress location remains (map_tile=$%02X).",
                                   world, world_map_tile[0])

            # --- per-level / toad-house checks (the Level Checks option) ---
            # Any Map_Completions bit that flipped 0->1 this pass is a cleared panel;
            # its (world, byte_offset, bit) identifies which. We look it up in the
            # generated PANELS table and, if it's a level/toad-house location the
            # server knows about for this slot (i.e. the option is on), send it.
            # Fortress panels aren't in PANELS, so they never double-fire here.
            flips, bulk = panel_cleared(self._prev_completions, completions)
            if bulk:
                logger.info("SMB3: bulk Map_Completions change (save-state/sync) — "
                            "re-baselining without crediting.")
            else:
                world = world_num[0] + 1
                known = ctx.missing_locations | ctx.checked_locations | ctx.locations_checked
                for offset, bit in flips:
                    panel = PANELS.get((world, offset, bit))
                    if panel is None:
                        continue  # not a level/toad-house panel (e.g. a fortress)
                    kind, name = panel
                    loc_name = (level_location_name(world, name)
                                if kind == "level" else name)
                    loc_id = location_name_to_id.get(loc_name)
                    if loc_id is not None and loc_id in known \
                            and loc_id not in ctx.locations_checked:
                        logger.info("SMB3: %s cleared (offset=$%02X bit=$%02X)",
                                    loc_name, offset, bit)
                        await self._send_check(ctx, loc_id)
            self._prev_completions = completions

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
