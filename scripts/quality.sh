#!/bin/sh
set -eu

python scripts/check_dev_tools.py quality

printf '%s\n' '[1/8] Python compilation'
python -m compileall -q src tests scripts

printf '%s\n' '[2/8] Test suite + coverage regression'
python -m pytest tests --cov=src --cov-report=term --cov-report=json:.coverage-regression.json --cov-fail-under=78
PYTHONPATH=src python -m envs_xmpp_ops.regression coverage-check

printf '%s\n' '[3/8] Ruff'
python -m ruff check .

printf '%s\n' '[4/8] mypy'
python -m mypy src

printf '%s\n' '[5/8] Build distributions'
rm -rf build dist
python -m build

printf '%s\n' '[6/8] Distribution metadata'
python -m twine check dist/*

printf '%s\n' '[7/8] Git whitespace errors'
git --no-pager diff --check HEAD

printf '%s\n' '[8/8] Dependency audit (pip-audit)'

audit_requirements=$(mktemp)
trap 'rm -f "$audit_requirements"' EXIT

uv export --locked --all-extras \
    --no-emit-project \
    --no-hashes \
    --format requirements.txt \
    --output-file "$audit_requirements"

python -m pip_audit --no-deps --strict \
    -r "$audit_requirements"

printf '%s\n' 'Quality checks passed (8/8).'
