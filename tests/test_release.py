"""The command, the plugin and the skill must carry one version number.

Claude Code only hands out a new copy of a plugin when its version changes, and
the skill upgrades the command when it's older than the version the skill names.
So all three move together on every release.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from gdocout import __version__

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "claude-plugin"
SKILL = PLUGIN / "skills" / "gdocout" / "SKILL.md"


def test_plugin_version_matches_package():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__


def test_skill_names_the_current_version():
    skill = SKILL.read_text(encoding="utf-8")
    named = set(re.findall(r"gdocout (\d+\.\d+\.\d+) or newer", skill)) | set(re.findall(r"older than (\d+\.\d+\.\d+)", skill))
    assert named == {__version__}, named


def test_skill_installs_its_own_release():
    skill = SKILL.read_text(encoding="utf-8")
    pins = set(re.findall(r"github\.com/RazorII/gdocout@v(\d+\.\d+\.\d+)", skill))
    assert pins == {__version__}, pins
    assert not re.search(r"github\.com/RazorII/gdocout(?!@v|/)", skill), "an install line is not pinned"
