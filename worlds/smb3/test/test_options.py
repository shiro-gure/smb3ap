"""Tests for the webhost options page wiring (PR 3): option groups, presets,
tutorials, and the docs files. Pure Python — no ROM/emulator needed."""
import dataclasses
import os
import unittest

from .. import SMB3World
from ..Options import SMB3Options, smb3_option_groups
from ..Presets import smb3_options_presets

_DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "docs")


def _field_types() -> dict:
    """Map dataclass field name -> Option class (for from_any validation)."""
    if hasattr(SMB3Options, "type_hints"):
        return SMB3Options.type_hints
    return {f.name: f.type for f in dataclasses.fields(SMB3Options)}


# Framework groups AP auto-appends to option_groups (item/location plumbing that
# lives on PerGameCommonOptions, not on our dataclass directly). Not ours to check.
_FRAMEWORK_GROUPS = {"Item & Location Options", "Game Options"}


class TestOptionGroups(unittest.TestCase):
    def test_grouped_options_are_real_dataclass_fields(self) -> None:
        field_classes = set(_field_types().values())
        for group in smb3_option_groups:
            if group.name in _FRAMEWORK_GROUPS:
                continue
            for opt in group.options:
                # Every option we group must be a field on SMB3Options.
                self.assertIn(
                    opt, field_classes,
                    f"grouped option {opt.__name__} is not a field on SMB3Options",
                )

    def test_no_option_in_two_groups(self) -> None:
        seen = set()
        for group in smb3_option_groups:
            for opt in group.options:
                self.assertNotIn(opt, seen, f"{opt.__name__} appears in two groups")
                seen.add(opt)


class TestPresets(unittest.TestCase):
    def test_presets_reference_real_options_and_validate(self) -> None:
        types = _field_types()
        self.assertTrue(smb3_options_presets, "expected at least one preset")
        for pname, preset in smb3_options_presets.items():
            for opt_name, value in preset.items():
                self.assertIn(opt_name, types,
                              f"preset '{pname}' references unknown option '{opt_name}'")
                # Must validate exactly as the webhost validates it.
                types[opt_name].from_any(value)


class TestWebWorld(unittest.TestCase):
    def test_tutorial_points_at_existing_doc(self) -> None:
        self.assertTrue(SMB3World.web.tutorials, "expected a setup tutorial")
        for tut in SMB3World.web.tutorials:
            self.assertTrue(os.path.exists(os.path.join(_DOCS, tut.file_name)),
                            f"tutorial doc {tut.file_name} missing from docs/")

    def test_game_info_doc_matches_game_name(self) -> None:
        # The webhost looks for docs/{lang}_{game}.md.
        expected = f"en_{SMB3World.game}.md"
        self.assertTrue(os.path.exists(os.path.join(_DOCS, expected)),
                        f"game-info doc {expected} missing from docs/")

    def test_web_option_groups_wired(self) -> None:
        self.assertIs(SMB3World.web.option_groups, smb3_option_groups)
        self.assertIs(SMB3World.web.options_presets, smb3_options_presets)


if __name__ == "__main__":
    unittest.main()
