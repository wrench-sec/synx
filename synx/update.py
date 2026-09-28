"""Refresh the tool database from a git repository.

The database synx reads is a directory of YAML files, so an update is just a
matter of fetching a remote copy of that directory and reconciling it with the
per-user one. This module does that with plain ``git`` calls, which keeps the
project free of an HTTP client dependency and reuses the user's existing git
configuration, credentials and proxy settings.

Every fetched file is validated with the same loader the database itself uses
before it is written, so a broken or malicious definition in the remote can
never replace a good local file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from synx.database import user_database_directory
from synx.models import SynxError, Tool, ToolValidationError

__all__ = [
    "DEFAULT_UPDATE_REPO",
    "TOOLS_SUBDIRECTORY",
    "UPDATE_REPO_ENV_VAR",
    "GitRunner",
    "UpdateError",
    "UpdateResult",
    "resolve_update_repo",
    "update_database",
]

DEFAULT_UPDATE_REPO = "https://github.com/wrench-sec/synx.git"
UPDATE_REPO_ENV_VAR = "SYNX_UPDATE_REPO"
TOOLS_SUBDIRECTORY = "tools"

GitRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class UpdateError(SynxError):
    """Raised when the database could not be refreshed from a remote."""


@dataclass(frozen=True)
class UpdateResult:
    """The outcome of a database refresh."""

    repo: str
    target: Path
    added: tuple[str, ...] = field(default_factory=tuple)
    updated: tuple[str, ...] = field(default_factory=tuple)
    unchanged: tuple[str, ...] = field(default_factory=tuple)
    local_only: tuple[str, ...] = field(default_factory=tuple)
    removed: tuple[str, ...] = field(default_factory=tuple)
    skipped: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    tools: int = 0

    @property
    def changed(self) -> int:
        """Number of files written, added or removed."""
        return len(self.added) + len(self.updated) + len(self.removed)

    def to_dict(self) -> dict[str, object]:
        return {
            "repo": self.repo,
            "target": str(self.target),
            "added": list(self.added),
            "updated": list(self.updated),
            "unchanged": list(self.unchanged),
            "local_only": list(self.local_only),
            "removed": list(self.removed),
            "skipped": [{"file": name, "reason": reason} for name, reason in self.skipped],
            "tools": self.tools,
            "changed": self.changed,
        }


def resolve_update_repo(
    repo: str | None = None, *, env: Mapping[str, str] | None = None
) -> str:
    """Return the repository to update from.

    An explicit ``repo`` wins, then the ``SYNX_UPDATE_REPO`` environment
    variable, then the bundled default. A blank value from any source falls
    through to the next one so that ``SYNX_UPDATE_REPO=`` cannot break the flag.
    """
    environ = os.environ if env is None else env
    for candidate in (repo, environ.get(UPDATE_REPO_ENV_VAR, "")):
        if candidate and candidate.strip():
            return candidate.strip()
    return DEFAULT_UPDATE_REPO


def _default_runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run git and return the completed process."""
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


def _checkout(repo: str, runner: GitRunner) -> Path:
    """Clone the remote shallowly into a temporary directory and return it."""
    workspace = Path(tempfile.mkdtemp(prefix="synx-update-"))
    try:
        completed = runner(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--quiet",
                "--no-tags",
                repo,
                str(workspace / "repo"),
            ]
        )
    except FileNotFoundError:
        shutil.rmtree(workspace, ignore_errors=True)
        raise UpdateError(
            "git was not found on this system, so the database cannot be updated."
        ) from None
    except OSError as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        raise UpdateError(f"Could not fetch '{repo}': {exc}") from exc
    if completed.returncode != 0:
        shutil.rmtree(workspace, ignore_errors=True)
        detail = (completed.stderr or completed.stdout or "").strip()
        raise UpdateError(f"Could not fetch '{repo}': {detail or 'git failed'}")
    return workspace


def _read_tool(path: Path) -> Tool:
    """Parse and validate one YAML definition, raising on any problem."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Tool.from_mapping(data, source=path.name)


def _write_atomically(path: Path, text: str) -> None:
    """Write text to path so a failure cannot leave a half-written definition."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def update_database(
    repo: str | None = None,
    *,
    target: Path | None = None,
    env: Mapping[str, str] | None = None,
    prune: bool = False,
    runner: GitRunner | None = None,
) -> UpdateResult:
    """Fetch the remote tool definitions and reconcile them with ``target``.

    Files are validated before they are written, so a definition that fails the
    schema is reported as skipped and the local file is left untouched. Local
    files that the remote does not ship are only deleted when ``prune`` is set,
    because they are usually hand-written additions.
    """
    source = resolve_update_repo(repo, env=env)
    destination = (
        user_database_directory(env) if target is None else Path(target)
    )
    run = _default_runner if runner is None else runner

    workspace = _checkout(source, run)
    try:
        remote_dir = workspace / "repo" / TOOLS_SUBDIRECTORY
        if not remote_dir.is_dir():
            raise UpdateError(
                f"'{source}' has no '{TOOLS_SUBDIRECTORY}/' directory, "
                "so it is not a synx tool database."
            )
        return _reconcile(remote_dir, destination, source, prune=prune)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _reconcile(
    remote_dir: Path, destination: Path, repo: str, *, prune: bool
) -> UpdateResult:
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    skipped: list[tuple[str, str]] = []

    destination.mkdir(parents=True, exist_ok=True)

    for remote_path in sorted(remote_dir.glob("*.yaml")):
        try:
            tool = _read_tool(remote_path)
        except (ToolValidationError, yaml.YAMLError, OSError) as exc:
            reason = str(exc) or exc.__class__.__name__
            skipped.append((remote_path.name, reason))
            continue

        text = remote_path.read_text(encoding="utf-8")
        local_path = destination / remote_path.name
        if not local_path.exists():
            added.append(tool.name)
        elif local_path.read_text(encoding="utf-8") == text:
            unchanged.append(tool.name)
        else:
            updated.append(tool.name)
        _write_atomically(local_path, text)

    remote_names = {path.name for path in remote_dir.glob("*.yaml")}
    local_only: list[str] = []
    removed: list[str] = []
    for local_path in sorted(destination.glob("*.yaml")):
        if local_path.name in remote_names:
            continue
        local_only.append(local_path.stem)
        if prune:
            local_path.unlink()
            removed.append(local_path.stem)

    return UpdateResult(
        repo=repo,
        target=destination,
        added=tuple(added),
        updated=tuple(updated),
        unchanged=tuple(unchanged),
        local_only=tuple(local_only),
        removed=tuple(removed),
        skipped=tuple(skipped),
        tools=len(remote_names) - len(skipped),
    )
