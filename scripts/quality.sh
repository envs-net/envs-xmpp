#!/bin/sh
set -eu

printf '%s\n' '[1/7] Python compilation'
python -m compileall -q src tests scripts

printf '%s\n' '[2/7] Test suite + coverage regression'
python -m pytest tests --cov=src --cov-report=term --cov-report=json:.coverage-regression.json --cov-fail-under=78
PYTHONPATH=src python -m envs_xmpp_ops.regression coverage-check

printf '%s\n' '[3/7] Ruff'
python -m ruff check .

printf '%s\n' '[4/7] mypy'
python -m mypy src

printf '%s\n' '[5/7] Build distributions'
rm -rf build dist
python -m build

printf '%s\n' '[6/7] Distribution metadata'
python -m twine check dist/*

printf '%s\n' '[7/7] Git whitespace errors'
git --no-pager diff --check HEAD

printf '%s\n' 'Quality checks passed (7/7).'
