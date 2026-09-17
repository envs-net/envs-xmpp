# Stable API reference

This document maps the supported envs-xmpp 1.x surfaces. It is an API guide, not an exhaustive list of every implementation detail.

## Version

```python
from envs_xmpp_core import __version__
```

## XMPP

Package-level convenience imports are available from `envs_xmpp_core.xmpp` for the most commonly shared operations.

### JID text normalization

```python
from envs_xmpp_core.xmpp import bare_jid, normalize_jid_text
```

`normalize_jid_text()` removes surrounding whitespace plus the known copy/paste presentation artifacts U+200B ZERO WIDTH SPACE and U+FEFF ZERO WIDTH NO-BREAK SPACE/BOM. It intentionally does not lowercase, validate, or remove a resource. `bare_jid()` layers the shared best-effort bare-JID comparison semantics on top by removing the resource and lowercasing the result. Strict JID validation remains application-owned.

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

For operator logs and alerts, stanza-safe IQ error helpers avoid stringifying Slixmpp exceptions that may otherwise render the complete raw IQ stanza:

```python
from envs_xmpp_core.xmpp import (
    iq_error_condition,
    iq_error_summary,
    iq_error_text,
)
```

`iq_error_summary()` reports values such as `IQ error forbidden: subscription denied` or `IQ timeout` without embedding the original stanza.


## Operator presentation

Version 1.1 adds a shared, policy-neutral presentation layer used by both bots for operator-facing status, task and room views:

```python
from envs_xmpp_core.presentation import (
    RoomView,
    StatusSection,
    TaskView,
    filter_room_views,
    filter_task_views,
    parse_room_list_request,
    parse_task_list_request,
    render_room_entry,
    render_status_sections,
    render_task_entry,
    render_task_summary,
)
```

The applications still collect their own runtime data and own authorization, health policy, moderation policy and command registration. The shared layer only normalizes common state, parses common filter/paging grammar, formats relative timestamps, and renders consistent operator output.

`envs_xmpp_core.pagination` also exposes `PageRequest`, `parse_page_request()` and `format_page()`. A persistent `preamble` can hold summaries and legends outside the paginated inventory so those rows remain visible on every page. When a default request carries a configured `page_size`, explicit `page`, `last`, and `all` selectors preserve it.

## Runtime

Convenience imports from `envs_xmpp_core.runtime` include alert, diagnostic, session, and reconnect primitives:

```python
from envs_xmpp_core.runtime import (
    AlertTracker,
    CooldownDecision,
    SessionLifecycleState,
    diagnostic_payload,
    run_reconnect_loop,
)
```

### Reconnect retry/backoff

`run_reconnect_loop()` owns the shared technical reconnect transaction used by both bots. It waits before transport retries, avoids opening a second connection when `session_start` wins a backoff race, waits for full application readiness instead of treating TCP connection as success, retries after a bounded readiness timeout, and stops when process shutdown begins.

Consumers inject `connect`, `disconnect_partial`, `session_started`, `shutdown_requested`, and `startup_completed` callbacks plus an `asyncio.Event` that is set only after the bot-specific session startup path is fully ready. Room reconciliation, worker lifecycle, alerts, and other recovery policy remain application-owned.

Documented direct modules provide the broader runtime toolkit:

- `runtime.tasks` - supervised resilient tasks and heartbeat-aware sleeping;
- `runtime.watchdog` - event-loop/systemd watchdog state;
- `runtime.lifecycle` - ordered lifecycle phases and results;
- `runtime.health` - passive health checks/snapshots;
- `runtime.alerts` - transition-aware operational alert state;
- `runtime.diagnostics` - redacted structured error payloads;
- `runtime.systemd` - runtime systemd notification helpers;
- `runtime.session` - XMPP session generations, reconnect counters and operator telemetry.


## Bounded MUC affiliation queries

The development API also exposes a bot-neutral XEP-0045 affiliation query helper:

```python
from envs_xmpp_core.xmpp import AffiliationQueryOptions, query_muc_affiliation

result = await query_muc_affiliation(
    xmpp["xep_0045"],
    "room@example.org",
    "owner",
    options=AffiliationQueryOptions(
        timeout_seconds=10.0,
        attempts=2,
        retry_delay_seconds=1.0,
    ),
)
```

The helper bounds IQ waits, retries timeouts and configured transient stanza errors, and returns a structured `AffiliationQueryResult`. Error summaries intentionally omit raw IQ XML so operational logs do not turn an ordinary timeout into a full stanza dump. Retry and authorization policy beyond that transport behavior remains in the consuming bot.

`SessionLifecycleState` similarly owns only generation/state tracking. Reconnect scheduling, startup phase policy, room synchronization and process shutdown remain application responsibilities.

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

## Runtime health facts

`envs_xmpp_core.runtime` exposes policy-neutral health primitives shared by both
bots:

```python
from envs_xmpp_core.runtime import (
    HealthCheck,
    HealthSnapshot,
    KeyedCooldown,
    RoomJoinHealthState,
    TaskHealthState,
    WatchdogHealthState,
    analyze_room_join_state,
    health_check_from_messages,
    health_snapshot_messages,
    supervisor_task_health_state,
    watchdog_health_state,
)
```

The helpers normalize runtime facts and message storage only. Whether a missing
room, restarted worker, watchdog lag or application-specific condition is an
operator warning or a hard error remains consumer policy.

## Deployment target and release audit

`envs_xmpp_ops.DeploymentTarget` carries the common immutable deployment
coordinates and provides virtualenv/environment helpers for thin deployment
frontends. Consumer repositories add only project-specific paths and policy.

`python -m envs_xmpp_ops.release_audit` validates that a consumer's
`pyproject.toml`, `requirements.txt`, Python constraint snapshots and deployment
bootstrap agree on the installed envs-xmpp version. It is intended as a project
validation step before tagging; it deliberately does not require consumer
package versions to be bumped during development.

## Dependency drift

`envs_xmpp_ops.inspect_dependency_drift()` compares runtime dependencies in a virtualenv with exact reviewed constraint pins.
