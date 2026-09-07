from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from envs_xmpp_ops.accounts import account_exists
from envs_xmpp_ops.deploy import (
    backup_checkout_files,
    restore_checkout_files,
    run_release_update_transaction,
)
from envs_xmpp_ops.git import (
    approve_release_target,
    describe_revision,
    git_is_ancestor,
    head_is_detached,
    is_stable_release_tag,
    local_tag_object,
    prepare_release_target,
    release_target_relation,
    remote_tag_object,
    remote_tags,
    require_clean_tracked_tree,
    select_release_remote,
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


def test_release_remote_prefers_branch_configuration_then_origin():
    def run_git(*args: str, **_kwargs: object):
        if args == ("remote",):
            return _result(stdout="origin\nupstream\n")
        if args[:4] == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            return _result(stdout="main\n")
        if args[:3] == ("config", "--get", "branch.main.remote"):
            return _result(stdout="upstream\n")
        raise AssertionError(args)

    assert select_release_remote(run_git) == "upstream"
    assert select_release_remote(run_git, configured_remote="origin") == "origin"


def test_prepare_release_target_fetches_only_selected_stable_tag():
    calls: list[tuple[str, ...]] = []

    def run_git(*args: str, **_kwargs: object):
        calls.append(args)
        if args == ("remote",):
            return _result(stdout="origin\n")
        if args[:4] == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            return _result(1)
        if args[:4] == ("fetch", "--prune", "--no-tags", "origin"):
            return _result()
        if args[:4] == ("ls-remote", "--tags", "--refs", "--sort=-version:refname"):
            return _result(stdout="a refs/tags/v2.0.0-rc1\nb refs/tags/v1.9.0\n")
        if args[:3] == ("ls-remote", "--tags", "origin"):
            return _result(stdout="tag-object refs/tags/v1.9.0\n")
        if args[:3] == ("rev-parse", "--verify", "--quiet"):
            if str(args[-1]).endswith("^{commit}"):
                return _result()
            return _result(1)
        if args[:3] == ("fetch", "--no-tags", "origin"):
            return _result()
        raise AssertionError(args)

    remote, tag = prepare_release_target(run_git, None)

    assert (remote, tag) == ("origin", "v1.9.0")
    assert ("fetch", "--prune", "--no-tags", "origin") in calls
    assert (
        "fetch",
        "--no-tags",
        "origin",
        "refs/tags/v1.9.0:refs/tags/v1.9.0",
    ) in calls


def test_prepare_release_target_rejects_nonstable_explicit_tag():
    with pytest.raises(RuntimeError, match="stable vX.Y.Z"):
        prepare_release_target(lambda *_args, **_kwargs: _result(), "main")


def test_release_target_relation_classifies_git_ancestry():
    outcomes = iter((_result(0), _result(1)))

    def run_git(*args: str, **_kwargs: object):
        assert args[0] == "merge-base"
        return next(outcomes)

    assert release_target_relation(run_git, "v2.0.0") == "upgrade"


def test_shared_release_approval_policy_handles_downgrade_and_same_release():
    prompts: list[str] = []
    lines: list[str] = []

    assert (
        approve_release_target(
            current="v2.0.0",
            target="v1.9.0",
            relation="downgrade",
            requested_tag=None,
            allow_downgrade=False,
            head_is_detached=False,
            require_confirmation=prompts.append,
            print_func=lines.append,
        )
        is False
    )
    assert prompts == []
    assert any("No newer release" in line for line in lines)

    assert (
        approve_release_target(
            current="v2.0.0",
            target="v2.0.0",
            relation="same",
            requested_tag=None,
            allow_downgrade=False,
            head_is_detached=True,
            require_confirmation=prompts.append,
            print_func=lines.append,
        )
        is False
    )
    assert any("Already at release" in line for line in lines)


def test_release_update_transaction_runs_common_steps_and_restores_operator_file(tmp_path: Path):
    root = tmp_path / "checkout"
    root.mkdir()
    config = root / "config.py"
    config.write_text("operator\n", encoding="utf-8")
    events: list[str] = []

    def checkout(target: str) -> None:
        events.append(f"checkout:{target}")
        config.write_text("release\n", encoding="utf-8")

    result = run_release_update_transaction(
        root=root,
        prepare_target=lambda: ("origin", "v2.0.0"),
        approve_target=lambda target: events.append(f"approve:{target}") or True,
        protected_paths=lambda: {"config": config},
        stop_service=lambda: events.append("stop") or True,
        before_checkout=lambda: events.append("before"),
        checkout_target=checkout,
        apply_target=lambda target: events.append(f"apply:{target}"),
        ask_start=lambda: events.append("start"),
        print_func=lambda line: events.append(f"print:{line}"),
    )

    assert result.target == "v2.0.0"
    assert result.changed is True
    assert result.stopped is True
    assert config.read_text(encoding="utf-8") == "operator\n"
    assert events.index("stop") < events.index("before") < events.index("checkout:v2.0.0")
    assert events.index("checkout:v2.0.0") < events.index("apply:v2.0.0") < events.index("start")


def test_release_update_transaction_noop_does_not_stop_or_collect_protected_paths(tmp_path: Path):
    result = run_release_update_transaction(
        root=tmp_path,
        prepare_target=lambda: ("origin", "v1.0.0"),
        approve_target=lambda _target: False,
        protected_paths=lambda: pytest.fail("no-op update must not collect protected paths"),
        stop_service=lambda: pytest.fail("no-op update must not stop the service"),
        checkout_target=lambda _target: pytest.fail("no-op update must not checkout"),
        apply_target=lambda _target: pytest.fail("no-op update must not apply"),
        ask_start=lambda: pytest.fail("no-op update must not start the service"),
        print_func=lambda _line: None,
    )

    assert result.changed is False
    assert result.stopped is False


def test_release_update_transaction_restores_protected_file_when_checkout_fails(tmp_path: Path):
    root = tmp_path / "checkout"
    root.mkdir()
    config = root / "config.py"
    config.write_text("operator\n", encoding="utf-8")

    def failing_checkout(_target: str) -> None:
        config.write_text("release\n", encoding="utf-8")
        raise RuntimeError("checkout failed")

    with pytest.raises(RuntimeError, match="checkout failed"):
        run_release_update_transaction(
            root=root,
            prepare_target=lambda: ("origin", "v2.0.0"),
            approve_target=lambda _target: True,
            protected_paths=lambda: {"config": config},
            stop_service=lambda: True,
            checkout_target=failing_checkout,
            apply_target=lambda _target: pytest.fail("failed checkout must not apply"),
            ask_start=lambda: pytest.fail("failed checkout must not start"),
            print_func=lambda _line: None,
        )

    assert config.read_text(encoding="utf-8") == "operator\n"


def test_release_update_transaction_keeps_stopped_service_on_apply_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    root = tmp_path / "checkout"
    root.mkdir()

    with pytest.raises(RuntimeError, match="validation failed"):
        run_release_update_transaction(
            root=root,
            prepare_target=lambda: ("origin", "v2.0.0"),
            approve_target=lambda _target: True,
            protected_paths=dict,
            stop_service=lambda: True,
            checkout_target=lambda _target: None,
            apply_target=lambda _target: (_ for _ in ()).throw(RuntimeError("validation failed")),
            ask_start=lambda: pytest.fail("failed update must not start"),
            failure_message="UPDATE FAILED: service remains stopped.",
            print_func=lambda _line: None,
        )

    assert "UPDATE FAILED: service remains stopped." in capsys.readouterr().err


def test_checkout_file_backup_restores_only_changed_files(tmp_path: Path):
    root = tmp_path / "checkout"
    backup_dir = tmp_path / "backup"
    root.mkdir()
    backup_dir.mkdir()
    config = root / "config.py"
    config.write_text("before\n", encoding="utf-8")
    external = tmp_path / "external.db"
    external.write_text("external\n", encoding="utf-8")
    lines: list[str] = []

    backups = backup_checkout_files(
        {"config": config, "database": external},
        root=root,
        backup_dir=backup_dir,
        print_func=lines.append,
    )
    assert len(backups) == 1
    assert backups[0].label == "config"
    assert lines == [f"PROTECT config: {config}"]

    config.write_text("after\n", encoding="utf-8")
    restore_checkout_files(backups, print_func=lines.append)

    assert config.read_text(encoding="utf-8") == "before\n"
    assert lines[-1] == f"RESTORE protected config: {config}"


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

    def which(_name: str) -> str:
        return "/usr/bin/systemctl"

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
