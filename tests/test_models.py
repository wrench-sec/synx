"""Tests for the schema validation and matching helpers in synx.models."""

from __future__ import annotations

import re

import pytest

from synx.models import (
    Command,
    CommandNotFoundError,
    Tool,
    ToolNotFoundError,
    ToolValidationError,
    normalise_query,
)

MINIMAL = {"name": "demo", "commands": [{"name": "run", "syntax": "demo run <target>"}]}


class TestCommand:
    def test_from_mapping_reads_every_documented_field(self) -> None:
        command = Command.from_mapping(
            {
                "name": "smb",
                "syntax": "nxc smb <target>",
                "description": "Connects over SMB.",
                "tags": ["smb", " credentials "],
                "notes": "Requires SMB.",
                "version": "nxc 0.3+",
                "example": "nxc smb 10.0.0.5",
            }
        )
        assert command.name == "smb"
        assert command.syntax == "nxc smb <target>"
        assert command.tags == ("smb", "credentials")
        assert command.version == "nxc 0.3+"

    def test_description_is_optional(self) -> None:
        command = Command.from_mapping({"name": "smb", "syntax": "nxc smb <target>"})
        assert command.description == ""

    @pytest.mark.parametrize(
        "payload",
        [
            {"syntax": "nxc smb <target>"},
            {"name": "smb"},
            {"name": "", "syntax": "nxc smb"},
            {"name": "smb", "syntax": 42},
            {"name": "smb", "syntax": "nxc smb", "tags": "smb,ldap"},
            {"name": "smb", "syntax": "nxc smb", "tags": [1, 2]},
            ["not", "a", "mapping"],
        ],
    )
    def test_invalid_payloads_raise(self, payload: object) -> None:
        with pytest.raises(ToolValidationError):
            Command.from_mapping(payload)

    def test_error_message_identifies_the_offending_command(self) -> None:
        with pytest.raises(ToolValidationError) as excinfo:
            Command.from_mapping({"name": "broken"}, index=3)
        assert "command #3" in str(excinfo.value)

    def test_executable_and_summary(self) -> None:
        command = Command(
            name="secretsdump",
            syntax="impacket-secretsdump -target <dc-ip>",
            description="Dumps hashes. Extra detail follows.",
        )
        assert command.executable == "impacket-secretsdump"
        assert command.summary == "Dumps hashes."
        assert Command(name="x", syntax="x").summary == ""

    def test_to_dict_omits_empty_values(self) -> None:
        assert Command(name="a", syntax="a").to_dict() == {
            "name": "a",
            "syntax": "a",
            "description": "",
        }


class TestTool:
    def test_from_mapping(self) -> None:
        tool = Tool.from_mapping(
            {
                "name": "nxc",
                "description": "Network service enumeration.",
                "aliases": ["netexec"],
                "category": "active-directory",
                "homepage": "https://example.invalid",
                "notes": "Flags change between releases.",
                "commands": [{"name": "SMB", "syntax": "nxc smb <target>"}],
            }
        )
        assert tool.name == "nxc"
        assert tool.aliases == ("netexec",)
        assert tool.command_count == 1
        assert tool.searchable_names == ("nxc", "netexec")

    def test_missing_commands_is_an_error(self) -> None:
        with pytest.raises(ToolValidationError, match="commands"):
            Tool.from_mapping({"name": "nxc"})

    def test_commands_must_be_a_list(self) -> None:
        with pytest.raises(ToolValidationError, match="must be a list"):
            Tool.from_mapping({"name": "nxc", "commands": "smb"})

    def test_top_level_must_be_a_mapping(self) -> None:
        with pytest.raises(ToolValidationError, match="top level"):
            Tool.from_mapping(["nxc"])

    def test_error_includes_the_source_file(self) -> None:
        with pytest.raises(ToolValidationError, match=re.escape("tools/nxc.yaml")):
            Tool.from_mapping({"commands": []}, source="tools/nxc.yaml")

    def test_command_names_are_matched_case_insensitively(self) -> None:
        tool = Tool.from_mapping(
            {"name": "nxc", "commands": [{"name": "SMB", "syntax": "nxc smb <target>"}]}
        )
        for query in ("SMB", "smb", "Smb", "  smb  "):
            assert tool.get_command(query) is not None
        assert tool.find_command("SMB").name == "SMB"

    def test_commands_can_be_matched_by_binary_and_tag(self) -> None:
        tool = Tool.from_mapping(
            {
                "name": "impacket",
                "commands": [
                    {
                        "name": "secretsdump",
                        "syntax": "impacket-secretsdump -target <dc-ip>",
                        "description": "Dumps credentials.",
                        "tags": ["ntlm"],
                    }
                ],
            }
        )
        assert tool.get_command("impacket-secretsdump").name == "secretsdump"
        assert tool.get_command("impacket_secretsdump").name == "secretsdump"
        assert tool.get_command("ntlm").name == "secretsdump"
        assert tool.get_command("secretsdump.py").name == "secretsdump"
        assert tool.get_command("missing") is None

    def test_find_command_raises_for_unknown_command(self) -> None:
        tool = Tool.from_mapping(MINIMAL)
        with pytest.raises(CommandNotFoundError) as excinfo:
            tool.find_command("nope")
        assert excinfo.value.tool_name == "demo"

    def test_summary_description_uses_the_first_sentence(self) -> None:
        tool = Tool.from_mapping(
            {
                "name": "demo",
                "description": "First sentence. Second sentence.",
                "commands": [{"name": "run", "syntax": "demo run"}],
            }
        )
        assert tool.summary_description == "First sentence."

    def test_with_source_returns_a_copy(self) -> None:
        tool = Tool.from_mapping(MINIMAL)
        assert tool.with_source(None) is tool
        assert tool.with_source("/tmp/demo.yaml").source == "/tmp/demo.yaml"

    def test_to_dict_round_trips_the_documented_fields(self) -> None:
        tool = Tool.from_mapping(
            {
                "name": "demo",
                "description": "Demo tool.",
                "aliases": ["d"],
                "category": "misc",
                "commands": [{"name": "run", "syntax": "demo run <target>", "tags": ["x"]}],
            }
        )
        data = tool.to_dict()
        assert data["name"] == "demo"
        assert data["aliases"] == ["d"]
        assert data["commands"][0]["tags"] == ["x"]


class TestNormaliseQuery:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("SMB", "smb"),
            ("  Certipy  ", "certipy"),
            ("bloodhound.py", "bloodhound"),
            ("impacket-GetUserSPNs", "impacket getuserspns"),
            ("net_exec", "net exec"),
            ("nxc.exe", "nxc"),
            ("", ""),
        ],
    )
    def test_normalisation(self, value: str, expected: str) -> None:
        assert normalise_query(value) == expected


class TestErrors:
    def test_tool_not_found_message(self) -> None:
        error = ToolNotFoundError("ceripy")
        assert str(error) == "Tool 'ceripy' was not found."
        assert error.name == "ceripy"
