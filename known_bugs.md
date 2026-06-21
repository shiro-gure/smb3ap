# Known Bugs

A running log of known issues. Newest first.

---

## BUG-001 — Save-state reload mis-credits fortresses in multi-fortress worlds

**Logged:** 2026-06-20
**Area:** fortress detection (`worlds/smb3/Client.py`)
**Severity:** TBD (POC; surfaces with save states / revisits)
**Status:** Open — under investigation (awaiting full logs from in-game test)

### Summary
When using save states: reloading a save state in a world that has **multiple fortresses**, the
client assumes the player is at the **next** fortress. So the count-based clear-order crediting
advances incorrectly — it credits the wrong fortress location (or an additional one) on the next
clear.

### Why (initial hypothesis)
Fortress crediting is **count-based / clear-order**: the Nth fortress *cleared* in a world maps to
that world's Nth fortress location (`next_unchecked_fortress`), and detection is a 0→1 edge on the
`Map_Completions` panel bit gated on a rubble tile. A save-state reload can:
- Re-present a `Map_Completions` state that the client's `_prev_completions` baseline doesn't match,
  producing a spurious 0→1 edge → a fortress credit that didn't happen this session; and/or
- Desync the "how many fortresses have I credited this world" count from the actual game state, so a
  subsequent real clear maps to the wrong location.

This ties into the broader **revisits** question: the current model assumes forward, in-order,
single-pass progression. Save states (and the future World-9-hub / revisitable-worlds plan) break
that assumption. The robust fix is likely to credit a fortress by **which specific panel bit flipped**
(positional → which fortress), not by clear-order count — or to track per-world already-seen panel
bits rather than a running count. (See DESIGN.md §10 / NEXT_STEPS.md persistent-bitfield plan.)

### Repro (from the user, to be confirmed with logs)
1. Be in a world with ≥2 fortresses (e.g. W3/W4/W5/W6/W7).
2. Clear one fortress (check fires correctly).
3. Reload a save state.
4. Clear a fortress again → the client credits the *next* fortress location instead of the right one.

### TODO
- [ ] Attach the in-game logs (user finishing the test).
- [ ] Get the user's deeper explanation of the exact mis-credit behavior.
- [ ] Design fix: positional panel-bit → specific fortress, OR per-world seen-bit set that survives
      reloads, instead of clear-order count. Consider how revisits should behave by design.
