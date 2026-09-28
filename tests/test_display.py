"""Tests for the rich rendering layer."""

from __future__ import annotations

import io
import json

import pytest

from synx.database import CommandDatabase, LoadIssue
from synx.display import RULE_WIDTH, Renderer, highlight_syntax
from synx.models import Command, Tool
from synx.search import search
from tests.conftest import make_console


@pytest.fixture
def out(buffer: io.StringIO) -> str:
    return buffer.getvalue()


def collect(renderer: Renderer, buffer: io.StringIO) -> str:
    buffer.seek(0)
    return buffer.getvalue()


class TestHighlightSyntax:
    def test_keeps_the_plain_text_intact(self) -> None:
        syntax = "nxc smb <target> -d <domain> -u <username> -p <password>"
        assert highlight_syntax(syntax).plain == syntax

    def test_colours_the_executable_placeholders_and_flags(self) -> None:
        text = highlight_syntax("certipy find -dc-ip <dc-ip> --bloodhound")
        styles = {span.style for span in text.spans}
        assert "bold green" in styles
        assert "bold magenta" in styles
        assert "cyan" in styles
        assert text.spans[0].start == 0
        assert text.spans[0].end == len("certipy")

    def test_handles_an_empty_syntax(self) -> None:
        assert highlight_syntax("").plain == ""

    def test_does_not_split_a_flag_inside_a_placeholder(self) -> None:
        text = highlight_syntax("nmap -p <port> --script krb5-domain:<domain> <target>")
        assert text.plain == "nmap -p <port> --script krb5-domain:<domain> <target>"
        assert "-ip" not in [text.plain[s.start : s.end] for s in text.spans]

    def test_no_double_highlighting_on_repeated_runs(self) -> None:
        syntax = "evil-winrm -i <target> -u <username> -p <password>"
        assert highlight_syntax(syntax).plain == highlight_syntax(syntax).plain == syntax


