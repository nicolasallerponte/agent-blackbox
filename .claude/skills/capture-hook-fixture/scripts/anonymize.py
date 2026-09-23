"""Turn raw captures from dump_payload.py into ordered, anonymized fixtures.

Usage:
    python3 anonymize.py <capture-dir> <output-dir> --replace OLD=NEW [--replace OLD=NEW ...]

Files are ordered by capture time and renamed ``NN-<Event>[-<Tool>].json``.
Every ``OLD`` string (absolute paths, user names, host names) is replaced by
``NEW`` everywhere, longest first. ``observed_ns`` becomes
``_observed_offset_s``, relative to the first event, so fixtures are stable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def anonymize_text(text: str, replacements: list[tuple[str, str]]) -> str:
    """Apply replacements longest-first so that nested paths are handled."""
    for old, new in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(old, new)
    return text


def convert(capture_dir: Path, output_dir: Path, replacements: list[tuple[str, str]]) -> list[Path]:
    """Convert every capture in ``capture_dir`` and return the written paths."""
    records = [json.loads(p.read_text(encoding="utf-8")) for p in capture_dir.glob("*.json")]
    records.sort(key=lambda r: r["observed_ns"])
    if not records:
        return []
    t0 = records[0]["observed_ns"]
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for index, record in enumerate(records):
        payload = record["payload"]
        name = f"{index:02d}-{payload.get('hook_event_name', 'Unknown')}"
        if payload.get("tool_name"):
            name += f"-{payload['tool_name']}"
        out = {
            "_observed_offset_s": round((record["observed_ns"] - t0) / 1e9, 3),
            "payload": payload,
        }
        text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
        path = output_dir / f"{name}.json"
        path.write_text(anonymize_text(text, replacements), encoding="utf-8")
        written.append(path)
    return written


def _parse_replacement(value: str) -> tuple[str, str]:
    old, sep, new = value.partition("=")
    if not sep or not old:
        msg = f"expected OLD=NEW, got {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return old, new


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--replace", type=_parse_replacement, action="append", default=[])
    args = parser.parse_args(argv)
    written = convert(args.capture_dir, args.output_dir, args.replace)
    sys.stdout.write(f"wrote {len(written)} fixtures to {args.output_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
