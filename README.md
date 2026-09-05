# envs-xmpp

Shared technical infrastructure for the envs.net XMPP bots `envsbot` and
`muc_banbot`.

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
│   ├── release/
│   ├── runtime/
│   ├── storage/
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
ships a tiny stdlib-only bootstrap shim. When the required `envs-xmpp` minor
series is unavailable, that shim creates a cached deployment virtualenv below
`$XDG_CACHE_HOME/envs-xmpp/deploy/` (or `~/.cache/envs-xmpp/deploy/`), installs
the pinned compatible series from PyPI, and re-executes the deployment frontend.
`ENVS_XMPP_DEPLOY_SOURCE` can point at a local checkout or wheel for development
and pre-release testing.

## CI and PyPI releases

GitHub Actions tests Python 3.12 and 3.13. A `vX.Y.Z` tag is accepted only when
it exactly matches `project.version` in `pyproject.toml`. Release distributions
are published through PyPI Trusted Publishing/OIDC, without a long-lived PyPI
token.

PyPI publishing is configured through the `pypi` GitHub environment and the
Trusted Publisher for `envs-net/envs-xmpp` using `.github/workflows/release.yml`.
