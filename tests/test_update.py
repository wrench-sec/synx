"""Tests for refreshing the tool database from a git remote.

The happy paths run against a real git repository created in a temporary
directory, because ``git`` accepts a local path as a remote. That exercises the
actual subprocess calls, so these tests do not depend on the network.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from synx.cli import main
from synx.display import Renderer
from synx.update import (
    DEFAULT_UPDATE_REPO,
    UPDATE_REPO_ENV_VAR,
    UpdateError,
    resolve_update_repo,
    update_database,
)
from tests.conftest import TEST_WIDTH, make_console
from tests.data import CERTIPY_YAML, NXC_YAML, write_yaml

BROKEN_YAML = "name: broken\ncategory: nope\n"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def make_remote(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """Create a git repository containing a ``tools/`` directory."""
    remote = tmp_path / "remote"
    remote.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=remote)
    _git("config", "user.email", "test@example.com", cwd=remote)
    _git("config", "user.name", "Test", cwd=remote)
    definitions = {"nxc.yaml": NXC_YAML, "certipy.yaml": CERTIPY_YAML}
    definitions.update(files or {})
    for filename, content in definitions.items():
        write_yaml(remote / "tools", filename, content)
    _git("add", ".", cwd=remote)
    _git("commit", "--quiet", "-m", "tools", cwd=remote)
    return remote


def commit_all(repo: Path, message: str) -> None:
    _git("add", ".", cwd=repo)
    _git("commit", "--quiet", "-m", message, cwd=repo)


def test_update_writes_definitions_to_the_target(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "user-tools"

    result = update_database(str(remote), target=target)

    assert sorted(result.added) == ["certipy", "nxc"]
    assert result.updated == ()
    assert result.target == target
    assert sorted(path.name for path in target.glob("*.yaml")) == [
        "certipy.yaml",
        "nxc.yaml",
    ]
    assert result.tools == 2


def test_second_update_reports_everything_unchanged(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "user-tools"
    update_database(str(remote), target=target)

    result = update_database(str(remote), target=target)

    assert result.added == ()
    assert result.updated == ()
    assert sorted(result.unchanged) == ["certipy", "nxc"]


def test_changed_definition_is_reported_as_updated(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "user-tools"
    update_database(str(remote), target=target)

    write_yaml(remote / "tools", "nxc.yaml", NXC_YAML.replace("netexec", "nxchanged"))
    commit_all(remote, "change nxc")
    result = update_database(str(remote), target=target)

    assert result.updated == ("nxc",)
    assert result.unchanged == ("certipy",)
    assert "nxchanged" in (target / "nxc.yaml").read_text(encoding="utf-8")


def test_invalid_definition_is_skipped_and_local_file_survives(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "user-tools"
    update_database(str(remote), target=target)
    good = (target / "certipy.yaml").read_text(encoding="utf-8")

    write_yaml(remote / "tools", "broken.yaml", BROKEN_YAML)
    commit_all(remote, "add broken")
    result = update_database(str(remote), target=target)

    assert tuple(name for name, _ in result.skipped) == ("broken.yaml",)
    assert not (target / "broken.yaml").exists()
    assert (target / "certipy.yaml").read_text(encoding="utf-8") == good


def test_existing_file_is_kept_when_remote_copy_is_invalid(tmp_path: Path) -> None:
    """A bad remote definition must not overwrite a good local one."""
    remote = make_remote(tmp_path, {"broken.yaml": BROKEN_YAML})
    target = tmp_path / "user-tools"
    write_yaml(target, "broken.yaml", NXC_YAML)

    result = update_database(str(remote), target=target)

    assert (target / "broken.yaml").read_text(encoding="utf-8") == NXC_YAML
    assert result.skipped[0][0] == "broken.yaml"


def test_local_only_files_are_kept_by_default(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "user-tools"
    write_yaml(target, "mine.yaml", CERTIPY_YAML)

    result = update_database(str(remote), target=target)

    assert result.local_only == ("mine",)
    assert result.removed == ()
    assert (target / "mine.yaml").exists()


def test_prune_removes_local_only_files(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "user-tools"
    write_yaml(target, "mine.yaml", CERTIPY_YAML)

    result = update_database(str(remote), target=target, prune=True)

    assert result.removed == ("mine",)
    assert not (target / "mine.yaml").exists()
    assert result.changed == 3


def test_update_creates_the_target_directory(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    target = tmp_path / "deeply" / "nested" / "tools"

    update_database(str(remote), target=target)

    assert target.is_dir()


def test_missing_remote_reports_the_git_error(tmp_path: Path) -> None:
    with pytest.raises(UpdateError) as excinfo:
        update_database(str(tmp_path / "does-not-exist"), target=tmp_path / "out")

    assert "Could not fetch" in str(excinfo.value)


def test_remote_without_tools_directory_is_rejected(tmp_path: Path) -> None:
    remote = tmp_path / "empty-remote"
    remote.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=remote)
    _git("config", "user.email", "test@example.com", cwd=remote)
    _git("config", "user.name", "Test", cwd=remote)
    (remote / "README.md").write_text("no tools here", encoding="utf-8")
    commit_all(remote, "initial")

    with pytest.raises(UpdateError) as excinfo:
        update_database(str(remote), target=tmp_path / "out")

    assert "not a synx tool database" in str(excinfo.value)


def test_missing_git_is_reported_clearly(tmp_path: Path) -> None:
    def missing_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with pytest.raises(UpdateError) as excinfo:
        update_database(
            str(tmp_path), target=tmp_path / "out", runner=missing_git  # type: ignore[arg-type]
        )

    assert "git was not found" in str(excinfo.value)


def test_temporary_checkout_is_cleaned_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful update must not leave its scratch clone behind."""
    remote = make_remote(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    update_database(str(remote), target=tmp_path / "out")

    assert list(scratch.iterdir()) == []


def test_temporary_checkout_is_cleaned_up_after_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed clone must clean up too, rather than leaking the directory."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    with pytest.raises(UpdateError):
        update_database(str(tmp_path / "missing"), target=tmp_path / "out")

    assert list(scratch.iterdir()) == []


def test_update_only_ever_spawns_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """update.py may shell out, but only to git and never through a shell.

    This is the guarantee that lets tests/test_safety.py permit subprocess in
    this one file. The repository string is passed as its own argv element, so
    it cannot be interpreted as shell syntax, and no call uses a shell.
    """
    remote = make_remote(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    real_run = subprocess.run

    def record(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return real_run(args, capture_output=True, text=True, check=True)

    monkeypatch.setattr("synx.update.subprocess.run", record)
    update_database(str(remote), target=tmp_path / "out")

    assert calls, "git was never invoked"
    for args, kwargs in calls:
        assert args[0] == "git", f"unexpected program: {args[0]}"
        assert kwargs.get("shell") in (None, False), "must not use a shell"
        assert str(remote) in args, "the repository must be a separate argv element"


def test_update_does_not_execute_database_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A definition in the database must never reach the command line."""
    remote = make_remote(tmp_path)
    marker = "$(touch /tmp/synx-pwned); rm -rf /"
    write_yaml(
        remote / "tools",
        "evil.yaml",
        NXC_YAML.replace("netexec", marker),
    )
    commit_all(remote, "hostile definition")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    seen: list[list[str]] = []

    real_run = subprocess.run

    def record(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return real_run(args, capture_output=True, text=True, check=True)

    monkeypatch.setattr("synx.update.subprocess.run", record)
    update_database(str(remote))

    for args in seen:
        assert all(marker not in element for element in args)


@pytest.mark.parametrize(
    ("repo", "env", "expected"),
    [
        ("https://example.com/a.git", {}, "https://example.com/a.git"),
        (None, {UPDATE_REPO_ENV_VAR: "https://example.com/b.git"}, "https://example.com/b.git"),
        (None, {}, DEFAULT_UPDATE_REPO),
        (None, {UPDATE_REPO_ENV_VAR: "   "}, DEFAULT_UPDATE_REPO),
        ("  https://example.com/c.git  ", {}, "https://example.com/c.git"),
    ],
)
def test_resolve_update_repo_precedence(
    repo: str | None, env: dict[str, str], expected: str
) -> None:
    assert resolve_update_repo(repo, env=env) == expected


def test_update_target_defaults_to_the_user_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    remote = make_remote(tmp_path)

    result = update_database(str(remote))

    assert result.target == tmp_path / "xdg" / "synx" / "tools"
    assert (result.target / "nxc.yaml").exists()


def test_cli_update_reports_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, buffer
) -> None:
    remote = make_remote(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        "synx.cli.Renderer", lambda **kwargs: Renderer(console=make_console(buffer), **kwargs)
    )

    code = main(["--update", str(remote), "--width", str(TEST_WIDTH)])
    output = buffer.getvalue()

    assert code == 0
    assert "nxc" in output
    assert "added" in output


def test_cli_update_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, buffer
) -> None:
    import json

    remote = make_remote(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        "synx.cli.Renderer", lambda **kwargs: Renderer(console=make_console(buffer), **kwargs)
    )

    code = main(["--update", str(remote), "--json", "--width", str(TEST_WIDTH)])
    payload = json.loads(buffer.getvalue())

    assert code == 0
    assert sorted(payload["added"]) == ["certipy", "nxc"]
    assert payload["tools"] == 2


def test_cli_update_failure_exits_with_the_database_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, buffer
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        "synx.cli.Renderer", lambda **kwargs: Renderer(console=make_console(buffer), **kwargs)
    )

    code = main(
        ["--update", str(tmp_path / "nope"), "--width", str(TEST_WIDTH)]
    )

    assert code == 3
    assert "Could not fetch" in buffer.getvalue()


def test_prune_without_update_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, buffer
) -> None:
    monkeypatch.setattr(
        "synx.cli.Renderer", lambda **kwargs: Renderer(console=make_console(buffer), **kwargs)
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--prune", "--width", str(TEST_WIDTH)])

    assert excinfo.value.code == 2


@pytest.mark.parametrize("conflict", [["--list"], ["--info"], ["--search", "kerb"]])
def test_update_cannot_be_combined_with_other_actions(
    conflict: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, buffer
) -> None:
    remote = make_remote(tmp_path)
    monkeypatch.setattr(
        "synx.cli.Renderer", lambda **kwargs: Renderer(console=make_console(buffer), **kwargs)
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--update", str(remote), *conflict, "--width", str(TEST_WIDTH)])

    assert excinfo.value.code == 2
