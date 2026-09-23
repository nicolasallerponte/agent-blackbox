"""Print the CHANGELOG.md section for one version (used by the release workflow).

Usage: python scripts/changelog_notes.py 0.1.0 [CHANGELOG.md]

Exits with status 1 if the version has no section or the section is empty, so a
release can never be published without notes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]")


def extract(changelog: str, version: str) -> str:
    """Return the body of the ``## [version]`` section, without its heading.

    Args:
        changelog: Full CHANGELOG.md text in Keep a Changelog format.
        version: Version without a leading ``v``, e.g. ``0.1.0``.

    Returns:
        The section body with surrounding blank lines removed.

    Raises:
        LookupError: If the section is missing or empty.
    """
    lines = changelog.splitlines()
    body: list[str] = []
    inside = False
    for line in lines:
        match = _HEADING.match(line)
        if match:
            if inside:
                break
            inside = match.group("version") == version
            continue
        if inside:
            if line.startswith("[") and "]: " in line:
                break  # link reference definitions at the end of the file
            body.append(line)
    text = "\n".join(body).strip()
    if not text:
        msg = f"CHANGELOG has no non-empty section for version {version!r}"
        raise LookupError(msg)
    return text


def main(argv: list[str]) -> int:
    """Command-line entry point."""
    if len(argv) not in {2, 3}:
        sys.stderr.write(__doc__ or "")
        return 2
    version = argv[1].removeprefix("v")
    path = Path(argv[2]) if len(argv) == 3 else Path("CHANGELOG.md")  # noqa: PLR2004
    try:
        notes = extract(path.read_text(encoding="utf-8"), version)
    except LookupError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(notes + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
