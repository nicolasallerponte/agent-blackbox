import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_blackbox.core import journal


def _write_raw(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def test_append_creates_file_with_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    journal.append(path, {"seq": 0})
    assert path.read_text() == '{"seq":0}\n'
    assert path.stat().st_mode & 0o777 == 0o600


def test_append_accumulates_lines(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    for i in range(3):
        journal.append(path, {"seq": i})
    assert [r["seq"] for r in journal.read_records(path)] == [0, 1, 2]


def test_read_missing_file_is_empty(tmp_path: Path) -> None:
    assert journal.read_records(tmp_path / "missing.jsonl") == []
    assert journal.last_record(tmp_path / "missing.jsonl") is None


def test_torn_tail_line_is_ignored_by_readers(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b'{"seq":0}\n{"seq":1}\n{"seq":')
    assert [r["seq"] for r in journal.read_records(path)] == [0, 1]
    assert journal.last_record(path) == {"seq": 1}


def test_garbage_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b'{"seq":0}\nnot json\n[1,2]\n\xff\xfe\n{"seq":1}\n')
    assert [r["seq"] for r in journal.read_records(path)] == [0, 1]


def test_repair_truncates_torn_tail(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b'{"seq":0}\n{"seq":1')
    assert journal.repair(path) is True
    assert path.read_bytes() == b'{"seq":0}\n'
    assert journal.repair(path) is False


def test_repair_of_file_with_only_a_torn_line_empties_it(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b'{"seq":0')
    assert journal.repair(path) is True
    assert path.read_bytes() == b""


def test_repair_missing_file_is_noop(tmp_path: Path) -> None:
    assert journal.repair(tmp_path / "missing.jsonl") is False


def test_append_after_torn_tail_repairs_first(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b'{"seq":0}\n{"se')
    journal.append(path, {"seq": 1})
    assert [r["seq"] for r in journal.read_records(path)] == [0, 1]
    assert path.read_bytes().endswith(b'{"seq":1}\n')


def test_last_record_reads_only_the_tail_of_large_files(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    big = "x" * 200_000
    journal.append(path, {"seq": 0, "blob": big})
    journal.append(path, {"seq": 1, "blob": big})
    last = journal.last_record(path)
    assert last is not None
    assert last["seq"] == 1


def test_last_record_skips_trailing_garbage(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b'{"seq":0}\nnot json\n')
    assert journal.last_record(path) == {"seq": 0}


def test_unicode_line_breaks_are_escaped(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    record = {"text": "a\x85b\u2028c\u2029d"}
    journal.append(path, record)
    raw = path.read_text(encoding="utf-8")
    assert raw.count("\n") == 1
    assert len(raw.splitlines()) == 1
    assert journal.read_records(path) == [record]


def test_lone_surrogates_from_parsed_payloads_are_escaped(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    record = json.loads('{"text": "bad \\ud800 surrogate"}')
    journal.append(path, record)
    assert journal.read_records(path) == [record]


def test_append_rejects_non_object(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        journal.append(tmp_path / "x.jsonl", ["not", "a", "dict"])  # type: ignore[arg-type]


@given(st.lists(st.dictionaries(st.text(max_size=8), st.text(max_size=30), max_size=4), max_size=8))
def test_round_trip_any_records(records: list[dict[str, str]]) -> None:
    import tempfile  # noqa: PLC0415 - hypothesis examples need fresh dirs

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "j.jsonl"
        for r in records:
            journal.append(path, r)
        assert journal.read_records(path) == records
        assert journal.last_record(path) == (records[-1] if records else None)
        text = path.read_text(encoding="utf-8") if records else ""
        # One physical line per record, even for readers that split on Unicode breaks.
        assert len(text.splitlines()) == len(records)
        for line in text.splitlines():
            json.loads(line)


def test_last_record_with_lines_larger_than_the_read_chunk(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    big = "y" * 300_000
    journal.append(path, {"seq": 0, "blob": big})
    with path.open("ab") as fh:
        fh.write(b'{"torn": "' + b"z" * 200_000)
    last = journal.last_record(path)
    assert last is not None
    assert last["seq"] == 0
    assert journal.repair(path) is True
    assert journal.last_record(path) == last


def test_last_record_when_nothing_parses(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    _write_raw(path, b"garbage\n" * 20_000)
    assert journal.last_record(path) is None


def test_repair_of_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    path.write_bytes(b"")
    assert journal.repair(path) is False
