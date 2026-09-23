"""Agent-agnostic core: snapshots, session journal, bisect.

Must not import from ``agent_blackbox.adapters`` or ``agent_blackbox.cli``,
nor from CLI libraries (enforced by import-linter).
"""
