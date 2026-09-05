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
    ├── deploy.py
    ├── git.py
    ├── profile.py
    ├── systemd.py
    └── venv.py
```

`envs_xmpp_ops` does not solve bootstrap by assuming the package is already
installed. Bot deploy scripts remain thin stdlib-only bootstrap frontends; they
may install/pin this distribution into a dedicated deploy environment before
handing off to the shared operations code.

## CI and PyPI releases

GitHub Actions tests Python 3.12 and 3.13. A `vX.Y.Z` tag is accepted only when
it exactly matches `project.version` in `pyproject.toml`. Release distributions
are published through PyPI Trusted Publishing/OIDC, without a long-lived PyPI
token.

Before the first release configure a PyPI Trusted Publisher for:

- PyPI project: `envs-xmpp`
- GitHub owner: `envs-net`
- Repository: `envs-xmpp`
- Workflow: `release.yml`
- Environment: `pypi`
