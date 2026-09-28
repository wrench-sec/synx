"""Tests for search scoring and fuzzy suggestions."""

from __future__ import annotations

import pytest

from synx.database import CommandDatabase
from synx.models import Tool
from synx.search import (
    fuzzy_suggestions,
    score_command,
    score_tool,
    search,
    search_commands,
    search_tools,
    suggest,
)
from tests.data import CERTIPY_YAML, NXC_YAML

TOOL_MAPPING = {
    "name": "nxc",
    "aliases": ["netexec", "crackmapexec"],
    "category": "active-directory",
    "description": "Network service enumeration and administration tool.",
    "commands": [
        {
            "name": "SMB",
            "syntax": "nxc smb <target> -d <domain> -u <username> -p <password>",
            "description": "Connects to an SMB service using the supplied credentials.",
            "tags": ["smb", "credentials"],
        },
        {
            "name": "LDAP BloodHound",
            "syntax": "nxc ldap <target> --bloodhound",
            "description": "Collects LDAP data for BloodHound.",
        },
    ],
}


@pytest.fixture
def nxc() -> Tool:
    return Tool.from_mapping(TOOL_MAPPING)


class TestToolSearch:
    def test_matches_the_tool_name(self, nxc: Tool) -> None:
        hits = search_tools("nxc", [nxc])
        assert [hit.tool.name for hit in hits] == ["nxc"]
        assert hits[0].field == "name"
        assert hits[0].field_label == "tool name"

    def test_matches_an_alias(self, nxc: Tool) -> None:
        hits = search_tools("netexec", [nxc])
        assert hits[0].field == "alias"
        assert "netexec" in hits[0].excerpt

    def test_matches_the_description(self, nxc: Tool) -> None:
        hits = search_tools("enumeration", [nxc])
        assert hits[0].field == "tool_description"

    def test_matches_the_category(self, nxc: Tool) -> None:
        assert search_tools("active-directory", [nxc])[0].field == "category"

    def test_is_case_insensitive(self, nxc: Tool) -> None:
        assert search_tools("NXC", [nxc])

    def test_returns_nothing_for_unknown_terms(self, nxc: Tool) -> None:
        assert search_tools("kubernetes", [nxc]) == []

    def test_ranks_name_matches_above_description_matches(self) -> None:
        by_name = Tool.from_mapping({"name": "kerberos", "description": "x", "commands": []})
        by_text = Tool.from_mapping({"name": "other", "description": "kerberos", "commands": []})
        assert search_tools("kerberos", [by_text, by_name])[0].tool.name == "kerberos"

    def test_empty_keyword_scores_zero(self, nxc: Tool) -> None:
        assert score_tool(nxc, "  ") == (0, "")


class TestCommandSearch:
    def test_matches_the_command_name(self, nxc: Tool) -> None:
        hits = search_commands("bloodhound", [nxc])
        assert [hit.command.name for hit in hits] == ["LDAP BloodHound"]
        assert hits[0].field == "command_name"

    def test_matches_the_syntax(self, nxc: Tool) -> None:
        hits = search_commands("--bloodhound", [nxc])
        assert hits[0].command.name == "LDAP BloodHound"
        assert hits[0].field == "syntax"

    def test_matches_the_command_description(self, nxc: Tool) -> None:
        assert search_commands("supplied", [nxc])[0].field == "description"

    def test_matches_tags(self, nxc: Tool) -> None:
        hits = search_commands("credentials", [nxc])
        assert hits[0].field == "tags"

    def test_command_name_matches_outrank_tag_matches(self, nxc: Tool) -> None:
        assert search_commands("smb", [nxc])[0].field == "command_name"

    def test_matches_a_placeholder_from_the_syntax(self, nxc: Tool) -> None:
        assert search_commands("<domain>", [nxc])[0].command.name == "SMB"

    def test_all_tokens_must_be_able_to_match(self, nxc: Tool) -> None:
        assert search_commands("smb kerberos", [nxc])[0].command.name == "SMB"

    def test_scores_are_positive(self, nxc: Tool) -> None:
        score, field = score_command(nxc.commands[0], "smb")
        assert score > 0
        assert field == "command_name"

    def test_unknown_term(self, nxc: Tool) -> None:
        assert search_commands("kubernetes", [nxc]) == []


class TestCombinedSearch:
    def test_returns_tool_and_command_hits(self, nxc: Tool) -> None:
        hits = search("smb", [nxc])
        assert len(hits) == 1
        assert hits[0].command is not None

    def test_reports_each_command_once(self, database: CommandDatabase) -> None:
        """A command matching in several fields must not be listed twice."""
        hits = search("bloodhound", [database.get("nxc")])
        assert len(hits) == 1

    def test_includes_tool_level_hits(self, nxc: Tool) -> None:
        hits = search("enumeration", [nxc])
        assert hits[0].command is None
        assert hits[0].excerpt.startswith("Network service enumeration")

    def test_hits_are_sorted_by_score(self, database: CommandDatabase) -> None:
        hits = search("password", database.tools)
        scores = [hit.score for hit in hits]
        assert scores == sorted(scores, reverse=True)

    def test_to_dict_serialises_a_hit(self, nxc: Tool) -> None:
        data = search("smb", [nxc])[0].to_dict()
        assert data["tool"] == "nxc"
        assert data["command"] == "SMB"
        assert data["syntax"].startswith("nxc smb")

    def test_no_matches(self, database: CommandDatabase) -> None:
        assert search("kubernetes", database.tools) == []


class TestFuzzySuggestions:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("ceripy", "certipy"),
            ("netexec", "nxc"),
            ("nxc.exe", "nxc"),
            ("impackt", "impacket"),
            ("evil winrm", "evil-winrm"),
            ("bloodhound", "bloodhound-python"),
            ("responderr", "responder"),
        ],
    )
    def test_suggests_close_names(self, query: str, expected: str) -> None:
        candidates = ["nxc", "certipy", "impacket", "evil-winrm", "bloodhound-python", "responder"]
        assert expected in suggest(query, candidates)

    def test_returns_scores_in_descending_order(self) -> None:
        results = fuzzy_suggestions("certipy", ["certipy-ad", "certipy", "nxc"])
        assert [name for name, _score in results] == ["certipy", "certipy-ad"]
        assert results[0][1] > results[1][1]

    def test_respects_the_limit(self) -> None:
        assert len(suggest("certipy", ["certipy", "certipy-ad", "certipy.py"], limit=2)) == 2

    def test_ignores_unrelated_names(self) -> None:
        assert suggest("zzzzzzzz", ["nxc", "certipy"]) == []

    def test_empty_inputs(self) -> None:
        assert fuzzy_suggestions("", ["nxc"]) == []
        assert fuzzy_suggestions("nxc", []) == []
        assert suggest("   ", ["nxc"]) == []


class TestDatabaseBackedSearch:
    def test_search_uses_the_sample_database(self, database: CommandDatabase) -> None:
        hits = search("kerberos", database.tools)
        tools = {hit.tool.name for hit in hits}
        assert "certipy" in tools
        assert any(hit.command and hit.command.name == "auth" for hit in hits)

    def test_search_over_every_shipped_tool(self, database: CommandDatabase) -> None:
        for tool in database.tools:
            assert search(tool.name, database.tools)

    def test_certipy_description_is_searchable(self, database: CommandDatabase) -> None:
        assert database.get("certipy").description.startswith("Tool for enumerating")
        assert CERTIPY_YAML.startswith("name: certipy")
        assert NXC_YAML.startswith("name: nxc")
