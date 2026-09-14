# Architecture

## Purpose

envs-xmpp contains reusable technical mechanisms shared by envsbot and muc_banbot. It intentionally does not define either application's command system, moderation policy, plugin model or product behavior.

The dependency direction is one-way:

```text
envsbot ───────┐
               ├──> envs-xmpp
muc_banbot ────┘

envs-xmpp must not import either bot.
```

## Distribution layout

One PyPI distribution ships two packages:

- `envs_xmpp_core` - runtime-safe, bot-neutral primitives used by the applications;
- `envs_xmpp_ops` - deployment and operator tooling used before or around application startup.

This keeps runtime and deployment contracts on one version while preserving a clear namespace boundary.

## Core domains

`envs_xmpp_core.xmpp` owns protocol/mechanism helpers such as confirmed MUC joins, occupant normalization, routing and avatar publication.

`envs_xmpp_core.runtime` owns task supervision, watchdog/lifecycle/health helpers, alerts and safe diagnostics.

`envs_xmpp_core.storage` owns generic SQLite/archive/backup/restore/outbox mechanisms without defining an application's schema or retention policy.

`envs_xmpp_core.config` owns typed schema/editing mechanisms without defining the bots' settings.

`envs_xmpp_core.security` owns generic redaction helpers.

`envs_xmpp_ops` owns Git, systemd, virtualenv, path/account and deployment transaction mechanisms.

## Application-owned policy

The following remain local by design:

- command names, permissions and reply wording;
- moderation and protection policy;
- OMEMO behavior;
- plugin systems and feature modules;
- application database schemas;
- concrete health severity decisions and recovery policy;
- service-specific configuration defaults;
- operator notifications and room policy.

A thin adapter is acceptable when it protects these boundaries. Removing every wrapper is not a goal.

## Stability principle

The shared layer should grow from observed common behavior, not speculative abstraction. See [consolidation-policy.md](consolidation-policy.md).

## Deployment frontend boundary

`envs_xmpp_ops.deploy.DeploymentTarget` owns the common immutable deployment
coordinates (checkout, virtualenv, config, service account/unit, base Python)
and the virtualenv/environment helpers used by both bots.  Each application
subclasses it only for project-specific paths and executable names.  The
shared package continues to own Git/systemd/virtualenv transactions; the bot
frontends retain prompts, config migration, permission policy and runtime-path
validation.  Small local wrapper functions are intentionally allowed as test
and dependency-injection seams rather than duplicating the underlying
mechanism.

## Shared health facts

`envs_xmpp_core.runtime.health` owns policy-neutral task, watchdog, lifecycle
and room-inventory normalization.  It also provides the common message-based
`HealthCheck` builder and ordered snapshot-message flattening used by status
renderers.  Applications decide which facts are warnings versus errors and
keep application-specific checks such as RSS/plugin health, moderation rights,
RTBL and backup policy local.
