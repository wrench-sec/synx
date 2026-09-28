"""Command-line interface for synx.

The CLI is a thin orchestration layer: it resolves the database, delegates
matching to :mod:`synx.search` and rendering to :mod:`synx.display`. It never
executes anything.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from synx import __version__
from synx.database import DATABASE_ENV_VAR, CommandDatabase, resolve_database_paths
from synx.display import Renderer
from synx.models import Command, DatabaseError, Tool
from synx.search import search as search_database
from synx.search import suggest

__all__ = ["build_parser", "main"]

EXIT_SUCCESS = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2
EXIT_DATABASE_ERROR = 3

PROGRAM_NAME = "synx"
_SEARCH_FLAG = object()

DESCRIPTION = """\
synx is a syntax and reference tool for Linux and cybersecurity utilities.

It reads a local YAML database of tools and displays their common commands,
syntax and descriptions. It never executes the commands it documents.
"""

EPILOG = """\
examples:
  synx                     show this help
  synx --list              list every tool in the database
  synx --info              show application and database information
  synx nxc                 show all documented commands for nxc
  synx nxc smb             show a single command of a tool
  synx --search kerberos   search tools, syntax and descriptions
  synx nxc --search ldap   search inside a single tool

exit codes:
  0  success
  1  tool, command or search term not found
  2  invalid usage
  3  the database could not be loaded
