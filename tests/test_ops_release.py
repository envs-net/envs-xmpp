from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from envs_xmpp_ops.release import (
    ReleaseTagSpec,
    WheelAsset,
    WheelCheckSpec,
    check_release_tag,
    inspect_wheel,
    read_python_assignment,
    smoke_test_installed_wheel,
)


def test_read_python_assignment_and_release_tag_check(tmp_path: Path) -> None:
    version_file = tmp_path / "version.py"
    version_file.write_text('__version__: str = "2.4.6"\n', encoding="utf-8")

    assert read_python_assignment(version_file) == "2.4.6"
    result = check_release_tag(
        "v2.4.6",
        root=tmp_path,
        spec=ReleaseTagSpec("version.py"),
    )
    assert result.ok is True
    assert result.expected_tag == "v2.4.6"

    mismatch = check_release_tag(
        "v2.4.5",
        root=tmp_path,
        spec=ReleaseTagSpec("version.py"),
    )
    assert mismatch.ok is False



def test_release_tag_check_supports_pep621_project_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "3.1.4"\n',
        encoding="utf-8",
    )

    result = check_release_tag(
        "v3.1.4",
        root=tmp_path,
        spec=ReleaseTagSpec("pyproject.toml", source_kind="pyproject"),
    )
    assert result.ok is True
    assert result.project_version == "3.1.4"

def test_read_python_assignment_rejects_missing_assignment(tmp_path: Path) -> None:
    version_file = tmp_path / "version.py"
    version_file.write_text('OTHER = "1.0"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="could not read __version__"):
        read_python_assignment(version_file)


def test_inspect_wheel_validates_assets_required_members_and_entry_point(tmp_path: Path) -> None:
    source = tmp_path / "pkg" / "bundled" / "avatar.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"avatar")
    wheel = tmp_path / "dist" / "demo-1.0-py3-none-any.whl"
    wheel.parent.mkdir()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/bundled/avatar.png", b"avatar")
        archive.writestr("config_sample.py", "# sample\n")
        archive.writestr(
            "demo-1.0.dist-info/entry_points.txt",
            "[console_scripts]\ndemo = pkg.cli:main\n",
        )

    spec = WheelCheckSpec(
        distribution="demo",
        wheel_glob="demo-*.whl",
        console_script="demo",
        entry_point="pkg.cli:main",
        version_prefix="demo ",
        assets=(WheelAsset("pkg/bundled/avatar.png", "pkg/bundled/avatar.png"),),
        required_members=("config_sample.py",),
    )

    result = inspect_wheel(wheel, root=tmp_path, spec=spec)
    assert result.ok is True
    assert result.errors == ()


def test_inspect_wheel_reports_drift_and_missing_entry_point(tmp_path: Path) -> None:
    source = tmp_path / "asset.txt"
    source.write_bytes(b"canonical")
    wheel = tmp_path / "demo.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/asset.txt", b"drifted")
        archive.writestr("demo-1.0.dist-info/entry_points.txt", "[console_scripts]\nother = pkg:main\n")

    result = inspect_wheel(
        wheel,
        root=tmp_path,
        spec=WheelCheckSpec(
            distribution="demo",
            wheel_glob="demo-*.whl",
            console_script="demo",
            entry_point="pkg:main",
            version_prefix="demo ",
            assets=(WheelAsset("asset.txt", "pkg/asset.txt"),),
            required_members=("config_sample.py",),
        ),
    )

    assert result.ok is False
    assert any("differs from canonical" in error for error in result.errors)
    assert any("required member" in error for error in result.errors)
    assert any("console entry point" in error for error in result.errors)


def test_smoke_test_installed_wheel_runs_assets_pip_check_and_version(tmp_path: Path) -> None:
    wheel = tmp_path / "demo-1.0-py3-none-any.whl"
    dist_info = "demo-1.0.dist-info"
    files = {
        "demo/__init__.py": "",
        "demo/asset.txt": "runtime-asset\n",
        "demo/assets.py": (
            "from pathlib import Path\n"
            "def bundled_asset(name):\n"
            "    return Path(__file__).with_name(name)\n"
        ),
        "demo/cli.py": (
            "def main():\n"
            "    import sys\n"
            "    if '--version' in sys.argv:\n"
            "        print('demo 1.0 (envs-xmpp 1.5.0)')\n"
            "        return 0\n"
            "    return 0\n"
        ),
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            "Name: demo\n"
            "Version: 1.0\n"
        ),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: envs-xmpp-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
        f"{dist_info}/entry_points.txt": "[console_scripts]\ndemo = demo.cli:main\n",
    }
    files[f"{dist_info}/RECORD"] = "".join(
        f"{name},,\n" for name in [*files, f"{dist_info}/RECORD"]
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    smoke_test_installed_wheel(
        wheel,
        spec=WheelCheckSpec(
            distribution="demo",
            wheel_glob="demo-*.whl",
            console_script="demo",
            entry_point="demo.cli:main",
            version_prefix="demo ",
            version_contains=("(envs-xmpp ",),
            assets=(
                WheelAsset(
                    source="unused",
                    member="demo/asset.txt",
                    resolver="demo.assets:bundled_asset",
                    resolver_argument="asset.txt",
                    expected_runtime_fragment="demo/asset.txt",
                ),
            ),
        ),
    )
