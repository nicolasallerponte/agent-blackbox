import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_blackbox.core.outcome import Outcome, classify_exit_code


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, Outcome.GOOD),
        (1, Outcome.BAD),
        (2, Outcome.BAD),
        (124, Outcome.BAD),
        (125, Outcome.SKIP),
        (126, Outcome.BAD),
        (127, Outcome.BAD),
        (128, Outcome.ABORT),
        (255, Outcome.ABORT),
        (-9, Outcome.ABORT),
        (-15, Outcome.ABORT),
    ],
)
def test_git_bisect_run_convention(code: int, expected: Outcome) -> None:
    assert classify_exit_code(code) is expected


@given(st.integers(min_value=1, max_value=127).filter(lambda c: c != 125))
def test_every_failure_code_below_128_except_125_is_bad(code: int) -> None:
    assert classify_exit_code(code) is Outcome.BAD


@given(st.one_of(st.integers(min_value=128), st.integers(max_value=-1)))
def test_signals_and_high_codes_abort(code: int) -> None:
    assert classify_exit_code(code) is Outcome.ABORT
