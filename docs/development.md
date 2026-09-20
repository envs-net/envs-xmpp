# Development guide

## Supported Python versions

envs-xmpp supports Python 3.12 and 3.13. The package deliberately has no mandatory third-party runtime dependencies.

## Local setup

```bash
git clone https://github.com/envs-net/envs-xmpp.git
cd envs-xmpp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Use an editable install when testing a core change together with a bot:

```bash
/path/to/bot/.venv/bin/python -m pip install -e /path/to/envs-xmpp
```

## Quality gates

The repository quality gate is intentionally small and deterministic:

```bash
./scripts/quality.sh
python -m pytest
python -m ruff check .
python -m mypy src
python -m build
python -m twine check dist/*
```

GitHub Actions runs the tests on Python 3.12 and 3.13. Release tags are accepted only when `vX.Y.Z` exactly matches `project.version`. Publishing uses PyPI Trusted Publishing/OIDC.

## Compatibility rules

The 1.x series follows these rules:

- documented public imports remain available throughout 1.x;
- additions may appear in minor releases;
- behavior fixes should preserve the documented contract;
- incompatible public API changes require a 2.0 release;
- direct imports from documented modules are supported even when a convenience re-export also exists;
- names beginning with `_` are private unless explicitly documented otherwise.

## Testing changes in both bots

A shared change is not complete until its own tests pass and the affected bot suites pass against the same checkout. Prefer focused tests while iterating, then run each repository's full quality gate before release.

Do not move application policy into envs-xmpp merely to reduce line count. The shared package owns mechanisms; the bots own policy and user-facing behavior.

## Consumer release-state audit

`python -m envs_xmpp_ops.release_audit` is intended for envsbot and muc_banbot
quality gates. It checks that `pyproject.toml`, `requirements.txt`, both Python
constraint snapshots and the deploy bootstrap all agree with the installed
`envs-xmpp` version. This catches partial shared-core upgrades before a release
tag or production deployment. Consumer package versions are deliberately not
part of this check and can remain unchanged while a release is still being
assembled.

## Shared release verification

`envs_xmpp_ops.release` provides the mechanism used by both bot repositories
for release-tag and wheel checks. Consumers declare only their version source,
distribution/wheel name, console entry point, required packaged members and
canonical runtime assets. The shared checker verifies the tag/version match,
asset hashes and entry-point metadata, then installs the wheel in a fresh
virtualenv, runs `pip check`, resolves declared runtime assets and exercises the
installed CLI with `--version`. Bot-specific release policy stays in the bot
repositories.
