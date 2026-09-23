import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "changelog_notes.py"

CHANGELOG = """\
# Changelog

## [Unreleased]

### Added

- Something new.

## [0.2.0] - 2026-10-01

### Fixed

- A bug.

## [0.1.0] - 2026-09-30

### Added

- First release.

[Unreleased]: https://example.invalid/compare/v0.2.0...HEAD
[0.2.0]: https://example.invalid/compare/v0.1.0...v0.2.0
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("changelog_notes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extracts_middle_section() -> None:
    assert _load().extract(CHANGELOG, "0.2.0") == "### Fixed\n\n- A bug."


def test_extracts_last_section_without_link_references() -> None:
    assert _load().extract(CHANGELOG, "0.1.0") == "### Added\n\n- First release."


def test_missing_version_raises() -> None:
    with pytest.raises(LookupError, match=r"0\.3\.0"):
        _load().extract(CHANGELOG, "0.3.0")


def test_empty_section_raises() -> None:
    with pytest.raises(LookupError):
        _load().extract("## [1.0.0]\n\n## [0.9.0]\n\n- x\n", "1.0.0")


def test_cli_strips_leading_v(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "v0.1.0", str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == "### Added\n\n- First release.\n"


def test_cli_fails_for_missing_version(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "9.9.9", str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "9.9.9" in proc.stderr
