"""End-to-end tests for the synx command-line interface."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from synx import __version__
from synx.cli import EXIT_NOT_FOUND, EXIT_SUCCESS, EXIT_USAGE, build_parser, main
from tests.data import NXC_YAML, write_yaml

RunSynx = Callable[..., tuple[int, str]]


class TestParser:
    def test_help_is_available(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["--help"])
        assert excinfo.value.code == EXIT_SUCCESS

    def test_version(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == EXIT_SUCCESS
        assert __version__ in capsys.readouterr().out

    def test_positional_arguments_are_optional(self) -> None:
        args = build_parser().parse_args([])
        assert args.tool is None
        assert args.command is None
        assert args.search is None
        assert args.list is False

    def test_short_and_long_flags_are_equivalent(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["-l"]).list is True
        assert parser.parse_args(["--list"]).list is True
        assert parser.parse_args(["-i"]).info is True
        assert parser.parse_args(["-v"]).verbose is True

    @pytest.mark.parametrize("value", ["-1", "abc"])
    def test_invalid_context_value(self, value: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(["--context", value])
        assert excinfo.value.code == EXIT_USAGE


class TestToolDisplay:
    def test_shows_a_tool(self, run_synx: RunSynx) -> None:
        code, output = run_synx("nxc")
        assert code == EXIT_SUCCESS
        assert output.splitlines()[0] == "nxc"
        assert "Network service enumeration and administration tool." in output
        assert "SMB" in output
        assert "nxc smb <target> -d <domain> -u <username> -p <password>" in output
        assert "WinRM" in output
        assert "LDAP" in output

    def test_shows_a_single_command(self, run_synx: RunSynx) -> None:
        code, output = run_synx("nxc", "smb")
        assert code == EXIT_SUCCESS
        assert "SMB" in output
        assert "Connects to an SMB service" in output
        assert "WinRM" not in output

    def test_command_lookup_is_case_insensitive(self, run_synx: RunSynx) -> None:
        code, output = run_synx("nxc", "SMB")
        assert code == EXIT_SUCCESS
        assert "SMB" in output

    def test_resolves_aliases(self, run_synx: RunSynx) -> None:
        code, output = run_synx("netexec")
        assert code == EXIT_SUCCESS
        assert output.splitlines()[0] == "nxc"

    def test_json_output(self, run_synx: RunSynx) -> None:
        code, output = run_synx("nxc", "--json")
        assert code == EXIT_SUCCESS
        payload = json.loads(output)
        assert payload["name"] == "nxc"
        assert payload["commands"][0]["name"] == "SMB"

    def test_json_output_for_a_single_command(self, run_synx: RunSynx) -> None:
        code, output = run_synx("nxc", "smb", "--json")
        assert code == EXIT_SUCCESS
        payload = json.loads(output)
        assert payload["tool"] == "nxc"
        assert payload["command"]["name"] == "SMB"

    def test_verbose_shows_the_source_file(self, run_synx: RunSynx, tools_directory: Path) -> None:
        code, output = run_synx("nxc", "-v")
        assert code == EXIT_SUCCESS
        assert "nxc.yaml" in output

    def test_unknown_tool_suggests_a_close_match(self, run_synx: RunSynx) -> None:
        code, output = run_synx("ceripy")
        assert code == EXIT_NOT_FOUND
        assert "Tool 'ceripy' was not found." in output
        assert "Did you mean:" in output
        assert "certipy" in output
        assert "synx --list" in output

    def test_unknown_tool_without_suggestions(self, run_synx: RunSynx) -> None:
        code, output = run_synx("kubernetes")
        assert code == EXIT_NOT_FOUND
        assert "No close matches were found." in output

    def test_unknown_command_suggests_a_close_match(self, run_synx: RunSynx) -> None:
        code, output = run_synx("nxc", "sm")
        assert code == EXIT_NOT_FOUND
        assert "Command 'sm' was not found in tool 'nxc'." in output
        assert "SMB" in output


class TestList:
    def test_lists_every_tool(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--list")
        assert code == EXIT_SUCCESS
        assert "nxc" in output
        assert "certipy" in output
        assert "2 tool(s), 6 command(s) available." in output
        assert "Tool" in output
        assert "Category" in output

    def test_json_output(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--list", "--json")
        assert code == EXIT_SUCCESS
        payload = json.loads(output)
        assert [tool["name"] for tool in payload["tools"]] == ["certipy", "nxc"]


class TestSearch:
    def test_global_search(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--search", "kerberos")
        assert code == EXIT_SUCCESS
        assert "Search results for 'kerberos'" in output
        assert "certipy auth" in output
        assert "nxc ldap" in output

    def test_search_with_the_positional_keyword(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--search", "smb")
        assert code == EXIT_SUCCESS
        assert "Search results for 'smb'" in output

    def test_search_inside_a_single_tool(self, run_synx: RunSynx) -> None:
        code, output = run_synx("certipy", "--search", "kerberos")
        assert code == EXIT_SUCCESS
        assert "Searching only in 'certipy'." in output
        assert "1 tool(s), 1 command(s) matched." in output

    def test_search_for_an_unknown_tool(self, run_synx: RunSynx) -> None:
        code, output = run_synx("ceripy", "--search", "kerberos")
        assert code == EXIT_NOT_FOUND
        assert "Tool 'ceripy' was not found." in output

    def test_search_without_matches(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--search", "kubernetes")
        assert code == EXIT_NOT_FOUND
        assert "Search term 'kubernetes' was not found." in output
        assert "No tool, command or description matches this keyword." in output

    def test_search_requires_a_keyword(self, run_synx: RunSynx) -> None:
        with pytest.raises(SystemExit) as excinfo:
            run_synx("--search")
        assert excinfo.value.code == EXIT_USAGE

    def test_context_controls_the_number_of_commands(self, run_synx: RunSynx) -> None:
        _, output = run_synx("--search", "enumerating", "--context", "1")
        assert "1 more command(s), run 'synx certipy'" in output

    def test_json_output(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--search", "kerberos", "--json")
        assert code == EXIT_SUCCESS
        payload = json.loads(output)
        assert payload["keyword"] == "kerberos"
        assert payload["match_count"] == len(payload["results"])
        assert payload["results"][0]["tool"] == "certipy"

    def test_search_cannot_be_combined_with_a_command(self, run_synx: RunSynx) -> None:
        with pytest.raises(SystemExit) as excinfo:
            run_synx("nxc", "smb", "--search", "ldap")
        assert excinfo.value.code == EXIT_USAGE


class TestInfo:
    def test_info_reports_the_database(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--info")
        assert code == EXIT_SUCCESS
        assert f"synx {__version__}" in output
        assert "never executes commands" in output
        assert "2 tool(s), 6 command(s)" in output
        assert "Database locations" in output

    def test_reload_reports_the_same_information(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--reload")
        assert code == EXIT_SUCCESS
        assert "2 tool(s), 6 command(s)" in output

    def test_json_output(self, run_synx: RunSynx) -> None:
        code, output = run_synx("--info", "--json")
        assert code == EXIT_SUCCESS
        payload = json.loads(output)
        assert payload["version"] == __version__
        assert payload["database"]["tool_count"] == 2
        assert payload["database"]["locations"][0]["kind"] == "explicit"


class TestNoArguments:
    def test_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == EXIT_SUCCESS
        assert "usage: synx" in capsys.readouterr().out


class TestDatabaseHandling:
    def test_missing_database_directory(self, run_synx: RunSynx, tmp_path: Path) -> None:
        code, output = run_synx("nxc", db_path=tmp_path / "absent")
        assert code == 3  # EXIT_DATABASE_ERROR
        assert "Could not load the command database" in output
        assert "--db-path" in output

    def test_broken_files_are_skipped(self, run_synx: RunSynx, tools_directory: Path) -> None:
        write_yaml(tools_directory, "broken.yaml", "name: [unclosed\n")
        code, output = run_synx("--list")
        assert code == EXIT_SUCCESS
        assert "nxc" in output
        assert "1 file(s) produced warnings or were skipped" in output

    def test_verbose_reports_the_broken_file(
        self, run_synx: RunSynx, tools_directory: Path
    ) -> None:
        write_yaml(tools_directory, "broken.yaml", "name: [unclosed\n")
        code, output = run_synx("--list", "--verbose")
        assert code == EXIT_SUCCESS
        assert "broken.yaml" in output
        assert "invalid YAML" in output

    def test_a_new_tool_needs_no_code_change(
        self, run_synx: RunSynx, tools_directory: Path
    ) -> None:
        write_yaml(
            tools_directory,
            "brandnew.yaml",
            NXC_YAML.replace("name: nxc", "name: brandnew").replace("- name: SMB", "- name: run"),
        )
        code, output = run_synx("brandnew")
        assert code == EXIT_SUCCESS
        assert "brandnew" in output
        assert "run" in output
        assert run_synx("--list")[0] == EXIT_SUCCESS
        assert "brandnew" in run_synx("--list")[1]
