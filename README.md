# envs-xmpp-core

Shared technical runtime infrastructure for `envsbot` and `muc_banbot`.

The package intentionally contains no bot commands, permissions, database
schemas, moderation logic, plugin systems or bot-specific lifecycle code.
Public compatibility facades remain in the bot repositories while migrations
are in progress.

## Compatibility

- Python 3.12 and 3.13
- `slixmpp>=1.8,<2`
- GPL-3.0-only

## Development install

For local development, install the checkout into each bot virtualenv:

```bash
python -m pip install -e /path/to/envs-xmpp-core
```

The bot repositories keep compatibility facades while the implementation lives
in this package. Their reproducible constraint files pin the tested core release.

## 0.1.1 compatibility fixes

- restore task-like object compatibility used by lifecycle tests and embedders
- support lazily supplied watchdog options for bots that apply runtime config later
- support deferred systemd `READY=1` notification after reconnect completion
- add the legacy MUC join-with-timeout primitive including timeout cleanup
- preserve configurable Slixmpp signature inspection through bot facades


## 0.1.2 invite parsing

- add a neutral `RoomInvite` model and shared XEP-0045/XEP-0249 stanza parsing
- share invite age calculation while keeping persistence, policy, commands, and notifications bot-local
- add a read-only SQLite integrity/foreign-key verification primitive while backup policy stays bot-local

## CI and PyPI releases

GitHub Actions runs the test suite on Python 3.12 and 3.13 for every branch push
and pull request.

PyPI releases use Trusted Publishing (OIDC); no long-lived PyPI API token is
stored in GitHub. The release workflow only accepts tags that exactly match the
version declared in `pyproject.toml`.

Release procedure:

1. Update `project.version` in `pyproject.toml`.
2. Run `python -m pip install -e ".[dev]"` and `./scripts/quality.sh`.
3. Commit and push the release state.
4. Create and push the matching tag, for example `v0.1.2`.
5. Approve the protected GitHub `pypi` environment if approval is enabled.

Before the first release, configure a PyPI Trusted Publisher (a pending
publisher is sufficient for a package that does not exist on PyPI yet) with:

- Owner: `envs-net`
- Repository: `envs-xmpp-core`
- Workflow: `release.yml`
- Environment: `pypi`
- PyPI project name: `envs-xmpp-core`

The first successful trusted publication can create the PyPI project.

