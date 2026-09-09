# Consolidation policy

The 1.0 release completed the large one-time consolidation of envsbot and muc_banbot. Future extraction should be evidence-driven.

## A candidate belongs in envs-xmpp when

All of the following are true:

1. **At least two real consumers need the mechanism.** A hypothetical future consumer is not enough.
2. **The semantics are materially the same.** Similar names or similar-looking code are not sufficient.
3. **The behavior is technical mechanism, not application policy.** The core may expose hooks/callbacks so each bot keeps its own policy.
4. **A shared contract can be tested independently.** The extraction should reduce duplicated correctness work rather than merely move code.
5. **The dependency direction stays clean.** envs-xmpp must not import bot modules or require bot configuration schemas.

## Keep code local when

- only one bot needs it;
- the two implementations intentionally differ;
- sharing would require many policy flags or bot-specific branches;
- a thin compatibility facade protects stable application imports;
- the abstraction would be harder to understand than the duplication.

## Review process

For future consolidation work:

1. identify the concrete duplicate behavior in both current repositories;
2. compare edge cases and failure semantics, not just function names;
3. design a bot-neutral contract;
4. add core tests for the contract;
5. migrate one consumer at a time;
6. run full quality gates for envs-xmpp and every affected consumer;
7. remove duplicate implementation only after both consumers are proven equivalent.

This policy deliberately favors a stable 1.x API and small application adapters over continuous repository-wide refactoring.
