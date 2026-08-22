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
from .Locations import BASE_ID, access_item_codes, access_item_name, gated_panels
from .panels import PANELS, FORTRESS_PANEL_BITS

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext, BizHawkClientCommandProcessor

logger = logging.getLogger("SMB3")

# Build/revision stamp — bump on each client change so the loaded build is
# unambiguous in the log (catches a stale apworld on the play machine).
CLIENT_REV = "2026-08-22-access-debug"

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
# Map_RepaintReq: a free RAM byte the hub ROM patch (make_hub.py Part 3) polls on the
# idle world-map loop — when nonzero it re-runs the map-load tail to repaint checkmarks
# (keeping our Map_Completions bits) so client-written checkmarks appear right after
# travel, without the player entering a level. LevLoad_Unused1 ($0701), unused in
# vanilla. Harmless on an unpatched ROM (nothing reads it).
MAP_REPAINT_REQ = 0x0701
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

# --- Roaming map-enemy (Hammer/Boomerang/Heavy/Fire Bro, W7 plant) persistence -----
# These wandering overworld enemies are NOT tracked by Map_Completions and have no
# defeat bitfield. Defeating one just blanks its slot in Map_Objects_IDs ($7F15-$7F22)
# to MAPOBJ_EMPTY ($00) in SRAM (disasm/PRG/prg011.asm:2037-2038). That state survives
# a normal level-return reload, but the one-time "enter world" path re-runs Map_Init,
# which repopulates Map_Objects_IDs fresh from the world's ROM object list
# (disasm/PRG/prg011.asm:141-158) — reviving every defeated bro. The hub forces that
# path on every arrival (HubReturn / pipe-entry both JMP PRG030_84A0), so the client
# must remember which object SLOTS were defeated per world and re-blank them on arrival.
#
# Each bro occupies its own slot index (0-13, same index across the parallel object
# arrays); a world can hold up to 3 (World 4/5/6). Slot 0 = HELP hand, slot 1 = Airship
# — neither is a defeatable bro, so we only ever record/blank BRO-valued slots.
MAP_OBJECT_IDS = 0x7F15        # $7F15-$7F22 live map-object IDs (0 = empty/defeated)
MAP_OBJECT_IDS_LEN = 14
# The roaming, defeat-and-gone map enemies (disasm/smb3.asm:2814-2818).
MAP_BRO_IDS = frozenset({0x03, 0x04, 0x05, 0x06, 0x07})  # Hammer/Boomerang/Heavy/Fire/W7Plant

# --- Level Access (the level_access option) — client-written "unlocked" bitfield -----
# When level_access is on, the hub ROM's entry-gate hook (at the A-press enter choke point
# PRG010_CEA7) refuses to ENTER a panel whose bit is SET in a per-panel LOCKED bitfield.
# The client owns that state: it tracks which "… Access" items it has received and, on each
# world's map, writes that world's LOCKED bits — indexed EXACTLY like Map_Completions:
# byte_offset = (World_Map_XHi<<4)|(World_Map_X>>4), bit = the panel's row bit — to a free
# WRAM region. Polarity: 1 = LOCKED. A bit is set ONLY for a gated panel whose Access item
# isn't received yet; everything else (hub pipes, non-gated spade/king/pipe-maze panels,
# unlocked panels) stays 0 = enterable, so the gate never blocks a panel we don't model.
#
# Home: $054B-$0586 is unused in the "$05xx World Map context" page (disasm/smb3.asm:1504;
# no code references it — grep-confirmed). It's a context-union page (clobbered inside a
# level/bonus game), but the client rewrites it every OVERWORLD pass and the hook only
# reads it on the overworld at entry, so that's fine.
#
# Default-OPEN safety: the ROM hook can't know if level_access is on, so a 1-byte ACTIVE
# flag gates it. The hook only enforces when the flag is nonzero; the client sets it to 1
# ONLY when level_access is enabled (and never on a level_access-off game), so entry is
# never wrongly blocked. And since all-zero = all-open, a fresh/garbage region is safe.
# Highest offset a real gated panel uses is 0x28 (World 8), so 0x30 bytes covers it.
MAP_UNLOCK_FLAG = 0x054B       # 1 = entry-gate active (client-set when level_access on)
MAP_UNLOCK_BITS = 0x0550       # LOCKED bitfield, indexed like Map_Completions (1=locked)
MAP_UNLOCK_BITS_LEN = 0x30     # 48 bytes ($0550-$057F); covers offsets 0..0x2F (max real 0x28)

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


