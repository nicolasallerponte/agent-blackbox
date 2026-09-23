import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).parents[2] / ".claude" / "skills" / "capture-hook-fixture" / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(directory: Path, ns: int, payload: dict[str, object]) -> None:
    record = {"observed_ns": ns, "payload": payload}
    (directory / f"{ns}.json").write_text(json.dumps(record), encoding="utf-8")


def test_dump_payload_writes_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "x": 1}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert _load("dump_payload").main(["dump_payload.py", str(tmp_path)]) == 0
    (written,) = tmp_path.iterdir()
    assert written.name.endswith("-PostToolUse-Write.json")
    assert json.loads(written.read_text())["payload"] == payload


def test_dump_payload_never_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert _load("dump_payload").main(["dump_payload.py", str(tmp_path)]) == 0
    assert list(tmp_path.iterdir()) == []


def test_anonymize_orders_renames_and_replaces(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    _capture(
        raw,
        2_500_000_000,
        {"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": "/secret/work/proj"},
    )
    _capture(raw, 1_000_000_000, {"hook_event_name": "SessionStart", "cwd": "/secret/work/proj"})

    written = _load("anonymize").convert(
        raw, out, [("/secret/work", "/opt/probe"), ("/secret/work/proj", "/home/user/project")]
    )

    assert [p.name for p in written] == ["00-SessionStart.json", "01-PostToolUse-Edit.json"]
    second = json.loads(written[1].read_text())
    assert second["_observed_offset_s"] == 1.5
    assert second["payload"]["cwd"] == "/home/user/project"
    assert "/secret" not in "".join(p.read_text() for p in written)


def test_anonymize_rejects_malformed_replacement() -> None:
    with pytest.raises(SystemExit):
        _load("anonymize").main(["raw", "out", "--replace", "no-equals-sign"])
