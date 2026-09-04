#!/bin/sh
set -eu

printf '%s\n' '[1/6] Python compilation'
python -m compileall -q src tests scripts

printf '%s\n' '[2/6] Test suite'
python -m pytest

printf '%s\n' '[3/6] Ruff'
python -m ruff check .

printf '%s\n' '[4/6] mypy'
python -m mypy src

printf '%s\n' '[5/6] Build distributions'
rm -rf build dist
python -m build

printf '%s\n' '[6/6] Distribution metadata'
python -m twine check dist/*

printf '%s\n' 'Quality checks passed (6/6).'
