"""Tests for the packaging metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from synx import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent

tomllib = pytest.importorskip("tomllib", reason="tomllib requires Python 3.11+")


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_console_script_maps_to_the_cli(pyproject: dict) -> None:
    assert pyproject["project"]["scripts"]["synx"] == "synx.cli:main"


def test_version_is_consistent(pyproject: dict) -> None:
    assert pyproject["project"]["version"] == __version__


def test_runtime_dependencies_are_declared(pyproject: dict) -> None:
    dependencies = " ".join(pyproject["project"]["dependencies"]).lower()
    assert "pyyaml" in dependencies
    assert "rich" in dependencies


def test_requirements_file_matches_dependencies(pyproject: dict) -> None:
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for dependency in pyproject["project"]["dependencies"]:
        name = dependency.split(">")[0].split("=")[0].split("[")[0].strip().lower()
        assert name in requirements, f"{name} is missing from requirements.txt"


def test_yaml_database_is_included_in_the_wheel(pyproject: dict) -> None:
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["tools"] == "synx/_bundled_tools"


def test_cli_entry_point_is_callable() -> None:
    from synx.cli import main

    assert callable(main)
