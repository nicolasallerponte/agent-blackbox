"""agent-blackbox: a flight recorder and bisect tool for AI coding agents."""

from __future__ import annotations

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    # Resolved lazily so that importing the package (as the latency-critical
    # hook does) never pays for importlib.metadata.
    if name == "__version__":
        from importlib.metadata import version  # noqa: PLC0415

        return version("agent-blackbox")
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