class TestToolRendering:
    def test_layout_matches_the_documented_example(
        self, renderer: Renderer, buffer: io.StringIO
    ) -> None:
        tool = Tool.from_mapping(
            {
                "name": "nxc",
                "description": "Network service enumeration and administration tool.",
                "commands": [
                    {
                        "name": "SMB",
                        "syntax": "nxc smb <target> -d <domain> -u <username> -p <password>",
                        "description": "Connects to an SMB service using the supplied credentials.",
                    }
                ],
            }
        )
        renderer.print_tool(tool)
        lines = [line.rstrip() for line in collect(renderer, buffer).splitlines() if line.strip()]
        assert lines[0] == "nxc"
        assert lines[1] == "─" * RULE_WIDTH
        assert lines[2] == "Network service enumeration and administration tool."
        assert "SMB" in lines
        assert "  Syntax:" in lines
        assert "    nxc smb <target> -d <domain> -u <username> -p <password>" in lines
        assert "  Description:" in lines
        assert "    Connects to an SMB service using the supplied credentials." in lines

    def test_optional_metadata_is_rendered(self, renderer: Renderer, buffer: io.StringIO) -> None:
        tool = Tool.from_mapping(
            {
                "name": "nxc",
                "description": "Tool.",
                "aliases": ["netexec"],
                "category": "active-directory",
                "homepage": "https://example.invalid",
                "notes": "Flags change between releases.",
                "commands": [{"name": "smb", "syntax": "nxc smb <target>", "tags": ["smb"]}],
            }
        )
        renderer.print_tool(tool.with_source("/tmp/nxc.yaml"), show_source=True)
        output = collect(renderer, buffer)
        expected_fields = (
            "Category:",
            "active-directory",
            "Aliases:",
            "netexec",
            "Homepage:",
            "Source:",
            "Tags:",
        )
        for expected in expected_fields:
            assert expected in output

    def test_optional_command_fields_are_rendered(
        self, renderer: Renderer, buffer: io.StringIO
    ) -> None:
        command = Command(
            name="find",
            syntax="certipy find -dc-ip <dc-ip>",
            description="Searches for certificate services.",
            notes="Needs LDAP.",
            version="Certipy 4.x",
            example="certipy find -dc-ip 10.0.0.1",
            tags=("adcs",),
        )
        renderer.print_command(command)
        output = collect(renderer, buffer)
        for expected in ("Notes:", "Needs LDAP.", "Version:", "Certipy 4.x", "Example:", "adcs"):
            assert expected in output

    def test_command_page_includes_the_tool_header(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        tool = database.get("nxc")
        renderer.print_command_page(tool, tool.commands[0])
        output = collect(renderer, buffer)
        assert output.splitlines()[0].strip() == "nxc"
        assert "─" * RULE_WIDTH in output
        assert "SMB" in output

    def test_tool_without_commands(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_tool(Tool(name="empty", description="No commands yet.", commands=()))
        assert "No commands are documented" in collect(renderer, buffer)


class TestListRendering:
    def test_table_contains_every_tool(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        renderer.print_tool_list(database.tools)
        output = collect(renderer, buffer)
        for tool in database.tools:
            assert tool.name in output
        assert "2 tool(s), 6 command(s) available." in output
        assert "Usage:" in output

    def test_issues_are_summarised(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        issues = [LoadIssue(path="/tmp/broken.yaml", message="invalid YAML")]
        renderer.print_tool_list(database.tools, issues=issues)
        assert "1 file(s) produced warnings or were skipped" in collect(renderer, buffer)

    def test_issue_table(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_issues(
            [
                LoadIssue(path="/tmp/a.yaml", message="invalid YAML"),
                LoadIssue(path="/tmp/b.yaml", message="no commands", level="warning"),
            ]
        )
        output = collect(renderer, buffer)
        assert "invalid YAML" in output
        assert "warning" in output

    def test_no_issues_prints_nothing(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_issues([])
        assert collect(renderer, buffer) == ""


class TestSearchRendering:
    def test_groups_results_by_tool(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        hits = search("kerberos", database.tools)
        renderer.print_search_results("kerberos", hits)
        output = collect(renderer, buffer)
        assert "Search results for 'kerberos'" in output
        assert "certipy" in output
        assert "nxc" in output
        assert "matched: command description" in output
        assert "never runs commands" in output

    def test_tool_hits_show_command_context(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        hits = search("enumerating", database.tools)
        renderer.print_search_results("enumerating", hits, context=1)
        output = collect(renderer, buffer)
        assert "certipy" in output
        assert "certipy find -u <username>" in output
        assert "1 more command(s), run 'synx certipy'" in output

    def test_context_is_not_repeated_when_commands_already_match(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        hits = search("Certificate Services", database.tools)
        renderer.print_search_results("certificate services", hits, context=3)
        output = collect(renderer, buffer)
        assert "more command(s)" not in output
        assert "certipy find -u <username>" in output

    def test_context_can_be_disabled(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        hits = search("enumerating", database.tools)
        renderer.print_search_results("enumerating", hits, context=0)
        output = collect(renderer, buffer)
        assert "more command(s)" not in output
        assert "certipy find" not in output


class TestMessages:
    def test_suggestions(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_suggestions(
            "Tool 'ceripy' was not found.",
            ["certipy"],
            hint="Run 'synx --list' to see every tool.",
        )
        output = collect(renderer, buffer)
        assert "Tool 'ceripy' was not found." in output
        assert "Did you mean:" in output
        assert "  certipy" in output
        assert "synx --list" in output

    def test_fallback_text(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_suggestions("Search term 'zzz' was not found.", [], fallback="No matches.")
        output = collect(renderer, buffer)
        assert "No matches." in output

    def test_no_suggestions_at_all(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_suggestions("Tool 'zzz' was not found.", [])
        assert "No close matches were found." in collect(renderer, buffer)

    def test_error_with_hint(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_error("Boom", hint="Try --help")
        output = collect(renderer, buffer)
        assert "Boom" in output
        assert "Try --help" in output

    def test_version_and_note(self, renderer: Renderer, buffer: io.StringIO) -> None:
        renderer.print_version("1.0.0")
        renderer.print_note("a note")
        output = collect(renderer, buffer)
        assert "synx 1.0.0" in output
        assert "a note" in output

    def test_json_output_is_parseable_and_unwrapped(self, buffer: io.StringIO) -> None:
        renderer = Renderer(console=make_console(buffer))
        payload = {"syntax": "certipy find " + "x" * 300}
        renderer.print_json(payload)
        text = collect(renderer, buffer)
        assert json.loads(text) == payload
        assert max(len(line) for line in text.splitlines()) > 200


class TestInfoRendering:
    def test_info_lists_the_database_locations(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        renderer.print_info(
            version="1.0.0",
            summary=database.summary(),
            package_path="/usr/lib/python3/site-packages/synx",
            python_version="3.12.0",
            active_paths=[str(path) for path in database.paths],
        )
        output = collect(renderer, buffer)
        assert "synx 1.0.0" in output
        assert "never executes commands" in output
        assert "2 tool(s), 6 command(s)" in output
        assert "Database locations" in output
        assert next(iter(database.paths)).name in output
        assert "*" in output

    def test_info_reports_issues(
        self, renderer: Renderer, buffer: io.StringIO, database: CommandDatabase
    ) -> None:
        renderer.print_issues(database.issues)
        renderer.print_info(
            version="1.0.0",
            summary=database.summary(),
            package_path="/pkg",
            python_version="3.12.0",
        )
        assert "occurred while loading" not in collect(renderer, buffer)
