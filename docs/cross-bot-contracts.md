# Cross-bot runtime contracts (Phase 7)

`envs-xmpp` provides shared mechanisms; each consumer still owns authorization,
moderation, commands, encryption fallback configuration, retry timing, and backup
policy. The immutable cases in `envs_xmpp_ops.contract_cases` are **test-only**
fixtures, not executable production policy or versioned protocol messages.

The same case collections are used by:

- `envs-xmpp/tests/test_cross_bot_contract_cases.py` (core reference)
- `envsbot_envs/tests/test_shared_adapter_contracts.py` (real envsbot adapters)
- `muc_banbot/tests/test_shared_adapter_contracts.py` (real BanBot adapters)

They check the following invariants independently in the respective bots:

1. **Message transport**: a MUC nickname does not convert an ordinary `chat`
   stanza into a group command; a MUC PM stays private; a decrypt failure must
   never route ciphertext as plaintext.
2. **Room lifecycle**: `joined` requires separately verified self-presence; a
   stale tracker observation cannot authorize membership; intentional leave
   does not count as a join failure.
3. **Outbound encryption**: explicit per-message choice overrides inherited
   context. Explicitly encrypted replies cannot silently downgrade when the
   backend rejects or cannot encrypt; a deliberately enabled plaintext fallback
   remains an application policy decision.
4. **Task snapshots**: `TaskInfo.scope/name` is the single canonical identity;
   the read-only `plugin` and `group` properties are compatibility aliases.
5. **Config previews**: top-level and nested secret values are redacted before
   operator-facing output.
6. **Backup safety**: an absent OMEMO pair is optional, while a half-present
   state/identity pair is incomplete and must not be treated as complete.
7. **Help resolution**: known alias prefixes resolve without invoking a handler.

To run the Core tests, use `./scripts/quality.sh` in `envs-xmpp`.
For either bot, install the *local* sibling Core in its Python 3.13 development
virtual environment before `./scripts/quality.sh`, until the coordinated Phase 8
release. The bot suites must run independently; importing one bot from the
other is intentionally unnecessary.

## Adapter audit

The two identical OMEMO JID validators and optional dependency logger setups
now delegate to the Core through compatibility wrappers. The substantially
larger shared-looking deployment and constraint scripts are left unchanged in
Phase 7: modifying them here would mix runtime contract validation with
release/deployment behavior. Review deployment and dependency pins during
Phase 8 instead.

**No version changes are part of Phase 7.**
