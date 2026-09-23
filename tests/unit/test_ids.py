import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_blackbox.core.ids import InvalidSessionIdError, validate_session_id


@pytest.mark.parametrize(
    "value",
    [
        "e083b435-f411-4ab8-8502-0881daa5e641",
        "abc",
        "A1_b.c-d",
        "x" * 128,
    ],
)
def test_accepts_safe_ids(value: str) -> None:
    assert validate_session_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "x" * 129,
        "../etc",
        "a/b",
        "a\\b",
        ".hidden",
        "-flag",
        "a..b",
        "a.lock",
        "trailing.",
        "sp ace",
        "new\nline",
        "é",
        "a:b",
        "a@{b",
        "a*b",
    ],
)
def test_rejects_unsafe_ids(value: str) -> None:
    with pytest.raises(InvalidSessionIdError):
        validate_session_id(value)


@given(st.text(max_size=200))
def test_accepted_ids_are_safe_as_path_and_ref_components(value: str) -> None:
    try:
        validate_session_id(value)
    except InvalidSessionIdError:
        return
    assert "/" not in value
    assert "\\" not in value
    assert ".." not in value
    assert not value.startswith((".", "-"))
    assert not value.endswith((".", ".lock"))
    assert value.isascii()
    assert 1 <= len(value) <= 128
