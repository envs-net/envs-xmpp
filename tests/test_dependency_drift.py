from __future__ import annotations

import json
import subprocess
from pathlib import Path

from envs_xmpp_ops.dependency_drift import (
    exact_constraint_pins,
    inspect_dependency_drift,
    normalize_package_name,
    project_runtime_dependencies,
)


def _project(root: Path) -> Path:
    (root / "constraints").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="1"\n'
        'dependencies=["EnvS_XMPP>=1", "slixmpp<2", "aiosqlite>=0.20"]\n',
        encoding="utf-8",
    )
    constraints = root / "constraints" / "python313.txt"
    constraints.write_text(
        "envs-xmpp==1.1.0\nslixmpp==1.17.0\naiosqlite==0.22.1\n",
        encoding="utf-8",
    )
    return constraints


def test_dependency_names_and_constraint_pins_are_normalized(tmp_path):
    constraints = _project(tmp_path)
    assert project_runtime_dependencies(tmp_path) == (
        "aiosqlite",
        "envs-xmpp",
        "slixmpp",
    )
    assert exact_constraint_pins(constraints)["envs-xmpp"] == "1.1.0"
    assert normalize_package_name("EnvS_XMPP") == "envs-xmpp"


def test_dependency_drift_reports_clean_runtime(tmp_path):
    constraints = _project(tmp_path)

    def run(_argv, **_kwargs):
        return subprocess.CompletedProcess(
            ["python"],
            0,
            json.dumps(
                {
                    "aiosqlite": "0.22.1",
                    "envs-xmpp": "1.1.0",
                    "slixmpp": "1.17.0",
                }
            ),
            "",
        )

    report = inspect_dependency_drift(tmp_path, Path("/venv/python"), constraints, run_process=run)
    assert report.ok is True
    assert report.mismatches == ()
    assert report.summary().startswith("clean")


def test_dependency_drift_reports_missing_mismatched_and_unpinned(tmp_path):
    constraints = _project(tmp_path)
    constraints.write_text("envs-xmpp==1.1.0\nslixmpp==1.17.0\n", encoding="utf-8")

    def run(_argv, **_kwargs):
        return subprocess.CompletedProcess(
            ["python"],
            0,
            json.dumps(
                {
                    "aiosqlite": "0.22.1",
                    "envs-xmpp": "1.0.0",
                    "slixmpp": None,
                }
            ),
            "",
        )

    report = inspect_dependency_drift(tmp_path, Path("/venv/python"), constraints, run_process=run)
    assert report.ok is False
    assert report.details() == (
        "aiosqlite: no exact pin in python313.txt",
        "envs-xmpp: installed 1.0.0, expected 1.1.0",
        "slixmpp: missing (expected 1.17.0)",
    )
