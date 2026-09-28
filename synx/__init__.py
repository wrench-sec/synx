"""synx - a command-line syntax and reference tool for Linux and cybersecurity tools."""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["Command", "CommandDatabase", "Tool", "__version__", "main"]


def __getattr__(name: str) -> object:
    if name in {"Command", "Tool"}:
        from synx import models

        return getattr(models, name)
    if name == "CommandDatabase":
        from synx.database import CommandDatabase

        return CommandDatabase
    if name == "main":
        from synx.cli import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
