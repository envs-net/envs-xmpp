"""Shared coverage and mutation-regression gates for envs.net projects."""

from __future__ import annotations

import argparse
import json
import tomllib
from collections import Counter
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

_BASELINE_SCHEMA = 2
_BLOCKING_MUTATION_STATUSES = frozenset(
    {"no tests", "timeout", "suspicious", "not checked", "check was interrupted by user", "segfault"}
)

# mutmut 3.x exit-code semantics. Keep this local so consumers do not import
# mutmut internals merely to inspect an already-completed mutation run.
_STATUS_BY_EXIT_CODE: dict[int, str] = {
    0: "survived",
    1: "killed",
    3: "killed",
    5: "no tests",
    2: "check was interrupted by user",
    24: "timeout",
    34: "skipped",
    33: "no tests",
    35: "suspicious",
    36: "timeout",
    37: "caught by type check",
    -24: "timeout",
    152: "timeout",
    255: "timeout",
    -11: "segfault",
    -9: "segfault",
}


@dataclass(frozen=True)
class RegressionConfig:
    baseline: Path
    mutation_results: Path
    coverage_json: Path


@dataclass(frozen=True)
class RegressionBaseline:
    coverage_percent: float
    coverage_allowed_drop: float
    mutmut_version: str
    accepted_survivors: frozenset[str] | None


@dataclass(frozen=True)
class MutationDelta:
    counts: Counter[str]
    new_survivors: frozenset[str]
    resolved_survivors: frozenset[str]
    blockers: tuple[tuple[str, str], ...]

    @property
    def ok(self) -> bool:
        return not self.new_survivors and not self.blockers


def _tool_config(root: Path) -> dict[str, Any]:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    envs_xmpp = data.get("tool", {}).get("envs-xmpp", {})
    if not isinstance(envs_xmpp, dict):
        raise TypeError("[tool.envs-xmpp] must be a table")
    return envs_xmpp


def load_regression_config(root: Path = Path(".")) -> RegressionConfig:
    raw = _tool_config(root).get("regression")
    if not isinstance(raw, dict):
        raise TypeError("missing [tool.envs-xmpp.regression] configuration")
    return RegressionConfig(
        baseline=root / str(raw.get("baseline", "tests/regression-baseline.json")),
        mutation_results=root / str(raw.get("mutation-results", "mutants")),
        coverage_json=root / str(raw.get("coverage-json", ".coverage-regression.json")),
    )


def load_baseline(path: Path) -> RegressionBaseline:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != _BASELINE_SCHEMA:
        raise ValueError(f"unsupported regression baseline schema in {path}")
    coverage = raw.get("coverage")
    mutation = raw.get("mutation")
    if not isinstance(coverage, dict) or not isinstance(mutation, dict):
        raise TypeError(f"invalid regression baseline structure in {path}")
    mutmut_version = mutation.get("mutmut_version")
    if not isinstance(mutmut_version, str) or not mutmut_version.strip():
        raise ValueError("mutation.mutmut_version must be a non-empty string")
    survivors = mutation.get("accepted_survivors")
    if survivors is not None and not isinstance(survivors, list):
        raise ValueError("mutation.accepted_survivors must be an array or null")
    return RegressionBaseline(
        coverage_percent=float(coverage["percent"]),
        coverage_allowed_drop=float(coverage.get("allowed_drop", 0.0)),
        mutmut_version=mutmut_version.strip(),
        accepted_survivors=None if survivors is None else frozenset(str(item) for item in survivors),
    )


