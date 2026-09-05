from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from envs_xmpp_ops.accounts import account_exists
from envs_xmpp_ops.git import (
    describe_revision,
    git_is_ancestor,
    head_is_detached,
    is_stable_release_tag,
    local_tag_object,
    remote_tag_object,
    remote_tags,
    require_clean_tracked_tree,
    validate_tag,
)
from envs_xmpp_ops.interaction import confirm
from envs_xmpp_ops.paths import relative_to_root
from envs_xmpp_ops.service import ask_start, stop_active_service
from envs_xmpp_ops.systemd import service_active, systemctl_exists, systemd_property
from envs_xmpp_ops.venv import create_venv_if_missing


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["fake"], returncode, stdout, stderr)


def test_confirm_is_explicit_and_eof_safe():
    assert confirm("Continue", input_func=lambda _prompt: "YES") is True
    assert confirm("Continue", input_func=lambda _prompt: "") is False

    def eof(_prompt: str) -> str:
        raise EOFError

    assert confirm("Continue", input_func=eof) is False


def test_account_exists_uses_injected_pwd_lookup():
    assert account_exists("bot", getpwnam=lambda _user: object()) is True

    def missing(_user: str):
        raise KeyError

    assert account_exists("missing", getpwnam=missing) is False


def test_relative_to_root(tmp_path: Path):
    root = tmp_path / "root"
    child = root / "data" / "file"
    outside = tmp_path / "outside"
    assert relative_to_root(child, root) is True
    assert relative_to_root(outside, root) is False
    assert relative_to_root(None, root) is False


def test_git_release_helpers():
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run_git(*args: str, **kwargs: object):
        calls.append((args, kwargs))
        if args[0] == "describe":
            return _result(stdout="v1.2.3")
        if args[0] == "symbolic-ref":
            return _result(1)
        if args[0] == "ls-remote" and "--refs" in args:
            return _result(stdout="a refs/tags/v2.0.0\nb refs/tags/v1.0.0\n")
        if args[0] == "rev-parse" and str(args[-1]).endswith("^{commit}"):
            return _result(0)
        if args[0] == "rev-parse":
            return _result(stdout="tag-object")
        if args[0] == "ls-remote":
            return _result(stdout="abc refs/tags/v2.0.0\n")
        if args[0] == "merge-base":
            return _result(0)
        if args[0] == "status":
            return _result(stdout="")
        raise AssertionError(args)

    assert is_stable_release_tag("v1.2.3") is True
    assert is_stable_release_tag("v1.2.3rc1") is False
    assert describe_revision(run_git) == "v1.2.3"
    assert head_is_detached(run_git) is True
    assert remote_tags(run_git, "origin") == ["v2.0.0", "v1.0.0"]
    validate_tag(run_git, "v2.0.0")
    assert local_tag_object(run_git, "v2.0.0") == "tag-object"
    assert remote_tag_object(run_git, "origin", "v2.0.0") == "abc"
    assert git_is_ancestor(run_git, "old", "new") is True
    require_clean_tracked_tree(run_git)
    assert calls


def test_git_helpers_preserve_frontend_error_type():
    class DeployError(RuntimeError):
        pass

    def detached_error(*_args: str, **_kwargs: object):
        return _result(2)

    with pytest.raises(DeployError):
        head_is_detached(detached_error, error_factory=DeployError)

    def missing_tag(*_args: str, **_kwargs: object):
        return _result(1)

    with pytest.raises(DeployError, match="release tag does not exist"):
        validate_tag(missing_tag, "v9.9.9", error_factory=DeployError)


def test_systemd_inspection_uses_injected_runners():
    def run_process(*_args: object, **_kwargs: object):
        return _result(stdout="/etc/systemd/system/bot.service\n")

    assert systemd_property("bot.service", "FragmentPath", run_process=run_process) == (
        "/etc/systemd/system/bot.service"
    )

    calls: list[list[str]] = []

    def run_command(command: list[str], **_kwargs: object):
        calls.append(command)
        return _result()

    which = lambda _name: "/usr/bin/systemctl"
    assert systemctl_exists("bot.service", run_command=run_command, which=which) is True
    assert service_active("bot.service", run_command=run_command, which=which) is True
    assert calls[0][:2] == ["systemctl", "cat"]
    assert calls[1][:3] == ["systemctl", "is-active", "--quiet"]


def test_service_lifecycle_callbacks():
    commands: list[tuple[str, str]] = []
    prompts: list[str] = []

    stopped = stop_active_service(
        "bot.service",
        reason="for update",
        is_active=lambda: True,
        require_confirmation=lambda prompt: prompts.append(prompt),
        run_systemctl=lambda action, service: commands.append((action, service)),
    )
    assert stopped is True
    assert prompts == ["Stop bot.service for update?"]
    assert commands == [("stop", "bot.service")]

    commands.clear()
    ask_start(
        "bot.service",
        exists=lambda: True,
        is_active=lambda: False,
        confirm=lambda _prompt: True,
        run_systemctl=lambda action, service: commands.append((action, service)),
    )
    assert commands == [("start", "bot.service"), ("is-active", "bot.service")]


def test_create_venv_if_missing_uses_frontend_runner(tmp_path: Path):
    venv = tmp_path / "venv"
    calls: list[tuple[list[object], dict[str, object]]] = []
    deployment = SimpleNamespace()

    created = create_venv_if_missing(
        venv=venv,
        venv_python=venv / "bin" / "python",
        python="python3",
        run_command=lambda command, **kwargs: calls.append((command, kwargs)),
        deployment=deployment,
    )

    assert created is True
    assert calls == [
        (
            ["python3", "-m", "venv", venv],
            {"deployment": deployment, "as_service_user": True},
        )
    ]
