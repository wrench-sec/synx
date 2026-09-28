"""Shared fixtures for the synx test suite."""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from rich.console import Console

from synx.cli import main
from synx.database import CommandDatabase
from synx.display import Renderer
from tests.data import CERTIPY_YAML, NXC_YAML, write_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_TOOLS = REPO_ROOT / "tools"
TEST_WIDTH = 100

__all__ = [
    "CERTIPY_YAML",
    "NXC_YAML",
    "REPO_ROOT",
    "SHIPPED_TOOLS",
    "TEST_WIDTH",
    "write_yaml",
]


def make_console(buffer: io.StringIO) -> Console:
    """Return a deterministic, colourless console writing into ``buffer``."""
    return Console(
        file=buffer,
        width=TEST_WIDTH,
        no_color=True,
        markup=False,
        emoji=False,
        highlight=False,
    )


@pytest.fixture
def tools_directory(tmp_path: Path) -> Path:
    """A directory holding two valid tool definitions."""
    directory = tmp_path / "tools"
    write_yaml(directory, "nxc.yaml", NXC_YAML)
    write_yaml(directory, "certipy.yaml", CERTIPY_YAML)
    return directory


@pytest.fixture
def database(tools_directory: Path) -> CommandDatabase:
    """A database loaded from the :func:`tools_directory` fixture."""
    db = CommandDatabase([(tools_directory, "explicit")])
    db.load()
    return db


@pytest.fixture
def buffer() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def renderer(buffer: io.StringIO) -> Renderer:
    """A renderer that writes into :func:`buffer` without ANSI styling."""
    return Renderer(console=make_console(buffer))


@pytest.fixture
def run_synx(
    monkeypatch: pytest.MonkeyPatch, buffer: io.StringIO, tools_directory: Path
) -> Iterator[Callable[..., tuple[int, str]]]:
    """Run the CLI against a temporary database and capture its output."""

    def _run(*argv: str, db_path: Path | None = None) -> tuple[int, str]:
        console = make_console(buffer)
        monkeypatch.setattr(
            "synx.cli.Renderer", lambda **kwargs: Renderer(console=console, **kwargs)
        )
        buffer.seek(0)
        buffer.truncate(0)
        arguments = [
            *argv,
            "--db-path",
            str(db_path or tools_directory),
            "--width",
            str(TEST_WIDTH),
        ]
        code = main(arguments)
        return code, buffer.getvalue()

    yield _run
