import re
import runpy
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import agent_blackbox
from agent_blackbox.cli.app import app


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-]?(a|b|rc|dev)\d+)?", agent_blackbox.__version__)


def test_cli_version_flag() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"agent-blackbox {agent_blackbox.__version__}"


def test_cli_without_args_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def test_python_dash_m_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agent_blackbox", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == f"agent-blackbox {agent_blackbox.__version__}"


def test_main_runs_app(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["agent-blackbox", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("agent_blackbox", run_name="__main__")
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"agent-blackbox {agent_blackbox.__version__}"


def test_unknown_attribute_raises() -> None:
    with pytest.raises(AttributeError, match="no_such_thing"):
        _ = agent_blackbox.no_such_thing