def _write_baseline(path: Path, baseline: RegressionBaseline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": _BASELINE_SCHEMA,
        "coverage": {
            "percent": baseline.coverage_percent,
            "allowed_drop": baseline.coverage_allowed_drop,
        },
        "mutation": {
            "mutmut_version": baseline.mutmut_version,
            "accepted_survivors": (
                None if baseline.accepted_survivors is None else sorted(baseline.accepted_survivors)
            ),
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def coverage_percent_from_json(path: Path) -> float:
    raw = json.loads(path.read_text(encoding="utf-8"))
    totals = raw.get("totals")
    if not isinstance(totals, dict) or "percent_covered" not in totals:
        raise ValueError(f"coverage JSON has no totals.percent_covered: {path}")
    return float(totals["percent_covered"])


def check_coverage(root: Path = Path(".")) -> tuple[bool, str]:
    config = load_regression_config(root)
    baseline = load_baseline(config.baseline)
    current = coverage_percent_from_json(config.coverage_json)
    minimum = baseline.coverage_percent - baseline.coverage_allowed_drop
    ok = current + 1e-9 >= minimum
    status = "passed" if ok else "FAILED"
    message = (
        f"Coverage regression gate {status}: {current:.2f}% current, "
        f"{baseline.coverage_percent:.2f}% baseline, {baseline.coverage_allowed_drop:.2f} pp allowed drop "
        f"(minimum {minimum:.2f}%)."
    )
    return ok, message


def _mutation_status(exit_code: int | None) -> str:
    if exit_code is None:
        return "not checked"
    try:
        return _STATUS_BY_EXIT_CODE[exit_code]
    except KeyError as exc:
        raise ValueError(f"unknown mutmut exit code: {exit_code}") from exc


def read_mutation_results(results_root: Path) -> dict[str, str]:
    if not results_root.is_dir():
        raise FileNotFoundError(f"mutation results directory not found: {results_root}")
    metas = sorted(results_root.rglob("*.meta"))
    if not metas:
        raise FileNotFoundError(f"no mutmut .meta result files found under {results_root}")
    results: dict[str, str] = {}
    for path in metas:
        raw = json.loads(path.read_text(encoding="utf-8"))
        exit_codes = raw.get("exit_code_by_key")
        if not isinstance(exit_codes, dict):
            raise TypeError(f"invalid mutmut metadata: {path}")
        for name, exit_code in exit_codes.items():
            if name in results:
                raise ValueError(f"duplicate mutant id {name!r}")
            if exit_code is not None and not isinstance(exit_code, int):
                raise ValueError(f"invalid mutmut exit code for {name}: {exit_code!r}")
            results[str(name)] = _mutation_status(exit_code)
    if not results:
        raise ValueError(f"mutmut metadata contains no mutants under {results_root}")
    return results



def installed_mutmut_version() -> str:
    try:
        return metadata.version("mutmut")
    except metadata.PackageNotFoundError as exc:
        raise ValueError("mutmut is not installed") from exc


def check_mutation_tool(root: Path = Path(".")) -> tuple[bool, str]:
    config = load_regression_config(root)
    baseline = load_baseline(config.baseline)
    current = installed_mutmut_version()
    ok = current == baseline.mutmut_version
    status = "passed" if ok else "FAILED"
    message = (
        f"Mutation tool gate {status}: mutmut {current} installed, "
        f"baseline requires {baseline.mutmut_version}."
    )
    return ok, message


def mutation_delta(current: dict[str, str], accepted_survivors: frozenset[str]) -> MutationDelta:
    counts: Counter[str] = Counter(current.values())
    blockers = tuple(
        sorted((name, status) for name, status in current.items() if status in _BLOCKING_MUTATION_STATUSES)
    )
    survivors = frozenset(name for name, status in current.items() if status == "survived")
    return MutationDelta(
        counts=counts,
        new_survivors=survivors - accepted_survivors,
        resolved_survivors=accepted_survivors - survivors,
        blockers=blockers,
    )


def check_mutation(root: Path = Path(".")) -> tuple[bool, str]:
    config = load_regression_config(root)
    baseline = load_baseline(config.baseline)
    tool_ok, tool_message = check_mutation_tool(root)
    if not tool_ok:
        return False, tool_message
    if baseline.accepted_survivors is None:
        return False, "Mutation regression gate FAILED: accepted survivor baseline is not initialized."
    current = read_mutation_results(config.mutation_results)
    delta = mutation_delta(current, baseline.accepted_survivors)
    counts = ", ".join(f"{key}={value}" for key, value in sorted(delta.counts.items()))
    lines = [f"Mutation results: {counts}."]
    if delta.blockers:
        lines.append("Blocking mutation results:")
        lines.extend(f"  {status}: {name}" for name, status in delta.blockers)
    if delta.new_survivors:
        lines.append("New survivors (review tests or explicitly accept after review):")
        lines.extend(f"  {name}" for name in sorted(delta.new_survivors))
    if delta.resolved_survivors:
        lines.append(f"Resolved accepted survivors: {len(delta.resolved_survivors)}")
    lines.append(f"Mutation regression gate {'passed' if delta.ok else 'FAILED'}.")
    return delta.ok, "\n".join(lines)


def accept_mutation_baseline(root: Path = Path(".")) -> str:
    config = load_regression_config(root)
    baseline = load_baseline(config.baseline)
    current = read_mutation_results(config.mutation_results)
    blocker_items = sorted((name, status) for name, status in current.items() if status in _BLOCKING_MUTATION_STATUSES)
    if blocker_items:
        details = "\n".join(f"  {status}: {name}" for name, status in blocker_items)
        raise ValueError(f"refusing to accept mutation baseline with blocking results:\n{details}")
    survivors = frozenset(name for name, status in current.items() if status == "survived")
    current_mutmut = installed_mutmut_version()
    _write_baseline(
        config.baseline,
        RegressionBaseline(
            coverage_percent=baseline.coverage_percent,
            coverage_allowed_drop=baseline.coverage_allowed_drop,
            mutmut_version=current_mutmut,
            accepted_survivors=survivors,
        ),
    )
    return f"Accepted {len(survivors)} current mutation survivors in {config.baseline}."


def accept_coverage_baseline(root: Path = Path(".")) -> str:
    config = load_regression_config(root)
    baseline = load_baseline(config.baseline)
    current = coverage_percent_from_json(config.coverage_json)
    _write_baseline(
        config.baseline,
        RegressionBaseline(
            coverage_percent=current,
            coverage_allowed_drop=baseline.coverage_allowed_drop,
            mutmut_version=baseline.mutmut_version,
            accepted_survivors=baseline.accepted_survivors,
        ),
    )
    return f"Accepted coverage baseline {current:.2f}% in {config.baseline}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "coverage-check",
            "coverage-accept",
            "mutation-tool-check",
            "mutation-check",
            "mutation-accept",
        ),
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "coverage-check":
            ok, message = check_coverage()
        elif args.command == "coverage-accept":
            print(accept_coverage_baseline())
            return 0
        elif args.command == "mutation-tool-check":
            ok, message = check_mutation_tool()
        elif args.command == "mutation-check":
            ok, message = check_mutation()
        else:
            print(accept_mutation_baseline())
            return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Regression gate FAILED: {exc}")
        return 1
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
