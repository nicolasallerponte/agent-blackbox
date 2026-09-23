import hashlib
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_blackbox.core.records import (
    MAX_LIST_ITEMS,
    MAX_STRING_CHARS,
    SCHEMA_VERSION,
    AgentRef,
    StepKind,
    StepRecord,
    TurnRecord,
    truncate_payload,
)


def _step(**overrides: object) -> StepRecord:
    fields: dict[str, object] = {
        "seq": 3,
        "kind": StepKind.TOOL,
        "session": "s1",
        "turn": "t1",
        "agent": AgentRef(id="a1", type="Explore"),
        "tool": "Edit",
        "input": {"file_path": "src/app.py", "old_string": "a", "new_string": "b"},
        "ok": True,
        "started_ns": 1_000,
        "ended_ns": 2_000,
        "commit": "c" * 40,
        "tree": "t" * 40,
        "parent": "p" * 40,
        "changed": True,
        "skipped_large": ("big.bin",),
        "flags": ("outside_project",),
    }
    fields.update(overrides)
    return StepRecord(**fields)  # type: ignore[arg-type]


def test_step_record_round_trips_through_json() -> None:
    record = _step()
    line = record.to_json()
    assert "\n" not in line
    assert StepRecord.from_dict(json.loads(line)) == record


def test_step_record_json_carries_schema_version_first() -> None:
    data = json.loads(_step().to_json())
    assert next(iter(data)) == "v"
    assert data["v"] == SCHEMA_VERSION
    assert data["kind"] == "tool"
    assert data["agent"] == {"id": "a1", "type": "Explore"}


def test_step_record_main_agent_serializes_as_null() -> None:
    data = json.loads(_step(agent=None).to_json())
    assert data["agent"] is None
    assert StepRecord.from_dict(data).agent is None


def test_from_dict_ignores_unknown_fields() -> None:
    data = json.loads(_step().to_json())
    data["future_field"] = {"anything": 1}
    assert StepRecord.from_dict(data) == _step()


def test_from_dict_rejects_newer_schema() -> None:
    data = json.loads(_step().to_json())
    data["v"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema version"):
        StepRecord.from_dict(data)


def test_non_ascii_is_kept_verbatim() -> None:
    line = _step(input={"content": "café ✓"}).to_json()
    assert "café ✓" in line


def test_turn_record_round_trips() -> None:
    turn = TurnRecord(session="s1", turn="t1", prompt="fix the bug", synthetic=False, at_ns=5)
    assert TurnRecord.from_dict(json.loads(turn.to_json())) == turn


def test_short_strings_are_untouched() -> None:
    payload = {"a": "x" * MAX_STRING_CHARS, "b": [1, 2.5, None, True]}
    assert truncate_payload(payload) == payload


def test_long_string_is_replaced_by_head_length_and_hash() -> None:
    long = "é" * (MAX_STRING_CHARS + 10)
    result = truncate_payload({"content": long})
    assert isinstance(result, dict)
    marker = result["content"]
    assert marker == {
        "$truncated": {
            "head": long[:MAX_STRING_CHARS],
            "chars": len(long),
            "sha256": hashlib.sha256(long.encode("utf-8")).hexdigest(),
        }
    }


def test_long_lists_are_cut_and_marked() -> None:
    result = truncate_payload(list(range(MAX_LIST_ITEMS + 5)))
    assert isinstance(result, list)
    assert len(result) == MAX_LIST_ITEMS + 1
    assert result[-1] == {"$truncated_items": 5}


def test_deep_nesting_is_cut() -> None:
    deep: object = "leaf"
    for _ in range(100):
        deep = {"k": deep}
    flat = json.dumps(truncate_payload(deep))
    assert "$truncated_depth" in flat
    assert "leaf" not in flat


def test_non_json_values_become_strings() -> None:
    assert truncate_payload({"x": b"bytes", 1: "one"}) == {"x": "b'bytes'", "1": "one"}


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=50),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=5), children, max_size=5)
    ),
    max_leaves=30,
)


@given(json_values)
def test_small_json_values_are_identity(value: object) -> None:
    assert truncate_payload(value) == value