# --- Client-driven checkmark persistence across hub travel --------------------
# SMB3's Map_Completions ($7D00-$7D3F) is a single, world-AGNOSTIC 128-byte bitfield
# (indexed only by on-screen panel position), and the game wipes it on every world
# load. There is no free persistent ROM RAM to make it per-world, so persisting the
# raw bitfield across travel would bleed one world's checkmarks onto another world's
# panels. Instead the CLIENT is the persistent per-world store: it knows which level
# locations are checked, so on each world's map it writes exactly THAT world's
# checkmark bits into Map_Completions. The ROM's own repaint (Map_Reload_with_
# Completions, run on the next map reload — e.g. entering a level and returning)
# then draws them; with the PR 5c ROM patch a level bit paints the enterable "$16"
# checkmark tile, so re-entry/walk-through still work.
#
# Reverse index: world -> [(byte_offset, bit_mask, location_id)] for panels that carry
# a stable per-location bit and must be REDRAWN after a repaint wipes Map_Completions —
# i.e. LEVELS and TOAD HOUSES (both keyed by a fixed (world,offset,bit) in PANELS with a
# location id). Fortresses are handled separately below (count-based, no per-location bit).
_DRAWABLE_PANEL_BITS: "dict[int, list[tuple[int, int, int]]]" = {}
for (_w, _off, _bit), (_kind, _pname) in PANELS.items():
    if _kind == "level":
        _lid = location_name_to_id.get(level_location_name(_w, _pname))
    elif _kind == "toad_house":
        _lid = location_name_to_id.get(_pname)
    else:
        continue
    if _lid is not None:
        _DRAWABLE_PANEL_BITS.setdefault(_w, []).append((_off, _bit, _lid))


def desired_completion_bytes(world: int, checked: "AbstractSet[int]",
                             cur: "bytes") -> "Optional[bytearray]":
    """Return a new 64-byte Map_Completions image for `world` with the checkmark bit
    SET for every checked panel in that world (levels, toad houses, and fortresses),
    starting from `cur` (so we only ADD bits, never clear the game's own live state).
    Returns None if nothing needs to change (no missing bits) — caller skips the write.

    Levels/toad houses have a stable (offset,bit) per checked location. Fortresses are
    count-based: we light the first N fortress panels of the world, where N = how many
    of that world's fortress locations are checked (there is no per-location fortress
    bit; the map only needs the right NUMBER of fort panels drawn). We never light more
    panels than the world actually has. Only sets bits. Pure — unit-tested."""
    out = bytearray(cur)
    changed = False
    for offset, bit, loc_id in _DRAWABLE_PANEL_BITS.get(world, ()):
        if loc_id in checked and offset < len(out) and not (out[offset] & bit):
            out[offset] |= bit
            changed = True
    # Fortresses: count checked fort locations for this world, light that many panels.
    fort_panels = FORTRESS_PANEL_BITS.get(world)
    if fort_panels:
        n_checked = sum(1 for lid in fortress_location_ids(world) if lid in checked)
        for offset, bit in fort_panels[:n_checked]:
            if offset < len(out) and not (out[offset] & bit):
                out[offset] |= bit
                changed = True
    return out if changed else None


