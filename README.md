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
