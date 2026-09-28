"""Tests for loading and querying the YAML database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from synx.database import (
    DATABASE_ENV_VAR,
    CommandDatabase,
    DatabaseError,
    resolve_database_paths,
)
from synx.models import ToolNotFoundError
from tests.data import CERTIPY_YAML, NXC_YAML, write_yaml


class TestLoading:
    def test_loads_every_yaml_file_in_a_directory(self, database: CommandDatabase) -> None:
        assert [tool.name for tool in database.tools] == ["certipy", "nxc"]
        assert database.tool_count == 2
        assert database.command_count == 6
        assert len(database) == 2
        assert "nxc" in database
        assert "missing" not in database

    def test_tool_metadata_is_preserved(self, database: CommandDatabase) -> None:
        tool = database.get("nxc")
        assert tool.description == "Network service enumeration and administration tool."
        assert tool.aliases == ("netexec", "crackmapexec")
        assert tool.category == "active-directory"
        assert tool.source is not None and tool.source.endswith("nxc.yaml")

    def test_yml_extension_is_supported(self, tmp_path: Path) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "demo.yml", NXC_YAML)
        database = CommandDatabase([directory])
        database.load()
        assert [tool.name for tool in database.tools] == ["nxc"]

    def test_non_yaml_files_are_ignored(self, tmp_path: Path) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "nxc.yaml", NXC_YAML)
        write_yaml(directory, "README.md", "# not a tool")
        write_yaml(directory, "nxc.json", "{}")
        database = CommandDatabase([directory])
        database.load()
        assert database.tool_count == 1
        assert database.issues == ()

    def test_locations_report_file_and_tool_counts(self, database: CommandDatabase) -> None:
        (location,) = database.locations
        assert location.kind == "explicit"
        assert location.file_count == 2
        assert location.tool_count == 2

    def test_later_directories_override_tools(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        override = tmp_path / "override"
        write_yaml(base, "nxc.yaml", NXC_YAML)
        write_yaml(override, "nxc.yaml", NXC_YAML.replace("nxc 0.3", "nxc 1.0"))
        database = CommandDatabase([(base, "bundled"), (override, "user")])
        database.load()
        assert database.tool_count == 1
        assert database.get("nxc").commands[-1].version == "nxc 1.0 and later"
        overrides = [issue for issue in database.issues if "overrides" in issue.message]
        assert len(overrides) == 1
        assert overrides[0].level == "warning"

    def test_reload_discards_previous_state(self, tools_directory: Path) -> None:
        database = CommandDatabase([tools_directory])
        database.load()
        assert database.tool_count == 2
        write_yaml(tools_directory, "extra.yaml", CERTIPY_YAML.replace("certipy", "extra"))
        database.reload()
        assert database.tool_count == 3
        (tools_directory / "extra.yaml").unlink()
        database.reload()
        assert database.tool_count == 2

    def test_missing_directory_is_reported(self, tmp_path: Path) -> None:
        write_yaml(tmp_path / "tools", "nxc.yaml", NXC_YAML)
        database = CommandDatabase(
            [(tmp_path / "absent", "explicit"), (tmp_path / "tools", "user")]
        )
        database.load()
        assert database.tool_count == 1
        assert [issue.message for issue in database.issues if "does not exist" in issue.message]


class TestMalformedInput:
    def test_invalid_yaml_is_skipped_and_reported(self, tmp_path: Path) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "nxc.yaml", NXC_YAML)
        write_yaml(directory, "broken.yaml", "name: [unclosed\n")
        database = CommandDatabase([directory])
        database.load()
        assert [tool.name for tool in database.tools] == ["nxc"]
        assert len(database.errors) == 1
        assert "invalid YAML" in database.errors[0].message
        assert database.errors[0].path.endswith("broken.yaml")

    @pytest.mark.parametrize(
        ("filename", "content", "expected"),
        [
            ("no_name.yaml", "commands: []\n", "missing required key 'name'"),
            ("no_commands.yaml", "name: demo\n", "missing required key 'commands'"),
            ("bad_syntax.yaml", "name: demo\ncommands:\n  - name: a\n", "command #0"),
            ("not_a_list.yaml", "name: demo\ncommands: {a: b}\n", "must be a list of commands"),
            ("list_file.yaml", "- a\n- b\n", "expected a YAML mapping"),
        ],
    )
    def test_schema_errors_are_reported_per_file(
        self, tmp_path: Path, filename: str, content: str, expected: str
    ) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "nxc.yaml", NXC_YAML)
        write_yaml(directory, filename, content)
        database = CommandDatabase([directory])
        database.load()
        assert [tool.name for tool in database.tools] == ["nxc"]
        assert any(expected in issue.message for issue in database.errors)

    def test_empty_file_is_only_a_warning(self, tmp_path: Path) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "nxc.yaml", NXC_YAML)
        write_yaml(directory, "empty.yaml", "\n")
        database = CommandDatabase([directory])
        database.load()
        assert database.tool_count == 1
        assert database.errors == ()
        assert "file is empty" in database.warnings[0].message

    def test_tool_without_commands_is_a_warning(self, tmp_path: Path) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "empty_tool.yaml", "name: demo\ndescription: Demo.\ncommands: []\n")
        database = CommandDatabase([directory])
        database.load()
        assert database.tool_count == 1
        assert "has no commands" in database.warnings[0].message

    def test_database_error_when_nothing_can_be_loaded(self, tmp_path: Path) -> None:
        directory = tmp_path / "tools"
        write_yaml(directory, "broken.yaml", "name: [unclosed\n")
        database = CommandDatabase([directory])
        with pytest.raises(DatabaseError, match="No tools could be loaded"):
            database.load()

    def test_database_error_without_any_directory(self, tmp_path: Path) -> None:
        database = CommandDatabase([])
        with pytest.raises(DatabaseError, match="No database directory found"):
            database.load()

    def test_summary_serialises(self, database: CommandDatabase) -> None:
        summary = database.summary()
        assert summary.tool_count == 2
        assert summary.command_count == 6
        data = summary.to_dict()
        assert data["tool_count"] == 2
        assert data["locations"][0]["kind"] == "explicit"


class TestLookup:
    @pytest.mark.parametrize(
        "query", ["nxc", "NXC", " netexec ", "NetExec", "crackmapexec", "nxc.exe"]
    )
    def test_find_accepts_names_and_aliases(self, database: CommandDatabase, query: str) -> None:
        assert database.find(query) is not None

    def test_find_returns_none_for_unknown_names(self, database: CommandDatabase) -> None:
        assert database.find("ceripy") is None
        assert database.find("") is None

    def test_get_raises_for_unknown_names(self, database: CommandDatabase) -> None:
        with pytest.raises(ToolNotFoundError):
            database.get("ceripy")

    def test_find_command(self, database: CommandDatabase) -> None:
        assert database.find_command("nxc", "smb").name == "SMB"
        assert database.find_command("nxc", "nope") is None
        assert database.find_command("nope", "smb") is None

    def test_candidate_names_include_aliases(self, database: CommandDatabase) -> None:
        assert database.candidate_names() == (
            "certipy",
            "nxc",
            "netexec",
            "crackmapexec",
        )

    def test_command_candidates(self, database: CommandDatabase) -> None:
        assert "SMB" in database.command_candidates("nxc")
        assert database.command_candidates("nope") == ()

    def test_categories(self, database: CommandDatabase) -> None:
        assert database.categories() == ("active-directory",)

    def test_iteration_and_to_dict(self, database: CommandDatabase) -> None:
        assert [tool.name for tool in database] == ["certipy", "nxc"]
        data = database.to_dict()
        assert data["command_count"] == 6
        assert data["tools"][0]["name"] == "certipy"

    def test_lazy_loading(self, tools_directory: Path) -> None:
        database = CommandDatabase([tools_directory])
        assert database.loaded is False
        assert database.tool_count == 2
        assert database.loaded is True


class TestPathResolution:
    def test_explicit_paths_replace_the_defaults(self, tmp_path: Path) -> None:
        paths = resolve_database_paths([tmp_path], env={DATABASE_ENV_VAR: "/ignored"})
        assert paths == [(tmp_path, "explicit")]

    def test_environment_variable_is_used(self, tmp_path: Path) -> None:
        env = {DATABASE_ENV_VAR: os.pathsep.join([str(tmp_path), str(tmp_path / "more")])}
        assert resolve_database_paths(env=env) == [
            (tmp_path, "environment"),
            (tmp_path / "more", "environment"),
        ]

    def test_existing_default_directories_are_merged(self, tmp_path: Path) -> None:
        user = tmp_path / "synx" / "tools"
        user.mkdir(parents=True)
        env = {"XDG_DATA_HOME": str(tmp_path)}
        paths = dict((path, kind) for path, kind in resolve_database_paths(env=env))
        assert paths.get(user) == "user"
        kinds = {kind for kind in paths.values()}
        assert "source" in kinds

    def test_duplicates_are_removed(self, tmp_path: Path) -> None:
        env = {DATABASE_ENV_VAR: f"{tmp_path}{os.pathsep}{tmp_path}"}
        assert resolve_database_paths(env=env) == [(tmp_path, "environment")]

    def test_database_reads_paths_from_a_tuple(self, tmp_path: Path) -> None:
        write_yaml(tmp_path, "nxc.yaml", NXC_YAML)
        database = CommandDatabase([tmp_path])
        assert database.paths == (tmp_path,)
        database.load()
        assert database.tool_count == 1
