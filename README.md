# envs-xmpp

Shared technical infrastructure for the envs.net XMPP bots [`envsbot`](https://github.com/envs-net/envsbot) and
[`muc_banbot`](https://github.com/envs-net/muc_banbot).

One distribution intentionally ships two stable Python packages:

- `envs_xmpp_core`: bot-neutral runtime, XMPP, config, storage and release primitives.
- `envs_xmpp_ops`: deployment and operations primitives.

Keeping both in one distribution gives runtime and deployment infrastructure one
version, one repository and one release pipeline while preserving the existing
import APIs used by both bots.

The package contains no bot commands, permissions, database schemas, moderation
logic, plugin systems or bot-specific lifecycle policy.

## Compatibility

- Python 3.12 and 3.13
- GPL-3.0-only
- no mandatory third-party runtime dependencies

The bots themselves remain responsible for dependencies such as Slixmpp.

Shared storage primitives include SQLite integrity checking and safe ZIP member
validation/streaming. Pending room invites use a shared typed model, deduplication and store
state machine while each bot keeps only its database adapter and bot-specific
notification/join policy.
Pagination provides a neutral page-slice model while bot frontends retain their
existing command-specific return formats.

## Development install

Install the checkout into each bot virtual environment:

```bash
python -m pip install -e /path/to/envs-xmpp
```

Existing imports remain valid:

```python
from envs_xmpp_core.runtime.tasks import TaskSupervisor
from envs_xmpp_ops.profile import DeploymentProfile
```

## Package layout

```text
src/
├── envs_xmpp_core/
│   ├── config/
│   ├── pagination.py
│   ├── release/
│   ├── runtime/
│   ├── storage/
│   │   ├── archive.py
│   │   ├── files.py
│   │   └── sqlite.py
│   └── xmpp/
└── envs_xmpp_ops/
    ├── accounts.py
    ├── deploy.py
    ├── git.py
    ├── interaction.py
    ├── paths.py
    ├── profile.py
    ├── service.py
    ├── systemd.py
    └── venv.py
```

`envs_xmpp_ops` is designed for thin bot-specific deployment frontends. The
frontends keep bot policy such as config migration, database backup/restore and
service hardening local, while shared Git release selection, systemd inspection,
operator confirmation, account/path checks and virtualenv creation live here.

Fresh installs do not assume that this package is already present. Each bot
ships a tiny stdlib-only bootstrap shim. When the exact required `envs-xmpp`
version is unavailable, that shim creates a versioned cached deployment virtualenv
below `$XDG_CACHE_HOME/envs-xmpp/deploy/` (or `~/.cache/envs-xmpp/deploy/`),
installs the pinned version from PyPI, and re-executes the deployment frontend.
`ENVS_XMPP_DEPLOY_SOURCE` can point at a local checkout or wheel for development
and pre-release testing.

## CI and PyPI releases

GitHub Actions tests Python 3.12 and 3.13. A `vX.Y.Z` tag is accepted only when
it exactly matches `project.version` in `pyproject.toml`. Release distributions
are published through PyPI Trusted Publishing/OIDC, without a long-lived PyPI
token.

PyPI publishing is configured through the `pypi` GitHub environment and the
Trusted Publisher for `envs-net/envs-xmpp` using `.github/workflows/release.yml`.

## Shared developer quality runners

`envs_xmpp_ops.quality` and `envs_xmpp_ops.testing` provide the common local
quality/test frontends used by envsbot and muc_banbot. Project-specific source
targets, generated-file checks, integration markers and coverage floors remain
declarative in each repository's `pyproject.toml`; the runner behavior and gate
ordering stay shared.

The quality runner enforces a common baseline: compilation, project validation,
warning-strict tests, Ruff repository/F401/I-UP-B gates, mypy, Git whitespace
validation and dependency audit.


## Runtime and utility primitives

The shared core also provides heartbeat-aware worker waits, asynchronous release comparison results, and neutral human-readable duration/byte formatting. Applications keep notification policy and domain-specific labels locally.
