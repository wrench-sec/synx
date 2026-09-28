"""Data models and schema validation for the synx command database.

This module is deliberately free of I/O: it only turns plain Python mappings
(as produced by :mod:`yaml`) into validated, immutable domain objects.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Command",
    "CommandNotFoundError",
    "DatabaseError",
    "SynxError",
    "Tool",
    "ToolNotFoundError",
    "ToolValidationError",
    "normalise_query",
]

_SEPARATOR_RE = re.compile(r"[\s_/\\-]+")
_SCRIPT_SUFFIXES = (".py", ".exe", ".ps1", ".sh", ".rb")


class SynxError(Exception):
    """Base class for every error raised by synx."""


class DatabaseError(SynxError):
    """Raised when the YAML command database cannot be used."""


class ToolValidationError(DatabaseError):
    """Raised when a YAML document does not match the documented schema."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        self.reason = message
        super().__init__(f"{source}: {message}" if source else message)


class ToolNotFoundError(SynxError):
    """Raised when a tool name is not present in the database."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Tool '{name}' was not found.")


class CommandNotFoundError(SynxError):
    """Raised when a command is not present in the requested tool."""

    def __init__(self, name: str, tool_name: str) -> None:
        self.name = name
        self.tool_name = tool_name
        super().__init__(f"Command '{name}' was not found in tool '{tool_name}'.")


def normalise_query(value: str) -> str:
    """Normalise user input so that ``NetExec``, ``net_exec`` and ``net exec`` match.

    Lower-cases the value, collapses separators into single spaces and strips a
    trailing script suffix such as ``.py`` or ``.exe``.
    """
    text = value.strip().casefold()
    for suffix in _SCRIPT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return _SEPARATOR_RE.sub(" ", text).strip()


def _first_sentence(description: str) -> str:
    """Return the first sentence of ``description`` with a trailing period."""
    text = " ".join(description.split())
    if not text:
        return ""
    head, separator, _rest = text.partition(". ")
    if separator:
        return f"{head}."
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _require_mapping(data: Any, *, source: str | None) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        kind = type(data).__name__
        raise ToolValidationError(
            f"expected a mapping at the top level, got {kind}", source=source
        )
    return data


def _require_text(data: Mapping[str, Any], key: str, *, source: str | None) -> str:
    if key not in data:
        raise ToolValidationError(f"missing required key '{key}'", source=source)
    value = data[key]
    if value is None:
        raise ToolValidationError(f"key '{key}' must be a string, got null", source=source)
    if not isinstance(value, str):
        raise ToolValidationError(
            f"key '{key}' must be a string, got {type(value).__name__}", source=source
        )
    text = value.strip()
    if not text:
        raise ToolValidationError(f"key '{key}' must not be empty", source=source)
    return text


def _optional_text(data: Mapping[str, Any], key: str, *, source: str | None) -> str | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if not isinstance(value, str):
        raise ToolValidationError(
            f"key '{key}' must be a string, got {type(value).__name__}", source=source
        )
    text = value.strip()
    return text or None


def _optional_text_tuple(
    data: Mapping[str, Any], key: str, *, source: str | None
) -> tuple[str, ...]:
    if key not in data or data[key] is None:
        return ()
    value = data[key]
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ToolValidationError(
            f"key '{key}' must be a list of strings, got {type(value).__name__} "
            "(use a YAML list, for example: tags: [smb, ldap])",
            source=source,
        )
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ToolValidationError(
                f"key '{key}[{index}]' must be a string, got {type(item).__name__}",
                source=source,
            )
        text = item.strip()
        if text:
            items.append(text)
    return tuple(items)


@dataclass(frozen=True, slots=True)
class Command:
    """A single documented command of a tool."""

    name: str
    syntax: str
    description: str = ""
    tags: tuple[str, ...] = ()
    notes: str | None = None
    version: str | None = None
    example: str | None = None

    @classmethod
    def from_mapping(
        cls, data: Any, *, source: str | None = None, index: int | None = None
    ) -> Command:
        """Build a :class:`Command` from a YAML mapping, validating the schema."""
        where = f"command #{index}" if index is not None else "command"
        mapping = _require_mapping(data, source=source)
        try:
            name = _require_text(mapping, "name", source=source)
            syntax = _require_text(mapping, "syntax", source=source)
            description = _optional_text(mapping, "description", source=source) or ""
            tags = _optional_text_tuple(mapping, "tags", source=source)
            notes = _optional_text(mapping, "notes", source=source)
            version = _optional_text(mapping, "version", source=source)
            example = _optional_text(mapping, "example", source=source)
        except ToolValidationError as exc:
            raise ToolValidationError(f"{where}: {exc.reason}", source=source) from exc
        return cls(
            name=name,
            syntax=syntax,
            description=description,
            tags=tags,
            notes=notes,
            version=version,
            example=example,
        )

    @property
    def executable(self) -> str:
        """The leading binary of the syntax string, e.g. ``impacket-secretsdump``."""
        parts = self.syntax.split()
        return parts[0] if parts else self.name

    @property
    def summary(self) -> str:
        """First sentence of the description, used for compact listings."""
        return _first_sentence(self.description)

    def search_keys(self) -> tuple[str, ...]:
        """Lower-cased strings that this command should match against."""
        return (
            self.name.casefold(),
            self.syntax.casefold(),
            self.description.casefold(),
            *(tag.casefold() for tag in self.tags),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the command."""
        data: dict[str, Any] = {
            "name": self.name,
            "syntax": self.syntax,
            "description": self.description,
        }
        if self.tags:
            data["tags"] = list(self.tags)
        if self.notes:
            data["notes"] = self.notes
        if self.version:
            data["version"] = self.version
        if self.example:
            data["example"] = self.example
        return data


