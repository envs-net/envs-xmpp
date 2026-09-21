import json
from pathlib import Path

import pytest

from envs_xmpp_ops.regression import (
    accept_mutation_baseline,
    check_coverage,
    check_mutation,
    mutation_delta,
    read_mutation_results,
)


def _project(tmp_path: Path, *, survivors=None, percent=90.0, allowed_drop=0.5) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.envs-xmpp.regression]\n"
        'baseline = "tests/regression-baseline.json"\n'
        'mutation-results = "mutants"\n'
        'coverage-json = ".coverage-regression.json"\n',
        encoding="utf-8",
    )
    baseline = {
        "schema": 1,
        "coverage": {"percent": percent, "allowed_drop": allowed_drop},
        "mutation": {"accepted_survivors": survivors},
    }
    path = tmp_path / "tests" / "regression-baseline.json"
    path.parent.mkdir()
    path.write_text(json.dumps(baseline), encoding="utf-8")
    return tmp_path


def _coverage(root: Path, percent: float) -> None:
    (root / ".coverage-regression.json").write_text(
        json.dumps({"totals": {"percent_covered": percent}}), encoding="utf-8"
    )


def _mutations(root: Path, values: dict[str, int | None]) -> None:
    path = root / "mutants" / "pkg.py.meta"
    path.parent.mkdir()
    path.write_text(json.dumps({"exit_code_by_key": values}), encoding="utf-8")


def test_coverage_delta_allows_configured_drop(tmp_path):
    root = _project(tmp_path, survivors=[], percent=90.0, allowed_drop=0.5)
    _coverage(root, 89.5)
    ok, message = check_coverage(root)
    assert ok is True
    assert "minimum 89.50%" in message


def test_coverage_delta_rejects_larger_regression(tmp_path):
    root = _project(tmp_path, survivors=[], percent=90.0, allowed_drop=0.5)
    _coverage(root, 89.49)
    ok, message = check_coverage(root)
    assert ok is False
    assert "FAILED" in message


def test_mutation_delta_accepts_known_and_reports_resolved_survivors():
    delta = mutation_delta(
        {"same": "survived", "killed": "killed"},
        frozenset({"same", "resolved"}),
    )
    assert delta.ok is True
    assert delta.new_survivors == frozenset()
    assert delta.resolved_survivors == frozenset({"resolved"})


def test_mutation_delta_rejects_new_survivor():
    delta = mutation_delta({"new": "survived"}, frozenset())
    assert delta.ok is False
    assert delta.new_survivors == frozenset({"new"})


@pytest.mark.parametrize("exit_code", [2, 5, 33, 35, 36, -24, 24, 152, 255, -11, -9, None])
def test_mutation_gate_rejects_blocking_statuses(tmp_path, exit_code):
    root = _project(tmp_path, survivors=[])
    _mutations(root, {"pkg.x__mutmut_1": exit_code})
    ok, message = check_mutation(root)
    assert ok is False
    assert "Blocking mutation results" in message


def test_mutation_gate_requires_initialized_baseline(tmp_path):
    root = _project(tmp_path, survivors=None)
    _mutations(root, {"pkg.x__mutmut_1": 1})
    ok, message = check_mutation(root)
    assert ok is False
    assert "not initialized" in message


def test_read_mutation_results_rejects_unknown_exit_code(tmp_path):
    root = _project(tmp_path, survivors=[])
    _mutations(root, {"pkg.x__mutmut_1": 999})
    with pytest.raises(ValueError, match="unknown mutmut exit code"):
        read_mutation_results(root / "mutants")


def test_accept_mutation_baseline_records_only_survivors(tmp_path):
    root = _project(tmp_path, survivors=None)
    _mutations(root, {"survivor": 0, "killed": 1, "skipped": 34, "typed": 37})
    message = accept_mutation_baseline(root)
    assert "Accepted 1" in message
    baseline = json.loads((root / "tests" / "regression-baseline.json").read_text(encoding="utf-8"))
    assert baseline["mutation"]["accepted_survivors"] == ["survivor"]


def test_accept_mutation_baseline_refuses_blockers(tmp_path):
    root = _project(tmp_path, survivors=None)
    _mutations(root, {"bad": 33})
    with pytest.raises(ValueError, match="refusing to accept"):
        accept_mutation_baseline(root)
