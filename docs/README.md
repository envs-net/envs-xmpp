# envs-xmpp documentation

envs-xmpp is the shared technical foundation for envsbot and muc_banbot.

## Guides

- [Development](development.md) - local setup, tests, quality gates, release workflow and compatibility rules
- [Architecture](architecture.md) - package boundaries, dependency direction and ownership rules
- [Stable API](api.md) - supported public modules and practical examples
- [Consolidation policy](consolidation-policy.md) - when code belongs in envs-xmpp and when it should remain application-local

The stable API is intentionally smaller than the implementation tree. Direct imports from documented modules are supported; private names and undocumented implementation details are not API promises.