@dataclass(frozen=True, slots=True)
class Tool:
    """A documented tool and the commands it exposes."""

    name: str
    description: str = ""
    commands: tuple[Command, ...] = ()
    aliases: tuple[str, ...] = ()
    category: str | None = None
    homepage: str | None = None
    notes: str | None = None
    source: str | None = None

    @classmethod
    def from_mapping(cls, data: Any, *, source: str | None = None) -> Tool:
        """Build a :class:`Tool` from a YAML document, validating the schema."""
        mapping = _require_mapping(data, source=source)
        name = _require_text(mapping, "name", source=source)
        description = _optional_text(mapping, "description", source=source) or ""
        aliases = _optional_text_tuple(mapping, "aliases", source=source)
        category = _optional_text(mapping, "category", source=source)
        homepage = _optional_text(mapping, "homepage", source=source)
        notes = _optional_text(mapping, "notes", source=source)

        raw_commands = mapping.get("commands")
        if raw_commands is None:
            raise ToolValidationError("missing required key 'commands'", source=source)
        if isinstance(raw_commands, (str, bytes, Mapping)) or not isinstance(
            raw_commands, Iterable
        ):
            raise ToolValidationError(
                f"key 'commands' must be a list of commands, got "
                f"{type(raw_commands).__name__}",
                source=source,
            )
        commands = tuple(
            Command.from_mapping(entry, source=source, index=position)
            for position, entry in enumerate(raw_commands)
        )
        return cls(
            name=name,
            description=description,
            commands=commands,
            aliases=aliases,
            category=category,
            homepage=homepage,
            notes=notes,
            source=source,
        )

    @property
    def display_name(self) -> str:
        """The canonical name of the tool."""
        return self.name

    @property
    def command_count(self) -> int:
        return len(self.commands)

    @property
    def summary_description(self) -> str:
        """First sentence of the description, used for compact listings."""
        return _first_sentence(self.description)

    @property
    def searchable_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    def find_command(self, query: str) -> Command:
        """Return the command matching ``query``.

        Matching is case-insensitive and also considers the leading binary of
        the syntax string and the command tags.
        """
        command = self.get_command(query)
        if command is None:
            raise CommandNotFoundError(query, self.name)
        return command

    def get_command(self, query: str) -> Command | None:
        """Return the command matching ``query`` or ``None`` when absent.

        Exact name matches win, followed by the leading binary of the syntax
        string and the tags. As a last resort a command name containing the
        query is accepted, provided the query is at least three characters long
        so that very short queries fall through to the caller's suggestions.
        """
        wanted = normalise_query(query)
        if not wanted:
            return None
        for command in self.commands:
            if normalise_query(command.name) == wanted:
                return command
        for command in self.commands:
            if normalise_query(command.executable) == wanted:
                return command
        for command in self.commands:
            if any(normalise_query(tag) == wanted for tag in command.tags):
                return command
        if len(wanted) >= 3:
            for command in self.commands:
                if wanted in normalise_query(command.name):
                    return command
        return None

    def search_keys(self) -> tuple[str, ...]:
        return (
            self.name.casefold(),
            *(alias.casefold() for alias in self.aliases),
            self.description.casefold(),
            (self.category or "").casefold(),
        )

    def with_source(self, source: str | None) -> Tool:
        """Return a copy of the tool that records where it was loaded from."""
        if source == self.source:
            return self
        return Tool(
            name=self.name,
            description=self.description,
            commands=self.commands,
            aliases=self.aliases,
            category=self.category,
            homepage=self.homepage,
            notes=self.notes,
            source=source,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the tool."""
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "commands": [command.to_dict() for command in self.commands],
        }
        if self.aliases:
            data["aliases"] = list(self.aliases)
        if self.category:
            data["category"] = self.category
        if self.homepage:
            data["homepage"] = self.homepage
        if self.notes:
            data["notes"] = self.notes
        if self.source:
            data["source"] = self.source
        return data