def newly_defeated_bro_slots(prev: "Optional[bytes]", cur: "bytes"):
    """Slot indices whose map-object ID went from a BRO id (alive) to $00 (defeated)
    this pass — i.e. a roaming enemy the player just cleared. `prev` None (first pass)
    yields [] (a baseline, never a defeat). Ignores non-bro transitions (e.g. a slot
    naturally emptying, or a bro converting to a coin ship). Pure — unit-tested."""
    if prev is None:
        return []
    out = []
    for i in range(min(len(prev), len(cur))):
        if prev[i] in MAP_BRO_IDS and cur[i] == 0x00:
            out.append(i)
    return out


def reblank_defeated_slots(defeated: "AbstractSet[int]", cur: "bytes"):
    """For every recorded-defeated slot that currently holds a live BRO id (i.e.
    Map_Init just respawned it after hub travel), produce the (slot_index, new_id=$00)
    writes needed to re-clear it. Returns [] when nothing needs re-blanking (steady
    state), so the caller can skip the write. Only touches slots that came back as a
    bro — never disturbs a coin ship, N-Spade, or a legitimately-alive object. Pure."""
    writes = []
    for slot in sorted(defeated):
        if slot < len(cur) and cur[slot] in MAP_BRO_IDS:
            writes.append(slot)
    return writes


# Reverse map for level access: received Access-item id -> (world, byte_offset, bit_mask).
# Built once from the canonical gated-panel table + Access-item codes (Locations.py).
_ACCESS_ID_TO_PANEL: "dict[int, tuple[int, int, int]]" = {}
for (_w, _off, _bit, _base) in gated_panels():
    _aid = BASE_ID + access_item_codes[access_item_name(_base)]
    _ACCESS_ID_TO_PANEL[_aid] = (_w, _off, _bit)

# Per-world index of the panels that can be unlocked: world -> [(offset, bit), ...].
_UNLOCKABLE_BY_WORLD: "dict[int, list[tuple[int, int]]]" = {}
for (_w, _off, _bit, _base) in gated_panels():
    _UNLOCKABLE_BY_WORLD.setdefault(_w, []).append((_off, _bit))

# (world, offset, bit) -> a short display name for logs / the /smb3_unlocked command.
# "World 1 Level 1-1" / "World 1 Toad House 2" / "World 3 Fortress 1" (drops " - Cleared").
_PANEL_DISPLAY_NAME: "dict[tuple[int, int, int], str]" = {}
# (world, offset, bit) -> the panel's clear-CHECK location id (to mark cleared ones).
_PANEL_CHECK_LOCID: "dict[tuple[int, int, int], int]" = {}
for (_w, _off, _bit, _base) in gated_panels():
    _PANEL_DISPLAY_NAME[(_w, _off, _bit)] = _base.replace(" - Cleared", "")
    _lid = location_name_to_id.get(_base)
    if _lid is not None:
        _PANEL_CHECK_LOCID[(_w, _off, _bit)] = _lid


_MAP_COMPLETE_Y = (0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80)
_MAP_COMPLETE_BIT = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)


def _row_bit_from_y(world_map_y: int):
    """The Map_CompleteBit for a player's World_Map_Y, matching the ROM (prg011.asm:
    4586-4599): find Y in Map_CompleteY -> that row's bit; no match -> bottom row ($01)."""
    for i, yv in enumerate(_MAP_COMPLETE_Y):
        if world_map_y == yv:
            return _MAP_COMPLETE_BIT[i]
    return _MAP_COMPLETE_BIT[7]