"""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``synx`` command."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "tool",
        nargs="?",
        help="tool to display, for example: nxc, certipy, impacket",
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="optional single command of the tool, for example: smb",
    )
    parser.add_argument(
        "-s",
        "--search",
        nargs="?",
        const=_SEARCH_FLAG,
        metavar="KEYWORD",
        help="search the database for KEYWORD; combine with a tool to search only it",
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="list every available tool"
    )
    parser.add_argument(
        "-i", "--info", action="store_true", help="show application and database information"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="re-read the database from disk and report what was loaded",
    )
    parser.add_argument(
        "--db-path",
        action="append",
        metavar="DIR",
        help=(
            "directory of YAML tool files to load instead of the defaults; "
            f"may be repeated, or set {DATABASE_ENV_VAR}"
        ),
    )
    parser.add_argument(
        "--context",
        type=_positive_int,
        default=3,
        metavar="N",
        help="commands to show under a matched tool during search (default: 3)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON instead of tables"
    )
    parser.add_argument(
        "--no-color", action="store_true", help="disable ANSI colours and styling"
    )
    parser.add_argument(
        "--width", type=_positive_int, metavar="N", help="force the output width in columns"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="report skipped or duplicate database files",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{PROGRAM_NAME} {__version__}",
        help="show the synx version and exit",
    )
    return parser


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not an integer") from None
    if number < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``synx`` command-line interface and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(parser, args)
    except BrokenPipeError:  # pragma: no cover - depends on the consumer
        _silence_broken_pipe()
        return EXIT_SUCCESS


def _silence_broken_pipe() -> None:  # pragma: no cover - depends on the consumer
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())


def _dispatch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    renderer = Renderer(no_color=args.no_color, width=args.width)
    paths = resolve_database_paths(args.db_path)
    database = CommandDatabase(paths)
    try:
        database.load()
    except DatabaseError as exc:
        renderer.print_error(
            f"Could not load the command database: {exc}",
            hint=(
                f"Point synx at a directory of YAML files with --db-path DIR or "
                f"{DATABASE_ENV_VAR}=DIR."
            ),
        )
        return EXIT_DATABASE_ERROR

    if args.verbose:
        renderer.print_issues(database.issues)

    if args.info or args.reload:
        return _show_info(renderer, database, args)

    if args.search is not None:
        return _run_search(parser, renderer, database, args)

    if args.list:
        return _show_list(renderer, database, args)

    if args.tool is None:
        if args.command is not None:  # pragma: no cover - argparse allows this
            parser.error("a command requires a tool, for example: synx nxc smb")
        parser.print_help()
        return EXIT_SUCCESS

    return _show_tool(parser, renderer, database, args)


def _show_info(renderer: Renderer, database: CommandDatabase, args: argparse.Namespace) -> int:
    summary = database.summary()
    if args.json:
        renderer.print_json(
            {
                "version": __version__,
                "python": platform.python_version(),
                "package_path": str(Path(__file__).resolve().parent),
                "database": summary.to_dict(),
            }
        )
        return EXIT_SUCCESS
    renderer.print_info(
        version=__version__,
        summary=summary,
        package_path=str(Path(__file__).resolve().parent),
        python_version=platform.python_version(),
        active_paths=[str(path) for path in database.paths],
    )
    return EXIT_SUCCESS


def _show_list(renderer: Renderer, database: CommandDatabase, args: argparse.Namespace) -> int:
    tools = database.tools
    if args.json:
        renderer.print_json(database.to_dict())
        return EXIT_SUCCESS
    renderer.print_tool_list(tools, issues=database.issues)
    return EXIT_SUCCESS


def _run_search(
    parser: argparse.ArgumentParser,
    renderer: Renderer,
    database: CommandDatabase,
    args: argparse.Namespace,
) -> int:
    scoped = isinstance(args.search, str)
    keyword = args.search if scoped else args.tool
    if not keyword or not isinstance(keyword, str):
        parser.error("--search requires a keyword, for example: synx --search kerberos")
    if args.command is not None and scoped:
        parser.error("a command cannot be combined with '--search KEYWORD'")

    tools: Sequence[Tool] = database.tools
    scope_note = None
    if scoped and args.tool:
        tool = _resolve_tool(renderer, database, args.tool)
        if tool is None:
            return EXIT_NOT_FOUND
        tools = (tool,)
        scope_note = tool.name

    hits = search_database(keyword, tools)
    if args.json:
        renderer.print_json(
            {
                "keyword": keyword,
                "scope": scope_note,
                "match_count": len(hits),
                "results": [hit.to_dict() for hit in hits],
            }
        )
        return EXIT_SUCCESS if hits else EXIT_NOT_FOUND

    if not hits:
        renderer.print_suggestions(
            f"Search term '{keyword}' was not found.",
            suggest(keyword, database.candidate_names(), limit=3),
            fallback="No tool, command or description matches this keyword.",
            hint=(
                "Run 'synx --list' to see every tool, or 'synx --search <keyword>' "
                "to try a different term."
            ),
        )
        return EXIT_NOT_FOUND

    if scope_note:
        renderer.print_note(f"Searching only in '{scope_note}'.")
        renderer.blank()
    renderer.print_search_results(keyword, hits, context=args.context)
    return EXIT_SUCCESS


def _show_tool(
    parser: argparse.ArgumentParser,
    renderer: Renderer,
    database: CommandDatabase,
    args: argparse.Namespace,
) -> int:
    if args.search is not None:
        parser.error("--search is a database-wide option; run 'synx --search <keyword>'")
    tool = _resolve_tool(renderer, database, args.tool)
    if tool is None:
        return EXIT_NOT_FOUND
    if args.command is None:
        if args.json:
            renderer.print_json(tool.to_dict())
        else:
            renderer.print_tool(tool, show_source=args.verbose)
        return EXIT_SUCCESS
    command = _resolve_command(renderer, tool, args.command)
    if command is None:
        return EXIT_NOT_FOUND
    if args.json:
        renderer.print_json(
            {"tool": tool.name, "command": command.to_dict()}
        )
    else:
        renderer.print_command_page(tool, command)
    return EXIT_SUCCESS


def _resolve_tool(renderer: Renderer, database: CommandDatabase, query: str) -> Tool | None:
    tool = database.find(query)
    if tool is not None:
        return tool
    renderer.print_suggestions(
        f"Tool '{query}' was not found.",
        suggest(query, database.candidate_names(), limit=3),
        hint=(
            f"Run 'synx --list' to see every tool, or 'synx --search {query}' "
            "to search the database."
        ),
    )
    return None


def _resolve_command(renderer: Renderer, tool: Tool, query: str) -> Command | None:
    command = tool.get_command(query)
    if command is not None:
        return command
    renderer.print_suggestions(
        f"Command '{query}' was not found in tool '{tool.name}'.",
        suggest(query, [item.name for item in tool.commands], limit=3),
        hint=(
            f"Run 'synx {tool.name}' to list the {tool.command_count} documented "
            f"command(s), or 'synx --search {query}' to search the database."
        ),
    )
    return None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
