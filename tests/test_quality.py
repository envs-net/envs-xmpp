from __future__ import annotations

from pathlib import Path

from envs_xmpp_ops.quality import load_quality_config
from envs_xmpp_ops.testing import PytestConfig, load_test_config, pytest_command


def _write_project(path: Path) -> None:
    path.joinpath("pyproject.toml").write_text(
        """
[project]
name = "example"
version = "1"

[tool.envs-xmpp.quality]
compile-targets = ["app.py", "pkg"]
ruff-targets = ["app.py", "pkg"]
mypy-targets = ["app.py", "pkg"]
mypy-args = ["--follow-imports=skip"]
constraints-dir = "locks"

[[tool.envs-xmpp.quality.project-checks]]
name = "Generated config"
command = ["python", "scripts/check_config.py"]

[tool.envs-xmpp.testing]
marker = "not integration"
coverage-source = "pkg"
coverage-report = "term-missing"
coverage-fail-under = 61
""".strip()
        + "\n"
    )


def test_load_quality_config(tmp_path: Path) -> None:
    _write_project(tmp_path)
    config = load_quality_config(tmp_path)

    assert config.compile_targets == ("app.py", "pkg")
    assert config.ruff_targets == ("app.py", "pkg")
    assert config.mypy_targets == ("app.py", "pkg")
    assert config.mypy_args == ("--follow-imports=skip",)
    assert config.constraints_dir == "locks"
    assert len(config.project_checks) == 1
    assert config.project_checks[0].name == "Generated config"


def test_load_test_config(tmp_path: Path) -> None:
    _write_project(tmp_path)
    config = load_test_config(tmp_path)

    assert config.marker == "not integration"
    assert config.coverage_source == "pkg"
    assert config.coverage_report == "term-missing"
    assert config.coverage_fail_under == 61


def test_pytest_command_default_warning_policy() -> None:
    config = PytestConfig(
        marker=None,
        coverage_source=".",
        coverage_report="term",
        coverage_fail_under=85,
    )
    command = pytest_command(
        config,
        coverage=False,
        last_failed=False,
        durations=None,
        targets=["tests/test_one.py"],
    )

    assert "error::RuntimeWarning" in command
    assert "error::DeprecationWarning" in command
    assert "--cov=." not in command
    assert command[-1] == "tests/test_one.py"


def test_pytest_command_project_policy() -> None:
    config = PytestConfig(
        marker="not integration",
        coverage_source="banbot",
        coverage_report="term-missing",
        coverage_fail_under=55,
    )
    command = pytest_command(
        config,
        coverage=True,
        last_failed=True,
        durations=10,
        targets=[],
    )

    marker_index = len(command) - 1 - command[::-1].index("-m")
    assert command[marker_index + 1] == "not integration"
    assert "--lf" in command
    assert "--durations=10" in command
    assert "--cov=banbot" in command
    assert "--cov-report=term-missing" in command
    assert "--cov-fail-under=55" in command

def test_run_quality_uses_common_gate_order(tmp_path: Path, monkeypatch, capsys) -> None:
    from envs_xmpp_ops import quality as quality_module

    tmp_path.joinpath("constraints").mkdir()
    minor = f"{__import__('sys').version_info.major}{__import__('sys').version_info.minor}"
    tmp_path.joinpath("constraints", f"python{minor}.txt").write_text("example==1\n")

    config = quality_module.QualityConfig(
        compile_targets=("app.py",),
        project_checks=(
            quality_module.ProjectCheck(
                name="Generated config",
                command=("python", "scripts/check.py"),
            ),
        ),
        ruff_targets=("app.py",),
        mypy_targets=("app.py",),
        mypy_args=(),
    )
    monkeypatch.setattr(quality_module, "load_quality_config", lambda root: config)

    commands: list[list[str]] = []
    monkeypatch.setattr(
        quality_module,
        "_run",
        lambda command, *, root: commands.append(command),
    )
    monkeypatch.setattr(quality_module, "_git_whitespace_check", lambda root: None)

    quality_module.run_quality(root=tmp_path, fix=True, skip_tests=False)

    output = capsys.readouterr().out
    assert "[1/9] Python compilation" in output
    assert "[2/9] Project validation" in output
    assert "[3/9] Test suite (warning strict)" in output
    assert "[4/9] Ruff: repository checks" in output
    assert "[5/9] Ruff: unused imports (F401)" in output
    assert "[6/9] Ruff: imports, modernization, and Bugbear (I,UP,B)" in output
    assert "[7/9] mypy: configured production source tree" in output
    assert "[8/9] Git whitespace errors" in output
    assert "[9/9] Dependency audit (pip-audit)" in output
    assert "Quality checks passed (9/9)." in output

    joined = [" ".join(command) for command in commands]
    assert any("-m envs_xmpp_ops.testing" in command for command in joined)
    assert sum("--fix" in command for command in joined) == 3
    assert any("-m pip_audit -r" in command for command in joined)


def test_quality_and_test_shell_contract_can_be_identical() -> None:
    """The bot repositories only need tiny wrappers around these shared modules."""
    assert callable(load_quality_config)
    assert callable(load_test_config)

def test_pytest_command_preserves_arbitrary_pytest_arguments() -> None:
    config = PytestConfig(
        marker=None,
        coverage_source=".",
        coverage_report="term",
        coverage_fail_under=85,
    )
    command = pytest_command(
        config,
        coverage=False,
        last_failed=False,
        durations=None,
        targets=["tests/test_one.py", "-k", "example"],
    )

    assert command[-3:] == ["tests/test_one.py", "-k", "example"]

