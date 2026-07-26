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
    },
}
