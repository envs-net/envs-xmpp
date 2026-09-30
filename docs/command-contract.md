# Shared command contract (development)

The `envs_xmpp_core.commands` module provides immutable, **policy-neutral**
`CommandSpec`, `SubcommandSpec`, and `CommandExample` models. Both bots use the
same normalization and presentation helpers for names, examples, subcommands,
usage prefixes and help-topic aliases. `resolve_longest_command` supports
multiword command names; `parse_prefixed_command` supports the BanBot prefix
entry point while preserving the original capitalization of arguments.

**Not shared:** handlers, role/affiliation mapping, authorization, public-room
rate limits, command execution, moderation, or application-specific wording.
The envsbot decorator and BanBot command router remain responsible for those
policies. Avoid adding a universal bot command router to this library.

During development, install `envs-xmpp[omemo]` from the adjacent local checkout
for the two bot Python 3.13 virtual environments; no package version is bumped
until the entire unification project passes final release checks.

Targeted contract tests live in `tests/test_commands.py`, with adapter tests
in the two bot repositories. The BanBot legacy full-help catalog and existing
individual `_..._usage_text` methods may be migrated incrementally to
structured specs without changing public command behavior.
