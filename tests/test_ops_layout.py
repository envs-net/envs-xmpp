from pathlib import Path

from envs_xmpp_ops.layout import (
    deployment_environment,
    resolve_environment_path,
    service_account,
    split_systemd_words,
    systemd_environment_value,
    systemd_exec_path,
    systemd_path_set,
    systemd_venv,
    venv_binary,
)


def test_systemd_property_parsers() -> None:
    value = 'FOO=one "BOT_CONFIG=/etc/bot/config file.py" EMPTY='
    assert split_systemd_words(value) == ["FOO=one", "BOT_CONFIG=/etc/bot/config file.py", "EMPTY="]
    assert systemd_environment_value(value, "BOT_CONFIG") == "/etc/bot/config file.py"
    assert systemd_environment_value(value, "EMPTY") is None
    assert systemd_environment_value(value, "MISSING") is None
    assert systemd_path_set('"/one path" /two') == {"/one path", "/two"}


def test_systemd_exec_and_venv_discovery() -> None:
    value = "{ path=/srv/bot/.venv/bin/bot ; argv[]=/srv/bot/.venv/bin/bot ; }"
    assert systemd_exec_path(value) == Path("/srv/bot/.venv/bin/bot")
    assert systemd_venv(value, "bot") == Path("/srv/bot/.venv")
    assert systemd_venv(value, "other") is None
    assert systemd_exec_path("missing") is None


def test_resolve_environment_path_uses_working_directory(tmp_path: Path) -> None:
    assert resolve_environment_path(
        "config.py",
        working_directory=tmp_path,
    ) == (tmp_path / "config.py").resolve()
    assert resolve_environment_path("/etc/bot/config.py") == Path("/etc/bot/config.py")
    assert resolve_environment_path(None) is None


def test_service_account_precedence() -> None:
    assert service_account(
        environment={"BOT_USER": "override"},
        environment_name="BOT_USER",
        discovered="systemd",
        fallback="default",
    ) == "override"
    assert service_account(
        environment={},
        environment_name="BOT_USER",
        discovered="systemd",
        fallback="default",
    ) == "systemd"
    assert service_account(
        environment={},
        environment_name="BOT_USER",
        discovered=None,
        fallback="default",
    ) == "default"


def test_deployment_environment_and_venv_binary() -> None:
    env = deployment_environment(
        config_environment="BOT_CONFIG",
        config="/etc/bot/config.py",
        base={"PATH": "/bin"},
        disable_bytecode=True,
        extra={"EXTRA": "yes"},
    )
    assert env == {
        "PATH": "/bin",
        "BOT_CONFIG": "/etc/bot/config.py",
        "PYTHONDONTWRITEBYTECODE": "1",
        "EXTRA": "yes",
    }
    assert venv_binary("/srv/bot/.venv", "python") == Path("/srv/bot/.venv/bin/python")
