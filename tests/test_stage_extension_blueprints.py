#!/usr/bin/env python3
"""Stage repo-root blueprints/ into package/<import>/blueprints/ without moving git source."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage_extension_blueprints import stage_extension_blueprints  # noqa: E402


class StageExtensionBlueprintsTests(unittest.TestCase):
    def test_copies_json_into_import_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "data"
            (root / "blueprints").mkdir(parents=True)
            (root / "package" / "data").mkdir(parents=True)
            (root / "package" / "data" / "__init__.py").write_text("", encoding="utf-8")
            (root / "blueprints" / "data_onboardings.json").write_text(
                json.dumps({"handle": "irma", "name": "data_onboardings", "version": "0.0.1"}),
                encoding="utf-8",
            )
            dest = stage_extension_blueprints(extension_root=root)
            self.assertIsNotNone(dest)
            self.assertTrue((dest / "data_onboardings.json").is_file())
            self.assertTrue((root / "blueprints" / "data_onboardings.json").is_file())


if __name__ == "__main__":
    unittest.main()
