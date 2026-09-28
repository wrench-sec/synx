"""Terminal rendering for synx, built on :mod:`rich`.

The renderer is the only module that knows how output looks. It never executes
anything: it only formats strings that the database provides.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from rich import box
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from synx.database import DatabaseSummary, LoadIssue
from synx.models import Command, Tool
from synx.search import SearchHit
from synx.update import UpdateResult

__all__ = ["RULE_WIDTH", "Renderer", "highlight_syntax"]

RULE_WIDTH = 40
LABEL_STYLE = "dim"
SYNTAX_INDENT = 4
BODY_INDENT = 2
_HIGHLIGHT_RE = re.compile(
    r"(?P<placeholder><[A-Za-z0-9_.:/\- ]+?>)"
    r"|(?P<flag>(?<![\w-])--?[A-Za-z][A-Za-z0-9-]*)"
    r"|(?P<ellipsis>\.\.\.)"
)
_TOKEN_STYLES: dict[str, str] = {
    "placeholder": "bold magenta",
    "flag": "cyan",
    "ellipsis": "dim",
}


def highlight_syntax(syntax: str) -> Text:
    """Return ``syntax`` as a :class:`~rich.text.Text` with coloured tokens.

    The leading binary is bold green, ``<placeholders>`` are magenta and
    ``-flags`` are cyan.
    """
    text = Text()
    if not syntax:
        return text
    executable = syntax.split(" ", 1)[0]
    cursor = len(executable)
    text.append(executable, style="bold green" if not executable.startswith("<") else "")

    for match in _HIGHLIGHT_RE.finditer(syntax, cursor):
        if match.start() > cursor:
            text.append(syntax[cursor : match.start()])
        text.append(match.group(), style=_TOKEN_STYLES[match.lastgroup or "flag"])
        cursor = match.end()
    if cursor < len(syntax):
        text.append(syntax[cursor:])
    return text


def _add_command(branch: Tree, command: Command) -> Tree:
    """Add a command node with its syntax and description to a tree branch."""
    leaf = branch.add(Text(command.name, style="bold"))
    leaf.add(highlight_syntax(command.syntax))
    if command.description:
        leaf.add(Text(command.description))
    return leaf


class Renderer:
    """Formats synx output on a :class:`rich.console.Console`."""

    def __init__(
        self,
        console: Console | None = None,
        *,
        no_color: bool = False,
        width: int | None = None,
    ) -> None:
        self.console = console or Console(
            no_color=no_color,
            width=width,
            markup=False,
            emoji=False,
            highlight=False,
            soft_wrap=False,
        )
        self.no_color = no_color

    def blank(self) -> None:
        self.console.print()

    def print_tool(self, tool: Tool, *, show_source: bool = False) -> None:
        """Print the full reference page of a tool."""
        self.console.print(Text(tool.display_name, style="bold cyan"))
        self.rule()
        self.blank()
        if tool.description:
            self.console.print(Text(tool.description))
            self.blank()
        if tool.category:
            self._field("Category", tool.category)
        if tool.aliases:
            self._field("Aliases", ", ".join(tool.aliases))
        if tool.homepage:
            self._field("Homepage", tool.homepage)
        if show_source and tool.source:
            self._field("Source", tool.source)
        if tool.notes:
            self.blank()
            self.console.print(Text(tool.notes, style="italic dim"))
        if not tool.commands:
            self.blank()
            self.console.print(
                Text("No commands are documented for this tool yet.", style="yellow")
            )
            return
        for command in tool.commands:
            self.blank()
            self.print_command(command)
        self.blank()
        self.console.print(
            Text(
                f"{tool.command_count} command(s) documented. Use "
                f"'synx {tool.name} <command>' for a single command, or "
                "'synx --search <keyword>' to search the database.",
                style="dim",
            )
        )

    def print_command_page(self, tool: Tool, command: Command) -> None:
        """Print a single command of a tool, including the tool header."""
        self.console.print(Text(tool.display_name, style="bold cyan"))
        self.rule()
        self.blank()
        self.print_command(command)
        self.blank()
        self.console.print(
            Text(
                f"Command {command.name} of {tool.command_count} documented "
                f"for {tool.name}. Run 'synx {tool.name}' for all commands.",
                style="dim",
            )
        )

    def print_command(self, command: Command) -> None:
        """Print a single documented command."""
        self.console.print(Text(command.name, style="bold"))
        self._label("Syntax:")
        self._indented(highlight_syntax(command.syntax), SYNTAX_INDENT)
        if command.description:
            self.blank()
            self._label("Description:")
            self._indented(Text(command.description), SYNTAX_INDENT)
        if command.notes:
            self.blank()
            self._label("Notes:")
            self._indented(Text(command.notes, style="italic dim"), SYNTAX_INDENT)
        if command.version:
            self.blank()
            self._label("Version:")
            self._indented(Text(command.version, style="yellow dim"), SYNTAX_INDENT)
        if command.example:
            self.blank()
            self._label("Example:")
            self._indented(highlight_syntax(command.example), SYNTAX_INDENT)
        if command.tags:
            self.blank()
            self._indented(
                Text("Tags: " + ", ".join(command.tags), style="dim blue"), BODY_INDENT
            )

    def print_tool_list(self, tools: Sequence[Tool], *, issues: Sequence[LoadIssue] = ()) -> None:
        """Print the table of available tools."""
        table = Table(box=box.SIMPLE_HEAD, header_style="bold cyan", padding=(0, 2))
        table.add_column("Tool", style="bold", no_wrap=True)
        table.add_column("Category", style="magenta", no_wrap=True)
        table.add_column("Commands", justify="right", no_wrap=True)
        table.add_column("Description")
        for tool in tools:
            table.add_row(
                tool.name, tool.category or "-", str(tool.command_count), tool.summary_description
            )
        self.console.print(table)
        self.blank()
        total = sum(tool.command_count for tool in tools)
        self.console.print(
            Text(f"{len(tools)} tool(s), {total} command(s) available.", style="dim")
        )
        self.blank()
        self.console.print(Text("Usage:  synx <tool> [command]", style="dim"))
        self.console.print(Text("        synx --search <keyword>", style="dim"))
        if issues:
            self.blank()
            self.console.print(
                Text(
                    f"{len(issues)} file(s) produced warnings or were skipped "
                    "(run with --verbose for details).",
                    style="yellow",
                )
            )

    def print_search_results(
        self, keyword: str, hits: Sequence[SearchHit], *, context: int = 3
    ) -> None:
        """Print grouped search results for ``keyword``."""
        tool_hits = [hit for hit in hits if hit.command is None]
        command_hits = [hit for hit in hits if hit.command is not None]
        matched = {hit.tool.name for hit in hits}
        self.console.print(Text(f"Search results for '{keyword}'", style="bold cyan"))
        self.console.print(
            Text(
                f"{len(matched)} tool(s), {len(command_hits)} command(s) matched.",
                style="dim",
            )
        )
        self.blank()
        tree = Tree(Text("matches", style="dim"), guide_style="grey42")
        for name in sorted(matched, key=str.casefold):
            tool = next(hit.tool for hit in hits if hit.tool.name == name)
            branch = tree.add(Text(name, style="bold cyan"))
            for hit in [item for item in tool_hits if item.tool.name == name]:
                summary = branch.add(Text(hit.excerpt or hit.tool.description))
                summary.add(Text(f"matched: {hit.field_label}", style="dim"))
            tool_command_hits = [hit for hit in command_hits if hit.tool.name == name]
            if context and not tool_command_hits:
                for command in tool.commands[:context]:
                    _add_command(branch, command)
                remaining = tool.command_count - min(context, tool.command_count)
                if remaining > 0:
                    branch.add(
                        Text(
                            f"... {remaining} more command(s), run 'synx {name}'",
                            style="dim",
                        )
                    )
            for hit in tool_command_hits:
                if hit.command is None:  # pragma: no cover - filtered above
                    continue
                matched_node = _add_command(branch, hit.command)
                matched_node.add(Text(f"matched: {hit.field_label}", style="dim"))
        self.console.print(tree)
        self.blank()
        self.console.print(
            Text("synx only displays documented syntax; it never runs commands.", style="dim")
        )

    def print_suggestions(
        self,
        message: str,
        suggestions: Sequence[str],
        *,
        hint: str | None = None,
        fallback: str | None = None,
    ) -> None:
        """Print a 'not found' message followed by 'Did you mean' suggestions."""
        self.print_error(message)
        self.blank()
        if suggestions:
            self.console.print(Text("Did you mean:", style="bold"))
            for suggestion in suggestions:
                self.console.print(Text(f"  {suggestion}", style="cyan"))
        elif fallback:
            self.console.print(Text(fallback, style="dim"))
        else:
            self.console.print(Text("No close matches were found.", style="dim"))
        if hint:
            self.blank()
            self.console.print(Text(hint, style="dim"))

    def print_error(self, message: str, *, hint: str | None = None) -> None:
        """Print an error message with an optional hint."""
        self.console.print(Text(message, style="bold red"))
        if hint:
            self.console.print(Text(hint, style="dim"))

    def print_warning(self, message: str) -> None:
        self.console.print(Text(message, style="yellow"))

    def print_note(self, message: str) -> None:
        self.console.print(Text(message, style="dim"))

    def print_issues(self, issues: Sequence[LoadIssue]) -> None:
        """Print database load problems such as skipped or duplicate files."""
        if not issues:
            return
        table = Table(box=box.SIMPLE_HEAD, header_style="bold yellow", padding=(0, 1))
        table.add_column("Level", style="yellow", no_wrap=True)
        table.add_column("File", style="dim", overflow="fold", ratio=1)
        table.add_column("Problem", overflow="fold", ratio=2)
        for issue in issues:
            table.add_row(issue.level, issue.path, issue.message)
        self.console.print(table)

    def print_update(self, result: UpdateResult) -> None:
        """Print the outcome of a database refresh from a remote."""
        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            padding=(0, 2),
            show_header=False,
        )
        table.add_column("Change", style="bold", no_wrap=True)
        table.add_column("Tools", overflow="fold")
        for label, names in (
            ("added", result.added),
            ("updated", result.updated),
            ("unchanged", result.unchanged),
            ("removed", result.removed),
        ):
            if names:
                table.add_row(label, ", ".join(names))
        self.console.print(table)

        if result.local_only:
            self.console.print(
                Text(
                    f"  {len(result.local_only)} local file(s) not in the remote were kept: "
                    + ", ".join(result.local_only),
                    style="dim",
                )
            )
            self.console.print(
                Text("  Pass --prune to remove them.", style="dim")
            )
        if result.skipped:
            self.console.print(
                Text(
                    f"  {len(result.skipped)} file(s) skipped because they are not valid:",
                    style="yellow",
                )
            )
            for name, reason in result.skipped:
                self.console.print(Text(f"    {name}: {reason}", style="yellow"))

    def print_info(
        self,
        *,
        version: str,
        summary: DatabaseSummary,
        package_path: str,
        python_version: str,
        active_paths: Sequence[str] = (),
    ) -> None:
        """Print application information and the database locations."""
        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            padding=(0, 2),
            show_header=False,
        )
        table.add_column("Key", style="bold", no_wrap=True)
        table.add_column("Value")
        table.add_row("Application", f"synx {version}")
        table.add_row(
            "Purpose",
            "Command-line syntax and reference for Linux and cybersecurity tools.",
        )
        table.add_row("Mode", "Read-only reference. synx never executes commands.")
        table.add_row("Python", python_version)
        table.add_row("Package", package_path)
        table.add_row(
            "Database", f"{summary.tool_count} tool(s), {summary.command_count} command(s)"
        )
        self.console.print(table)
        if not summary.locations:
            self.blank()
            self.console.print(Text("No database directory is configured.", style="yellow"))
            return
        self.blank()
        active = {str(path) for path in active_paths}
        locations = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            padding=(0, 1),
            title="Database locations (lowest precedence first)",
            title_justify="left",
        )
        locations.add_column("#", justify="right", no_wrap=True)
        locations.add_column("Kind", style="magenta", no_wrap=True)
        locations.add_column("Path", overflow="fold")
        locations.add_column("Tools", justify="right", no_wrap=True)
        locations.add_column("Files", justify="right", no_wrap=True)
        for index, location in enumerate(summary.locations, start=1):
            in_use = str(location.path) in active
            marker = " *" if in_use else ""
            locations.add_row(
                f"{index}{marker}",
                location.kind,
                str(location.path),
                f"{location.tool_count}{marker}",
                str(location.file_count),
            )
        self.console.print(locations)
        self.blank()
        self.console.print(
            Text(
                "Drop a YAML file into any of these directories to add a tool. "
                "'*' marks the directories currently in use.",
                style="dim",
            )
        )
        if summary.issues:
            self.blank()
            self.console.print(
                Text(
                    f"{len(summary.errors)} error(s) and {len(summary.warnings)} "
                    "warning(s) occurred while loading:",
                    style="yellow",
                )
            )
            self.blank()
            self.print_issues(summary.issues)

    def print_json(self, payload: Any) -> None:
        """Print a JSON document, used by the ``--json`` flag."""
        self.console.print(
            json.dumps(payload, indent=2, ensure_ascii=False),
            soft_wrap=True,
            highlight=False,
        )

    def print_version(self, version: str) -> None:
        self.console.print(Text(f"synx {version}", style="bold cyan"))

    def rule(self) -> None:
        self.console.print(Text("─" * RULE_WIDTH, style="dim"))

    def _label(self, text: str) -> None:
        self.console.print(Padding(Text(text, style=LABEL_STYLE), (0, 0, 0, BODY_INDENT)))

    def _indented(self, renderable: Any, indent: int) -> None:
        self.console.print(Padding(renderable, (0, 0, 0, indent)))

    def _field(self, label: str, value: str) -> None:
        self.console.print(Text.assemble((f"{label}: ", LABEL_STYLE), value))
