"""Option presets for the SMB3 webhost options page.

Each preset is a display-name -> {dataclass field name: value} mapping the
options page offers as a one-click starting point. Keys MUST match SMB3Options
field names and values must validate via the option's `from_any` (the framework
checks this), so we only reference options that exist today. More presets
(e.g. a Hub/100% preset) land as their options are added in later PRs.
"""
from typing import Any, Dict

smb3_options_presets: Dict[str, Dict[str, Any]] = {
    # The current Phase 0 model: beat Bowser; SMB3 receives only filler.
    "Any% / Vanilla": {
        "goal": "bowser",
        "item_model": "filler_only",
        "level_checks": False,
    },
    # Every level and Toad House is a check (100%-style location set). Victory is
    # still beating Bowser — the checks are extra locations, not a harder goal.
    "100% / Level Checks": {
        "goal": "bowser",
        "item_model": "filler_only",
        "level_checks": True,
    },
    # Start in the World-9 hub, with every level a check. The 100% experience.
    "Hub / 100%": {
        "goal": "bowser",
        "item_model": "filler_only",
        "level_checks": True,
        "hub_world": True,
    },
}
