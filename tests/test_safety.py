"""Guard rails: synx is a documentation tool and must never execute anything."""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest
from rich.console import Console

from synx.database import CommandDatabase
from synx.display import Renderer
from tests.conftest import SHIPPED_TOOLS
from tests.data import NXC_YAML, write_yaml

PACKAGE = Path(__file__).resolve().parent.parent / "synx"
SOURCE_FILES = sorted(PACKAGE.glob("*.py"))

FORBIDDEN_MODULES = {
    "subprocess",
    "pty",
    "socket",
    "multiprocessing",
    "asyncio.subprocess",
    "commands",
    "pexpect",
    "paramiko",
}
FORBIDDEN_CALLS = {"system", "popen", "spawnl", "spawnv", "execv", "execve", "eval", "exec"}
FORBIDDEN_YAML_TAGS = ("!!python/", "!!ruby/", "!!perl/", "!!bash")


def test_package_has_sources() -> None:
    assert SOURCE_FILES, "the synx package must contain Python sources"


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda path: path.name)
def test_no_execution_modules_are_imported(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert not imported & FORBIDDEN_MODULES, f"{path.name} imports {imported & FORBIDDEN_MODULES}"


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda path: path.name)
def test_no_execution_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, (
                f"{path.name} calls {node.func.id}()"
            )


def test_yaml_is_parsed_safely() -> None:
    source = (PACKAGE / "database.py").read_text(encoding="utf-8")
    assert "yaml.safe_load" in source
    assert "yaml.load(" not in source
    assert "yaml.unsafe_load" not in source
    assert "yaml.full_load" not in source


def test_displaying_a_tool_has_no_side_effects(tmp_path: Path) -> None:
    """Displaying a tool must not touch the database directory."""
    directory = tmp_path / "tools"
    write_yaml(directory, "nxc.yaml", NXC_YAML)
    before = sorted(item.name for item in directory.iterdir())
    database = CommandDatabase([(directory, "explicit")])
    database.load()
    renderer = Renderer(console=Console(file=io.StringIO(), width=80, no_color=True))
    renderer.print_tool(database.get("nxc"))
    assert sorted(item.name for item in directory.iterdir()) == before


@pytest.mark.parametrize("path", sorted(SHIPPED_TOOLS.glob("*.yaml")), ids=lambda p: p.name)
def test_shipped_yaml_has_no_unsafe_tags(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    for tag in FORBIDDEN_YAML_TAGS:
        assert tag not in content


def _is_switch(token: str) -> bool:
    """Return whether ``token`` names an option rather than carrying a value."""
    return token.startswith(("-", "/")) and ":" not in token


def option_values(syntax: str) -> Iterator[str]:
    """Yield the value of every option named in ``syntax``.

    Handles both spellings used by the documented tools: a separate token such
    as ``-p secret``, and the inline form ``/rc4:secret`` used by Rubeus.
    Placeholders are yielded unchanged so callers can inspect them.
    """
    for token in syntax.split():
        if _is_switch(token):
            continue
        if token.startswith(("-", "/")) and ":" in token:
            _switch, _, value = token.rpartition(":")
            if value:
                yield value
    for previous, token in pairwise(syntax.split()):
        if _is_switch(previous) and not (token.startswith(("-", "/"))):
            yield token


def test_documented_syntax_uses_placeholders() -> None:
    """Every credential or host in the database must be a placeholder.

    Only the value of an option is inspected, never a subcommand or an option
    name. That keeps genuine syntax such as ``bloodyAD ... set password`` or
    ``kerbrute passwordspray`` from being mistaken for a leaked secret, while
    still catching a real value that follows a switch, whether it is a separate
    token such as ``-p secret`` or an inline one such as ``/rc4:secret``.
    """
    database = CommandDatabase([(SHIPPED_TOOLS, "source")])
    database.load()
    for tool in database.tools:
        for command in tool.commands:
            for value in option_values(command.syntax):
                lowered = value.casefold()
                if "password" in lowered or "username" in lowered or lowered == "user":
                    assert value.startswith("<"), (
                        f"{tool.name} {command.name}: use a placeholder, not {value}"
                    )
