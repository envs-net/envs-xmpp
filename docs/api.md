# Stable API reference

This document maps the supported envs-xmpp 1.x surfaces. It is an API guide, not an exhaustive list of every implementation detail.

## Version

```python
from envs_xmpp_core import __version__
```

## XMPP

Package-level convenience imports are available from `envs_xmpp_core.xmpp` for the most commonly shared operations.

### Avatar/profile

```python
from envs_xmpp_core.xmpp import (
    AvatarPayload,
    load_avatar_payload,
    publish_xep0084_avatar,
    set_presence_avatar_hash,
)
```

Use these helpers to normalize one avatar payload and reuse the same SHA-1/media type across XEP-0054/XEP-0084/XEP-0153 integration code. Bot policy decides which protocol paths are required or optional.

### Confirmed MUC joins

```python
from envs_xmpp_core.xmpp import join_muc_confirmed
```

The confirmed join transaction handles Slixmpp API compatibility, self-presence confirmation, timeout/cancellation cleanup and failure settlement. Applications provide their room-state callbacks and retry policy.

### Occupants

```python
from envs_xmpp_core.xmpp import (
    MucOccupant,
    occupant_snapshot,
    find_occupant_by_jid,
    occupant_is_admin_or_owner,
)
```

The occupant model normalizes XMPP identity facts. Authorization policy remains application-owned.

### Message routing

```python
from envs_xmpp_core.xmpp import (
    MessageTarget,
    TaskLocalReplyRoute,
    classify_message_target,
)
```

Use the routing model for DM/MUC-PM/groupchat mechanics. Encryption and command policy stay in the consumer.

Additional protocol helpers remain supported through documented direct modules such as `envs_xmpp_core.xmpp.connection`, `jid`, `invites`, `pending_invites` and `stanza`.

## Runtime

Convenience imports from `envs_xmpp_core.runtime` include alert and diagnostic primitives:

```python
from envs_xmpp_core.runtime import AlertTracker, diagnostic_payload
```

Documented direct modules provide the broader runtime toolkit:

- `runtime.tasks` - supervised resilient tasks and heartbeat-aware sleeping;
- `runtime.watchdog` - event-loop/systemd watchdog state;
- `runtime.lifecycle` - ordered lifecycle phases and results;
- `runtime.health` - passive health checks/snapshots;
- `runtime.alerts` - transition-aware operational alert state;
- `runtime.diagnostics` - redacted structured error payloads;
- `runtime.systemd` - runtime systemd notification helpers.

## Storage

The most common outbox types are re-exported from `envs_xmpp_core.storage`:

```python
from envs_xmpp_core.storage import OutboxMessage, OutboxStore
```

Documented direct modules include:

- `storage.sqlite` - generic SQLite integrity helpers;
- `storage.archive` - safe ZIP member validation/streaming;
- `storage.backup` - backup archive construction/verification;
- `storage.restore` - verified restore staging/transactions;
- `storage.managed` and `storage.files` - managed retention/file helpers;
- `storage.outbox` - durable delivery queue primitives.

The core does not own either bot's database schema.

## Configuration

Use direct modules under `envs_xmpp_core.config`:

```python
from envs_xmpp_core.config.schema import ConfigKeySpec, schema_value_violation
from envs_xmpp_core.config.python_file import apply_config_edit_transaction
```

These modules provide schema metadata, literal parsing, normalized changes and transactional Python config editing. Consumers define settings, validation policy and user-facing text.

## Security and formatting

```python
from envs_xmpp_core.security import redact_text, redact_url
from envs_xmpp_core.formatting import format_bytes, format_duration
```

## Deployment operations

Common deployment imports are available from `envs_xmpp_ops`:

```python
from envs_xmpp_ops import DeploymentProfile, deployment_environment, systemd_venv
```

Direct modules under `envs_xmpp_ops` cover accounts, Git, interaction, paths, service/systemd handling, virtualenvs and deployment transactions. Bot-specific migration/backup/service-hardening policy belongs in the frontend repository.

## Compatibility

Within the 1.x line, documented public imports are intended to remain available. New APIs may be added in minor releases. Private names and undocumented implementation details may change without compatibility guarantees.
