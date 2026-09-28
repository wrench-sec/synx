"""Loading, merging and querying of the YAML command database.

The database is a directory (or a list of directories) containing ``*.yaml``
files. Every file describes exactly one tool, so adding a new tool only
requires dropping a new YAML file into the directory.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from synx.models import (
    Command,
    DatabaseError,
    Tool,
    ToolNotFoundError,
    ToolValidationError,
    normalise_query,
)

__all__ = [
    "DATABASE_ENV_VAR",
    "CommandDatabase",
    "DatabaseLocation",
    "DatabaseSummary",
    "LoadIssue",
    "resolve_database_paths",
    "user_database_directory",
]

DATABASE_ENV_VAR = "SYNX_DB_PATH"
BUNDLED_DIRECTORY = "_bundled_tools"
YAML_SUFFIXES = (".yaml", ".yml")


@dataclass(frozen=True, slots=True)
class LoadIssue:
    """A non-fatal problem encountered while loading a YAML file."""

    path: str
    message: str
    level: str = "error"

    @property
    def is_error(self) -> bool:
        return self.level == "error"

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "level": self.level, "message": self.message}


@dataclass(frozen=True, slots=True)
class DatabaseLocation:
    """A directory that was searched for YAML files."""

    path: Path
    kind: str
    file_count: int = 0
    tool_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "file_count": self.file_count,
            "tool_count": self.tool_count,
        }


@dataclass(frozen=True, slots=True)
class DatabaseSummary:
    """Aggregated information about a loaded database."""

    locations: tuple[DatabaseLocation, ...] = ()
    tool_count: int = 0
    command_count: int = 0
    issues: tuple[LoadIssue, ...] = ()

    @property
    def errors(self) -> tuple[LoadIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_error)

    @property
    def warnings(self) -> tuple[LoadIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_count": self.tool_count,
            "command_count": self.command_count,
            "locations": [location.to_dict() for location in self.locations],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _bundled_directory() -> Path | None:
    """Return the directory holding the YAML files shipped inside the wheel."""
    try:
        from importlib.resources import files
    except ImportError:  # pragma: no cover - Python < 3.9
        return None
    try:
        resource = files("synx") / BUNDLED_DIRECTORY
    except (ImportError, ModuleNotFoundError, TypeError):  # pragma: no cover
        return None
    path = Path(str(resource))
    return path if path.is_dir() else None


def _user_directory(env: Mapping[str, str]) -> Path:
    """Return the per-user tools directory, following the XDG base dir spec."""
    data_home = env.get("XDG_DATA_HOME", "").strip()
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "synx" / "tools"


def _source_directory() -> Path | None:
    """Return the ``tools/`` directory of a source checkout, if present."""
    path = Path(__file__).resolve().parent.parent / "tools"
    return path if path.is_dir() else None


def user_database_directory(env: Mapping[str, str] | None = None) -> Path:
    """Return the per-user tools directory, which ``--update`` refreshes.

    It sits after the bundled directory in precedence, so definitions written
    here override the ones shipped in the wheel without needing a reinstall.
    """
    return _user_directory(os.environ if env is None else env)


def _split_path_list(value: str) -> list[Path]:
    return [Path(entry) for entry in value.split(os.pathsep) if entry.strip()]


def resolve_database_paths(
    explicit: Sequence[str | Path] | None = None, *, env: Mapping[str, str] | None = None
) -> list[tuple[Path, str]]:
    """Resolve the database directories to load, lowest precedence first.

    ``explicit`` values (from ``--db-path``) or the ``SYNX_DB_PATH`` environment
    variable restrict the search to those directories only, and are reported
    even when they do not exist. Otherwise the bundled database, the per-user
    directory and a source checkout are merged, with later entries overriding
    tools of the same name. Optional directories that do not exist are skipped.
    """
    environ = os.environ if env is None else env

    if explicit:
        return _deduplicate([(Path(entry), "explicit") for entry in explicit])

    from_env = environ.get(DATABASE_ENV_VAR, "")
    if from_env.strip():
        return _deduplicate([(path, "environment") for path in _split_path_list(from_env)])

    candidates: list[tuple[Path, str]] = []
    bundled = _bundled_directory()
    if bundled is not None:
        candidates.append((bundled, "bundled"))
    candidates.append((_user_directory(environ), "user"))
    source = _source_directory()
    if source is not None:
        candidates.append((source, "source"))
    return _deduplicate([entry for entry in candidates if entry[0].is_dir()])


def _deduplicate(entries: Sequence[tuple[Path, str]]) -> list[tuple[Path, str]]:
    seen: dict[Path, str] = {}
    for path, kind in entries:
        key = _canonical(path)
        if key not in seen:
            seen[key] = kind
    return [(path, seen[path]) for path in seen]


def _canonical(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:  # pragma: no cover - unreadable path
        return path


@dataclass
class _LoadResult:
    tools: dict[str, Tool] = field(default_factory=dict)
    issues: list[LoadIssue] = field(default_factory=list)
    file_count: int = 0


class CommandDatabase:
    """An in-memory, read-only view over the YAML tool definitions."""

    def __init__(self, paths: Sequence[tuple[Path, str] | Path] | None = None) -> None:
        self._paths: tuple[tuple[Path, str], ...] = _normalise_paths(paths)
        self._tools: dict[str, Tool] = {}
        self._issues: list[LoadIssue] = []
        self._locations: list[DatabaseLocation] = []
        self._loaded = False

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(path for path, _kind in self._paths)

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def tools(self) -> tuple[Tool, ...]:
        """All loaded tools, sorted by name."""
        self._ensure_loaded()
        return tuple(self._tools[key] for key in sorted(self._tools))

    @property
    def issues(self) -> tuple[LoadIssue, ...]:
        return tuple(self._issues)

    @property
    def locations(self) -> tuple[DatabaseLocation, ...]:
        return tuple(self._locations)

    @property
    def tool_count(self) -> int:
        self._ensure_loaded()
        return len(self._tools)

    @property
    def command_count(self) -> int:
        self._ensure_loaded()
        return sum(tool.command_count for tool in self._tools.values())

    @property
    def errors(self) -> tuple[LoadIssue, ...]:
        """Files that were skipped because they could not be loaded."""
        return tuple(issue for issue in self.issues if issue.is_error)

    @property
    def warnings(self) -> tuple[LoadIssue, ...]:
        """Non-fatal problems, such as duplicate or incomplete definitions."""
        return tuple(issue for issue in self.issues if not issue.is_error)

    def __len__(self) -> int:
        return self.tool_count

    def __iter__(self) -> Iterator[Tool]:
        return iter(self.tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.find(name) is not None

    def load(self) -> None:
        """Load every YAML file from the configured directories."""
        self.reload()

    def reload(self) -> None:
        """Re-read the database from disk, discarding any previous state."""
        tools: dict[str, Tool] = {}
        issues: list[LoadIssue] = []
        locations: list[DatabaseLocation] = []

        for path, kind in self._paths:
            result = self._load_directory(path)
            issues.extend(result.issues)
            for key, tool in result.tools.items():
                existing = tools.get(key)
                if existing is not None:
                    issues.append(
                        LoadIssue(
                            path=str(path),
                            message=(
                                f"tool '{tool.name}' overrides the definition from "
                                f"{existing.source or 'an earlier directory'}"
                            ),
                            level="warning",
                        )
                    )
                tools[key] = tool
            locations.append(
                DatabaseLocation(
                    path=path,
                    kind=kind,
                    file_count=result.file_count,
                    tool_count=len(result.tools),
                )
            )

        self._tools = dict(sorted(tools.items(), key=lambda item: item[0].casefold()))
        self._issues = issues
        self._locations = locations
        self._loaded = True

        if not self._paths:
            raise DatabaseError(
                "No database directory found. Pass --db-path or set "
                f"{DATABASE_ENV_VAR} to point at a directory of YAML files."
            )
        if not self._tools:
            detail = ""
            if issues:
                first = issues[0]
                detail = f" First problem: {first.path}: {first.message}"
            raise DatabaseError(
                "No tools could be loaded from the configured database directories."
                + detail
            )

    def get(self, name: str) -> Tool:
        """Return the tool named ``name`` (or one of its aliases).

        Raises:
            ToolNotFoundError: when no tool matches.
        """
        tool = self.find(name)
        if tool is None:
            raise ToolNotFoundError(name)
        return tool

    def find(self, name: str) -> Tool | None:
        """Return the tool matching ``name`` exactly, by alias or case-insensitively."""
        self._ensure_loaded()
        wanted = normalise_query(name)
        if not wanted:
            return None
        for tool in self._tools.values():
            if tool.name.casefold() == name.strip().casefold():
                return tool
        for tool in self._tools.values():
            if any(alias.casefold() == name.strip().casefold() for alias in tool.aliases):
                return tool
        for tool in self._tools.values():
            if normalise_query(tool.name) == wanted:
                return tool
        for tool in self._tools.values():
            if any(normalise_query(alias) == wanted for alias in tool.aliases):
                return tool
        return None

    def find_command(self, tool_name: str, command_name: str) -> Command | None:
        """Return a command of a tool, or ``None`` when either is unknown."""
        tool = self.find(tool_name)
        if tool is None:
            return None
        return tool.get_command(command_name)

    def candidate_names(self) -> tuple[str, ...]:
        """Every tool name and alias, suitable for fuzzy matching."""
        names: list[str] = []
        for tool in self.tools:
            names.extend(tool.searchable_names)
        return tuple(names)

    def command_candidates(self, tool_name: str) -> tuple[str, ...]:
        """Every command name of a tool, suitable for fuzzy matching."""
        tool = self.find(tool_name)
        if tool is None:
            return ()
        return tuple(command.name for command in tool.commands)

    def categories(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {tool.category for tool in self.tools if tool.category},
                key=str.casefold,
            )
        )

    def summary(self) -> DatabaseSummary:
        self._ensure_loaded()
        return DatabaseSummary(
            locations=self.locations,
            tool_count=self.tool_count,
            command_count=self.command_count,
            issues=self.issues,
        )

    def to_dict(self) -> dict[str, Any]:
        self._ensure_loaded()
        return {
            "tool_count": self.tool_count,
            "command_count": self.command_count,
            "tools": [tool.to_dict() for tool in self.tools],
        }

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.reload()

    def _load_directory(self, path: Path) -> _LoadResult:
        result = _LoadResult()
        if not path.is_dir():
            result.issues.append(
                LoadIssue(path=str(path), message="directory does not exist", level="warning")
            )
            return result
        for file in _iter_yaml_files(path):
            result.file_count += 1
            tool, issue = _load_file(file)
            if tool is None:
                if issue is not None:
                    result.issues.append(issue)
                continue
            if not tool.description:
                result.issues.append(
                    LoadIssue(
                        path=str(file),
                        message=f"tool '{tool.name}' has no description",
                        level="warning",
                    )
                )
            if not tool.commands:
                result.issues.append(
                    LoadIssue(
                        path=str(file),
                        message=f"tool '{tool.name}' has no commands",
                        level="warning",
                    )
                )
            if tool.name in result.tools:
                result.issues.append(
                    LoadIssue(
                        path=str(file),
                        message=f"duplicate tool '{tool.name}' in the same directory",
                        level="warning",
                    )
                )
            result.tools[tool.name] = tool.with_source(str(file))
        return result


def _normalise_paths(
    paths: Sequence[tuple[Path, str] | Path] | None,
) -> tuple[tuple[Path, str], ...]:
    if paths is None:
        return tuple(resolve_database_paths())
    normalised: list[tuple[Path, str]] = []
    for entry in paths:
        if isinstance(entry, tuple):
            path, kind = entry
        else:
            path, kind = entry, "explicit"
        normalised.append((_canonical(Path(path)), kind))
    return tuple(_deduplicate(normalised))


def _iter_yaml_files(path: Path) -> list[Path]:
    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    except OSError:  # pragma: no cover - unreadable directory
        return []
    return [
        entry
        for entry in entries
        if entry.suffix.casefold() in YAML_SUFFIXES and entry.is_file()
    ]


def _load_file(file: Path) -> tuple[Tool | None, LoadIssue | None]:
    try:
        raw = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, LoadIssue(path=str(file), message=f"could not read file: {exc}")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ").strip()
        return None, LoadIssue(path=str(file), message=f"invalid YAML: {detail}")
    if data is None:
        return None, LoadIssue(path=str(file), message="file is empty", level="warning")
    if not isinstance(data, dict):
        return None, LoadIssue(
            path=str(file),
            message=f"expected a YAML mapping, got {type(data).__name__}",
        )
    try:
        tool = Tool.from_mapping(data, source=str(file))
    except ToolValidationError as exc:
        return None, LoadIssue(path=str(file), message=exc.reason)
    return tool, None
