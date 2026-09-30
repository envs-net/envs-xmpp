"""Regression tests for shared (previously duplicated) constraints scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from envs_xmpp_ops import constraints, constraints_update


def test_root_requirements_and_installed_dependency_closure(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("example[feature]>=1\nmissing; python_version<'3.0'\n")
    (tmp_path / "requirements-dev.txt").write_text("devlib==2\n")
    monkeypatch.chdir(tmp_path)

    seen = []

    def distribution(name):
        seen.append(name)
        if name == "example":
            return SimpleNamespace(version="1.3", requires=["optional>=1; extra == 'feature'", "pip>=1"])
        if name == "optional":
            return SimpleNamespace(version="1.2", requires=[])
        if name == "devlib":
            return SimpleNamespace(version="2", requires=[])
        raise AssertionError(name)

    monkeypatch.setattr(constraints.importlib.metadata, "distribution", distribution)
    assert constraints.dependency_closure() == {"example": "1.3", "devlib": "2", "optional": "1.2"}
    assert "pip" not in seen


def test_checker_detects_missing_and_stale_pins(tmp_path, monkeypatch):
    snap = tmp_path / "python313.txt"
    snap.write_text("example==0.9\nstale==9\n")
    monkeypatch.setattr(constraints, "dependency_closure", lambda: {"example": "1.3", "other": "4"})
    assert constraints.check_constraints(snap) == [
        "version mismatch: example installed=1.3 pinned=0.9",
        "missing transitive pin: other==4",
        "stale or unreachable pin: stale==9",
    ]


def test_update_snapshot_is_atomic_and_reuses_shared_checker(tmp_path, monkeypatch):
    (tmp_path / "constraints").mkdir()
    snapshot = tmp_path / "constraints/python313.txt"
    snapshot.write_text("old==1\n")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[-4:] == ["-m", "pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(argv, 0, stdout="pip==25\nFoo==1.0\nbar==2\n", stderr="")
        if "envs_xmpp_ops.constraints" in argv:
            assert Path(argv[-1]).read_text().splitlines()[-2:] == ["bar==2", "Foo==1.0"]
            assert "PYTHONPATH" in kwargs["env"]
            assert snapshot.read_text() == "old==1\n"
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(constraints_update.subprocess, "run", fake_run)
    assert constraints_update.update_constraints("3.13", root=tmp_path) == snapshot
    assert snapshot.read_text().endswith("bar==2\nFoo==1.0\n")
    assert len(calls) == 4
    assert "-c" in calls[1][0]


def test_failed_validation_does_not_overwrite_reviewed_snapshot(tmp_path, monkeypatch):
    (tmp_path / "constraints").mkdir()
    snapshot = tmp_path / "constraints/python313.txt"
    snapshot.write_text("old==1\n")

    def fake_run(argv, **_kwargs):
        if "envs_xmpp_ops.constraints" in argv:
            raise subprocess.CalledProcessError(1, argv)
        if argv[-4:] == ["-m", "pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(argv, 0, stdout="new==2\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(constraints_update.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        constraints_update.update_constraints("3.13", root=tmp_path)
    assert snapshot.read_text() == "old==1\n"
    assert sorted(p.name for p in (tmp_path / "constraints").iterdir()) == ["python313.txt"]


def test_update_requires_reviewed_snapshot_except_explicit_refresh(tmp_path):
    with pytest.raises(FileNotFoundError):
        constraints_update.update_constraints("3.13", root=tmp_path)


def test_update_cli_rejects_invalid_python_version():
    with pytest.raises(SystemExit) as exc:
        constraints_update.main(["3.15"])
    assert exc.value.code == 2
