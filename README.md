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

