from __future__ import annotations

import importlib.util
import runpy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_dev_tools.py"


def _load_script() -> dict[str, object]:
    return runpy.run_path(str(SCRIPT), run_name="envs_xmpp_check_dev_tools")



def test_dev_extra_contains_quality_and_mutation_tools() -> None:
    pyproject = tomllib.loads(ROOT.joinpath("pyproject.toml").read_text())
    dev = tuple(pyproject["project"]["optional-dependencies"]["dev"])

    assert any(requirement.startswith("pytest-cov") for requirement in dev)
    assert any(requirement.startswith("mutmut") for requirement in dev)

def test_readme_development_install_includes_dev_extra() -> None:
    readme = ROOT.joinpath("README.md").read_text()
    assert 'python -m pip install -e ".[dev]"' in readme
    assert 'A plain `pip install -e .` installs only the runtime package.' in readme


def test_missing_tools_reports_distribution_names(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = _load_script()
    missing_tools = namespace["missing_tools"]

    available = {"pytest", "ruff", "mypy", "build", "twine"}
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda module: SimpleNamespace() if module in available else None,
    )

    assert missing_tools("quality") == ("pytest-cov",)
    assert missing_tools("mutation") == ("mutmut",)


def test_main_prints_actionable_install_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    namespace = _load_script()
    # Patch the function's global import lookup instead of requiring any real dev tool state.
    available = {"pytest", "ruff", "mypy", "build", "twine"}
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda module: SimpleNamespace() if module in available else None,
    )

    assert namespace["main"](["quality"]) == 1
    stderr = capsys.readouterr().err
    assert "pytest-cov" in stderr
    assert 'python -m pip install -e ".[dev]"' in stderr


def test_shell_wrappers_run_dev_tool_preflight() -> None:
    quality = ROOT.joinpath("scripts/quality.sh").read_text()
    mutmut = ROOT.joinpath("scripts/mutmut.sh").read_text()

    assert "python scripts/check_dev_tools.py quality" in quality
    assert mutmut.count("python scripts/check_dev_tools.py mutation") == 2
