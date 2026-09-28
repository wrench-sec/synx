"""Tests that the YAML database shipped with synx stays valid and factual."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from synx.database import CommandDatabase
from synx.models import Tool
from tests.conftest import SHIPPED_TOOLS

YAML_FILES = sorted(SHIPPED_TOOLS.glob("*.yaml"))
REAL_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_.\-]+>")
WEB_URL_RE = re.compile(r"https?://")


def test_database_directory_is_not_empty() -> None:
    assert YAML_FILES, "the tools/ directory must ship at least one YAML file"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda path: path.name)
def test_file_is_valid_yaml(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "each file must contain one YAML mapping"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda path: path.name)
def test_file_matches_the_schema(path: Path) -> None:
    tool = Tool.from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8")), source=str(path)
    )
    assert tool.name == path.stem, "the file name should match the tool name"
    assert tool.description.endswith("."), "descriptions should be full sentences"
    assert tool.commands, "every tool documents at least one command"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda path: path.name)
def test_commands_are_documented_and_unique(path: Path) -> None:
    tool = Tool.from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8")), source=str(path)
    )
    names = [command.name for command in tool.commands]
    assert len(names) == len(set(names)), "command names must be unique within a tool"
    for command in tool.commands:
        assert command.syntax.split(), "every command needs a syntax string"
        assert command.description, f"{tool.name} {command.name} needs a description"
        assert not command.syntax.endswith("."), "syntax is not a sentence"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda path: path.name)
def test_syntax_uses_placeholders_instead_of_real_hosts(path: Path) -> None:
    """Documented syntax must not embed real addresses or credentials."""
    tool = Tool.from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8")), source=str(path)
    )
    for command in tool.commands:
        # Documentation URLs are not syntax, but a tool may legitimately take a
        # connection string such as ldaps://<dc-ip>:636 as an argument, so only
        # web schemes are rejected here.
        assert not WEB_URL_RE.search(command.syntax), "syntax should not contain URLs"
        # Only value tokens are inspected: a flag such as --password, -p or
        # /password:PASSWORD names the option, it does not embed a secret.
        value_tokens = [
            token for token in command.syntax.split() if not token.startswith(("-", "/"))
        ]
        if any("password" in token.casefold() for token in value_tokens):
            assert "<password>" in command.syntax, (
                f"{tool.name} {command.name}: document the password as <password>"
            )
        for host in (match for match in command.syntax.split() if PLACEHOLDER_RE.fullmatch(match)):
            assert not REAL_IP_RE.search(host), f"{host} looks like a real address"
        for word in command.syntax.split():
            if word.startswith("-") or word.startswith("<"):
                continue
            assert not REAL_IP_RE.fullmatch(word), f"{word} looks like a real address"


def test_no_duplicate_tool_names() -> None:
    names = [
        yaml.safe_load(path.read_text(encoding="utf-8"))["name"] for path in YAML_FILES
    ]
    assert len(names) == len(set(names))


def test_documented_examples_exist() -> None:
    names = {
        yaml.safe_load(path.read_text(encoding="utf-8"))["name"] for path in YAML_FILES
    }
    assert {"nxc", "certipy", "impacket"} <= names


def test_nxc_syntax_matches_the_documented_example() -> None:
    tool = Tool.from_mapping(yaml.safe_load((SHIPPED_TOOLS / "nxc.yaml").read_text()))
    assert tool.find_command("smb").syntax == (
        "nxc smb <target> -d <domain> -u <username> -p <password>"
    )
    assert tool.find_command("winrm").syntax == (
        "nxc winrm <target> -d <domain> -u <username> -p <password>"
    )
    assert tool.find_command("ldap").syntax == (
        "nxc ldap <target> -d <domain> -u <username> -p <password>"
    )
    assert tool.description == (
        "Network service enumeration and administration tool for Windows networks. "
        "NetExec is the maintained successor of CrackMapExec: it speaks SMB, LDAP, "
        "WinRM, RDP, MSSQL, SSH and other protocols with a single command line and "
        "reports what each account or host exposes."
    )
    assert [command.name for command in tool.commands[:3]] == ["SMB", "WinRM", "LDAP"]


def test_certipy_search_term_is_findable() -> None:
    tool = Tool.from_mapping(yaml.safe_load((SHIPPED_TOOLS / "certipy.yaml").read_text()))
    assert tool.find_command("find").syntax.startswith("certipy find ")
    assert "certificate" in tool.description


def test_shipped_database_loads_without_errors() -> None:
    database = CommandDatabase([(SHIPPED_TOOLS, "source")])
    database.load()
    assert database.errors == ()
    assert database.warnings == ()
    assert database.tool_count == len(YAML_FILES)
    assert database.command_count > 50


def test_kerberos_is_searchable_in_the_shipped_database() -> None:
    from synx.search import search

    database = CommandDatabase([(SHIPPED_TOOLS, "source")])
    database.load()
    matched = {hit.tool.name for hit in search("kerberos", database.tools)}
    assert {"certipy", "impacket"} <= matched
