"""Top-level ``agent-blackbox`` command."""

from __future__ import annotations

from typing import Annotated

import typer

from agent_blackbox import __version__

app = typer.Typer(
    name="agent-blackbox",
    help="Record every step of an AI coding agent session and bisect to the one that broke it.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:  # noqa: FBT001 - Typer callback signature
    if value:
        typer.echo(f"agent-blackbox {__version__}")
        raise typer.Exit


@app.callback()
def root(
    version: Annotated[  # noqa: FBT002 - Typer option declared as a bool default
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Record every step of an AI coding agent session and bisect to the one that broke it."""


def main() -> None:
    """Console-script entry point."""
    app()
