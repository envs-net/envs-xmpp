from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from envs_xmpp_core.config.literals import parse_literal
from envs_xmpp_core.config.python_file import replace_or_append_assignment_text
from envs_xmpp_core.release.github import github_api_url_from_release_url, release_tag_from_redirect_url
from envs_xmpp_core.release.versions import compare_versions
from envs_xmpp_core.storage.files import atomic_write_text, sha256_file
from envs_xmpp_core.xmpp.connection import connect_kwargs
from envs_xmpp_core.xmpp.jid import bare_jid, build_client_jid
from envs_xmpp_core.xmpp.stanza import safe_get_plugin, safe_plugin_value


def test_jid_helpers():
    assert bare_jid("User@Example.org/res") == "user@example.org"
    assert build_client_jid("bot@example.org/old", "new") == "bot@example.org/new"


def test_version_semantics():
    assert compare_versions("1.2.0", "1.2") == 0
    assert compare_versions("1.2.0", "1.2.0rc1") > 0
    assert compare_versions("1.3", "1.2.9") > 0


def test_github_helpers():
    assert (
        github_api_url_from_release_url("https://github.com/envs-net/envsbot/releases/latest")
        == "https://api.github.com/repos/envs-net/envsbot/releases/latest"
    )
    assert release_tag_from_redirect_url("https://github.com/envs-net/envsbot/releases/tag/v1.2.3") == "1.2.3"


def test_config_literal_and_replace():
    assert parse_literal("true") is True
    assert parse_literal("None") is None
    text = "A = 1\nB = {\n  'x': 1,\n}\n"
    updated = replace_or_append_assignment_text(text, "B", "B = {'x': 2}")
    assert "'x': 1" not in updated
    compile(updated, "config.py", "exec")
    appended = replace_or_append_assignment_text(updated, "C", "C = 3")
    assert "# Runtime config edits\nC = 3" in appended


def test_atomic_write_and_hash(tmp_path: Path):
    path = tmp_path / "secret.txt"
    atomic_write_text(path, "hello")
    assert path.read_text() == "hello"
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(sha256_file(path)) == 64


def test_connection_signature_compatibility():
    class AddressClient:
        def connect(self, address=None, use_ssl=False, force_starttls=True):
            return True

    kwargs = connect_kwargs(AddressClient(), host="example.org", port=5223, direct_tls=True)
    assert kwargs == {"address": ("example.org", 5223), "use_ssl": True, "force_starttls": False}


def test_stanza_helpers():
    class Plugin:
        def get(self, key):
            return {"jid": "room@example.org"}.get(key)

    class Stanza:
        def get_plugin(self, name, check=True):
            return Plugin() if name == "muc" else None

    plugin = safe_get_plugin(Stanza(), "muc")
    assert safe_plugin_value(plugin, "jid") == "room@example.org"


@pytest.mark.asyncio
async def test_join_muc_with_timeout_cleans_up_timed_out_membership():
    from envs_xmpp_core.xmpp.muc_join import join_muc_with_timeout

    blocker = asyncio.Event()
    left = []

    class Muc:
        async def join_muc(self, room, nick, **kwargs):
            assert kwargs == {"pshow": "chat"}
            await blocker.wait()

        async def leave_muc(self, room, nick):
            left.append((room, nick))

    with pytest.raises(TimeoutError):
        await join_muc_with_timeout(
            Muc(),
            "room@example.org",
            "Bot",
            timeout=0.01,
            join_kwargs={"pshow": "chat"},
        )
    assert left == [("room@example.org", "Bot")]


@pytest.mark.asyncio
async def test_watchdog_can_defer_ready_by_one_loop_turn():
    from envs_xmpp_core.runtime.watchdog import RuntimeWatchdog, WatchdogOptions

    ready = False
    notifications = []

    def predicate():
        return ready

    runtime = RuntimeWatchdog(
        service_name="test",
        options=WatchdogOptions(defer_ready_notification=True),
        ready_predicate=predicate,
        notifier=lambda payload: notifications.append(payload) or True,
    )

    assert runtime.notify_ready() is False
    assert notifications == []
    ready = True
    await asyncio.sleep(0)
    assert runtime.ready_sent is True
    assert notifications == ["READY=1\nSTATUS=test startup complete"]


@pytest.mark.asyncio
async def test_watchdog_options_provider_is_read_at_start(monkeypatch):
    from envs_xmpp_core.runtime.watchdog import RuntimeWatchdog, WatchdogOptions

    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    current = {"enabled": False}

    runtime = RuntimeWatchdog(
        service_name="test",
        options=WatchdogOptions(enabled=True),
        options_provider=lambda: WatchdogOptions(
            enabled=current["enabled"],
            interval_seconds=60,
        ),
        notifier=lambda _payload: True,
    )

    await runtime.start()
    assert runtime.task is None

    current["enabled"] = True
    await runtime.start()
    assert runtime.task is not None
    await runtime.stop()


def test_sqlite_integrity_primitive(tmp_path):
    import sqlite3

    from envs_xmpp_core.storage.sqlite import check_sqlite_integrity

    path = tmp_path / "healthy.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
        connection.commit()
    finally:
        connection.close()

    result = check_sqlite_integrity(path, check_foreign_keys=True)
    assert result.ok is True
    assert result.integrity == ("ok",)
    assert result.foreign_key_violations == ()
    assert result.message == "ok"


def test_sqlite_integrity_primitive_validates_missing_file(tmp_path):
    from envs_xmpp_core.storage.sqlite import check_sqlite_integrity

    path = tmp_path / "missing.sqlite3"
    result = check_sqlite_integrity(path, require_nonempty_file=True)
    assert result.ok is False
    assert result.error == f"Database file does not exist: {path.resolve()}"


def test_public_package_versions_stay_in_sync() -> None:
    import tomllib
    from pathlib import Path

    from envs_xmpp_core import __version__ as core_version
    from envs_xmpp_ops import __version__ as ops_version

    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )
    assert core_version == ops_version == project["project"]["version"]
