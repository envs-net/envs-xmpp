from __future__ import annotations

from pathlib import Path

from envs_xmpp_ops.release_audit import audit_shared_core_release_state, main


def _write_project(root: Path, version: str = "1.1.0") -> None:
    (root / "constraints").mkdir()
    (root / "scripts").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "consumer"\nversion = "1"\ndependencies = ["envs-xmpp>=1.1.0,<2.0"]\n',
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("envs-xmpp>=1.1.0,<2.0\n", encoding="utf-8")
    for name in ("python312.txt", "python313.txt"):
        (root / "constraints" / name).write_text(f"envs-xmpp=={version}\n", encoding="utf-8")
    (root / "scripts" / "_envs_xmpp_bootstrap.py").write_text(
        f'_REQUIRED_VERSION = "{version}"\n', encoding="utf-8"
    )


def test_release_audit_accepts_aligned_consumer(tmp_path):
    _write_project(tmp_path)
    result = audit_shared_core_release_state(tmp_path, expected_version="1.1.0")
    assert result.ok is True
    assert result.errors == ()


def test_release_audit_reports_all_alignment_errors(tmp_path):
    _write_project(tmp_path, version="1.0.0")
    (tmp_path / "requirements.txt").write_text("envs-xmpp>=1.0.0,<2.0\n", encoding="utf-8")
    result = audit_shared_core_release_state(tmp_path, expected_version="1.1.0")
    assert result.ok is False
    assert len(result.errors) == 4
    assert any("requirements.txt" in error for error in result.errors)
    assert any("python312.txt" in error for error in result.errors)
    assert any("python313.txt" in error for error in result.errors)
    assert any("_REQUIRED_VERSION" in error for error in result.errors)


def test_release_audit_cli_returns_nonzero_on_mismatch(tmp_path, capsys):
    _write_project(tmp_path, version="1.0.0")
    assert main(["--root", str(tmp_path), "--expected-version", "1.1.0"]) == 1
    assert "ERROR:" in capsys.readouterr().err