def desired_lock_bytes(world: int, unlocked_panels: "AbstractSet[tuple]",
                       cur: "bytes"):
    """Return the LOCKED bitfield image for `world` (polarity 1 = LOCKED), or None if it
    already matches `cur`. A bit is SET only for a GATED panel in this world whose Access
    item has NOT been received. Every other panel (non-gated spade/king/pipe-maze transit,
    hub pipes, already-unlocked panels) stays 0 = enterable — so the gate can never block a
    panel we don't explicitly model as gated-and-locked.

    Authoritative: built from scratch each pass (start all-open) and compared to `cur`.
    Pure — unit-tested."""
    out = bytearray(MAP_UNLOCK_BITS_LEN)
    for offset, bit in _UNLOCKABLE_BY_WORLD.get(world, ()):
        if (world, offset, bit) not in unlocked_panels and offset < len(out):
            out[offset] |= bit  # gated but not unlocked -> LOCKED
    return out if bytes(out) != bytes(cur[:MAP_UNLOCK_BITS_LEN]) else None


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


def cmd_smb3_unlocked(self: "BizHawkClientCommandProcessor", world: str = "") -> None:
    """List which levels you've UNLOCKED (level_access). Usage: /smb3_unlocked [world#].
    Shows unlocked panels grouped by world; a * marks ones you've already cleared."""
    # self.output(...) writes straight to the client text window (logger.info may be
    # filtered by the UI), so command results always print.
    if getattr(self.ctx, "game", None) != SMB3Client.game:
        self.output("This command only works while playing Super Mario Bros. 3.")
        return
    handler = getattr(self.ctx, "client_handler", None)
    if handler is None:
        self.output("SMB3 client not ready yet — connect and load the ROM first.")
        return
    if not getattr(handler, "_level_access", False):
        self.output("level_access is OFF for this slot — every level is enterable.")
        return
    unlocked = handler._unlocked_panels
    if not unlocked:
        self.output("No levels unlocked yet — find an '... Access' item to open one.")
        return
    checked = self.ctx.checked_locations | self.ctx.locations_checked
    want_world = None
    if world.strip():
        try:
            want_world = int(world.strip())
        except ValueError:
            self.output(f"'{world.strip()}' is not a world number.")
            return
    by_world: "dict[int, list[str]]" = {}
    for panel in unlocked:
        w = panel[0]
        if want_world is not None and w != want_world:
            continue
        name = _PANEL_DISPLAY_NAME.get(panel, str(panel))
        loc_id = _PANEL_CHECK_LOCID.get(panel)
        done = loc_id is not None and loc_id in checked
        by_world.setdefault(w, []).append(("* " if done else "  ") + name)
    if not by_world:
        self.output("Nothing unlocked" + (f" in World {want_world}." if want_world else "."))
        return
    self.output("Unlocked levels (* = already cleared):")
    for w in sorted(by_world):
        self.output(f"  World {w}: " + ", ".join(sorted(by_world[w])))


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
        # Roaming-enemy (Hammer/Boomerang/Heavy/Fire Bro, W7 plant) persistence:
        # per-world set of map-object SLOT indices the player has defeated, so we can
        # re-blank them after hub travel re-runs Map_Init and respawns them. Keyed by
        # 1-indexed world (World_Num+1). Persists for the client session.
        self._defeated_bro_slots: "dict[int, set[int]]" = {}
        # (world, Map_Objects_IDs snapshot) from the previous pass, to detect a
        # bro->empty defeat transition — only meaningful when the world is unchanged.
        self._prev_objects_world: "tuple[Optional[int], Optional[bytes]]" = (None, None)
        # Level access (level_access option): panels unlocked by received "… Access"
        # items, as a set of (world, offset, bit). Rebuilt each pass from items_received
        # (idempotent), so it needs no connect reset. The client writes the current
        # world's unlocked bitfield to RAM for the entry-gate ROM hook to read.
        self._unlocked_panels: "set[tuple[int, int, int]]" = set()
        # Panels we've already announced as unlocked, so each unlock logs exactly once.
        self._logged_unlocks: "set[tuple[int, int, int]]" = set()
        # Whether this slot enabled level_access (from slot_data). When True the client
        # arms the ROM entry-gate (writes the ACTIVE flag) and drives the unlock bitfield.
        self._level_access = False
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
        # Need slot_data to know if level_access is on (so we arm the entry-gate hook).
        ctx.want_slot_data = True
        ctx.watcher_timeout = POLL_NORMAL  # boosted dynamically during boss fights
        # Register the /smb3_* commands (idempotent across re-validations).
        if "smb3_debug" not in ctx.command_processor.commands:
            ctx.command_processor.commands["smb3_debug"] = cmd_smb3_debug
        if "smb3_unlocked" not in ctx.command_processor.commands:
            ctx.command_processor.commands["smb3_unlocked"] = cmd_smb3_unlocked
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
            # Re-baseline the map-object snapshot (so a connect mid-map doesn't read a
            # populated table as a fresh defeat). Keep _defeated_bro_slots — it's the
            # client-local record of cleared bros and has no server-side equivalent.
            self._prev_objects_world = (None, None)
            # Read level_access from slot_data (arms the entry-gate ROM hook).
            slot_data = args.get("slot_data") or {}
            self._level_access = bool(slot_data.get("level_access", 0))
            if self._level_access:
                logger.info("SMB3: level_access is ON — entry gating active.")
            ctx.watcher_timeout = POLL_NORMAL

    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        from worlds._bizhawk import read, guarded_write, RequestFailedError

        # Ensure the /smb3_* commands are registered (belt-and-suspenders: validate_rom
        # registers them too, but re-do it here so they're present even if the watcher
        # starts before/without a fresh validate_rom).
        if "smb3_unlocked" not in ctx.command_processor.commands:
            ctx.command_processor.commands["smb3_unlocked"] = cmd_smb3_unlocked
        if "smb3_debug" not in ctx.command_processor.commands:
            ctx.command_processor.commands["smb3_debug"] = cmd_smb3_debug

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
                rescue, lives, map_x, map_y, map_xhi, map_objects, unlock_bits, \
                unlock_flag = await read(ctx.bizhawk_ctx, [
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
                    (MAP_OBJECT_IDS, MAP_OBJECT_IDS_LEN, DOMAIN),
                    (MAP_UNLOCK_BITS, MAP_UNLOCK_BITS_LEN, DOMAIN),
                    (MAP_UNLOCK_FLAG, 1, DOMAIN),
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
            # Track whether a LEVEL panel flipped this pass. On a fresh level clear the
            # game writes the vanilla (non-enterable) completion tile immediately; our
            # enterable "$16" tile is only painted by Map_Reload_with_Completions on the
            # NEXT map reload. So we request a repaint this pass (below) to swap the tile
            # right away — otherwise the just-cleared level can't be re-entered until some
            # other reload happens (BUG-B).
            level_flip_seen = False
            if not bulk:
                world = world_num[0] + 1
                known = ctx.missing_locations | ctx.checked_locations | ctx.locations_checked
                for offset, bit in flips:
                    panel = PANELS.get((world, offset, bit))
                    if panel is None:
                        continue  # not a level/toad-house panel (e.g. a fortress)
                    kind, name = panel
                    if kind == "level":
                        level_flip_seen = True
                    loc_name = (level_location_name(world, name)
                                if kind == "level" else name)
                    loc_id = location_name_to_id.get(loc_name)
                    if loc_id is not None and loc_id in known \
                            and loc_id not in ctx.locations_checked:
                        logger.info("SMB3: %s cleared (offset=$%02X bit=$%02X)",
                                    loc_name, offset, bit)
                        await self._send_check(ctx, loc_id)
            self._prev_completions = completions

            # --- persist this world's checkmarks (client-driven) ---
            # Travel wipes Map_Completions (the game clears it on every world load) and
            # the bitfield is world-agnostic, so we re-assert THIS world's cleared panel
            # bits (levels, toad houses, fortresses) from the AP checked set. We only ADD
            # bits (never clear), guard the write on the value we just read (so a
            # concurrent game write aborts it harmlessly), and re-baseline
            # _prev_completions to the written image so the bits we set aren't
            # mis-detected as a fresh 0->1 clear next pass. Bulk passes are skipped (we
            # don't fight a save-state swap).
            #
            # We also request a repaint (MAP_REPAINT_REQ) when EITHER we added bits OR a
            # level just flipped this pass (BUG-B): a fresh level clear already has its
            # bit set, so desired_completion_bytes adds nothing, yet we still need the
            # repaint to swap the vanilla completion tile to our enterable "$16" so the
            # level is re-enterable immediately (not only after the next reload).
            if not bulk:
                world = world_num[0] + 1
                checked = ctx.checked_locations | ctx.locations_checked
                desired = desired_completion_bytes(world, checked, completions)
                if desired is not None or level_flip_seen:
                    # Write the bits (if any) AND request a map repaint (Part-3 ROM hook
                    # makes the checkmarks visible + swaps the enterable tile). The write
                    # is guarded on the completions value we read; if the game changed it
                    # meanwhile, the write aborts harmlessly and we retry next pass.
                    to_write = desired if desired is not None else bytearray(completions)
                    ok = await guarded_write(
                        ctx.bizhawk_ctx,
                        [(MAP_COMPLETIONS, list(to_write), DOMAIN),
                         (MAP_REPAINT_REQ, [0x01], DOMAIN)],
                        [(MAP_COMPLETIONS, list(completions), DOMAIN)],  # guard: unchanged
                    )
                    if ok:
                        self._prev_completions = bytes(to_write)
                        if self.debug:
                            added = sum(bin(d & ~c).count("1")
                                        for d, c in zip(to_write, completions))
                            logger.info("SMB3: re-asserted %d checkmark bit(s) for "
                                        "World %d (repaint requested)", added, world)

            # --- persist defeated roaming enemies (Hammer/Boomerang/Heavy/Fire Bro) ---
            # Their "defeated" state is just their Map_Objects_IDs slot being $00, which
            # hub travel wipes by re-running Map_Init. So (1) DETECT a bro->empty
            # transition and remember that slot for this world; (2) after travel re-runs
            # Map_Init and respawns the bro, RE-BLANK any slot we recorded defeated.
            #
            # Detection only compares against the previous pass when the world is
            # unchanged (a world swap replaces the whole object table, so slot-vs-slot
            # deltas would be meaningless). We store (world, objects) together for that.
            cur_objects = bytes(map_objects)
            world = world_num[0] + 1
            prev_world, prev_objs = getattr(self, "_prev_objects_world", (None, None))
            if prev_objs is not None and prev_world == world:
                for slot in newly_defeated_bro_slots(prev_objs, cur_objects):
                    self._defeated_bro_slots.setdefault(world, set()).add(slot)
                    logger.info("SMB3: World %d roaming enemy defeated (slot %d) — "
                                "will keep it cleared across travel.", world, slot)
            # Re-blank any recorded-defeated slot the game just respawned.
            defeated = self._defeated_bro_slots.get(world)
            if defeated:
                slots = reblank_defeated_slots(defeated, cur_objects)
                if slots:
                    ok = await guarded_write(
                        ctx.bizhawk_ctx,
                        [(MAP_OBJECT_IDS + s, [0x00], DOMAIN) for s in slots],
                        [(MAP_OBJECT_IDS + s, [cur_objects[s]], DOMAIN) for s in slots],
                    )
                    if ok:
                        # Reflect the write locally so we don't re-detect it as a defeat.
                        buf = bytearray(cur_objects)
                        for s in slots:
                            buf[s] = 0x00
                        cur_objects = bytes(buf)
                        if self.debug:
                            logger.info("SMB3: re-cleared %d respawned enemy slot(s) "
                                        "in World %d: %s", len(slots), world, slots)
            self._prev_objects_world = (world, cur_objects)

            # --- level access: arm the gate + write this world's "unlocked" bitfield ---
            # Only when this slot enabled level_access (from slot_data). Rebuild the
            # unlocked-panel set from received "… Access" items (idempotent), then write
            # the CURRENT world's unlocked bits (authoritative image, 1 = unlocked) so the
            # entry-gate ROM hook can read them, and set the ACTIVE flag so the hook
            # enforces. On a level_access-off game we never touch either, so entry is never
            # wrongly blocked (the hook stays inert with its flag clear).
            if self._level_access:
                self._unlocked_panels = {
                    _ACCESS_ID_TO_PANEL[it.item]
                    for it in ctx.items_received
                    if it.item in _ACCESS_ID_TO_PANEL
                }
                # Announce each newly-unlocked panel once (so you know what opened up).
                for panel in sorted(self._unlocked_panels - self._logged_unlocks):
                    logger.info("SMB3: UNLOCKED %s — you can now enter it.",
                                _PANEL_DISPLAY_NAME.get(panel, str(panel)))
                self._logged_unlocks |= self._unlocked_panels
                world = world_num[0] + 1
                want = desired_lock_bytes(world, self._unlocked_panels, unlock_bits)
                writes = []
                if want is not None:
                    writes.append((MAP_UNLOCK_BITS, list(want), DOMAIN))
                if unlock_flag[0] != 0x01:
                    writes.append((MAP_UNLOCK_FLAG, [0x01], DOMAIN))
                if writes:
                    ok = await guarded_write(
                        ctx.bizhawk_ctx, writes,
                        # Guard on the values we read so a concurrent game write aborts it.
                        [(MAP_UNLOCK_BITS, list(unlock_bits), DOMAIN),
                         (MAP_UNLOCK_FLAG, list(unlock_flag), DOMAIN)],
                    )
                    if self.debug:
                        logger.info("SMB3[access]: W%d wrote flag=%s bits=%s ok=%s "
                                    "(had flag=$%02X)",
                                    world, any(a == MAP_UNLOCK_FLAG for a, *_ in writes),
                                    want is not None, ok, unlock_flag[0])
                if self.debug:
                    # Show what the gate will see for the panel under the player RIGHT NOW.
                    off = (map_xhi[0] << 4) | (map_x[0] >> 4)
                    row_bit = _row_bit_from_y(map_y[0])
                    locked = (off < len(unlock_bits)) and bool(unlock_bits[off] & row_bit)
                    logger.info("SMB3[access]: player W%d off=$%02X ybit=$%02X flag=$%02X "
                                "-> %s (unlocked_panels=%d)", world, off, row_bit,
                                unlock_flag[0], "LOCKED" if locked else "open",
                                len(self._unlocked_panels))

            # --- victory --- (AP dedups server-side, sets finished_game on confirm)
            if not ctx.finished_game and rescue[0] != 0:
                logger.warning("SMB3: Player_RescuePrincess set — sending victory.")
                await ctx.send_msgs([{
                    "cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])

            # --- grant received items (POC: every FILLER item == +1 life) ---
            #
            # POC limitation: dedup state lives only on the client (no ROM scratch
            # byte without ASM). On (re)connect the server re-sends every prior
            # item, so we baseline applied_items the first pass and only grant
            # items that arrive after that. Items received while disconnected are
            # not retroactively granted.
            #
            # Level Access items are PROGRESSION (they set the unlock bitfield above,
            # handled idempotently from the full received list) — they must NOT grant a
            # life. So the lives grant only counts newly-arrived NON-Access items.
            received = ctx.items_received
            if not self.synced:
                self.applied_items = len(received)
                self.synced = True
            elif len(received) > self.applied_items:
                new_slice = received[self.applied_items:]
                to_apply = sum(1 for it in new_slice
                               if it.item not in _ACCESS_ID_TO_PANEL)
                if to_apply:
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
                else:
                    # Only Access items arrived — nothing to grant, but advance the
                    # dedup cursor so we don't reconsider them next pass.
                    self.applied_items = len(received)
        except Exception:
            logger.exception("SMB3 watcher crashed after read")
