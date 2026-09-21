#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

# Keep the src-layout import path relative. mutmut changes cwd to ./mutants for
# mutant tests, so "src" resolves to the mutated checkout rather than here.
export PYTHONPATH=src

command=${1:-run}
if [ "$#" -gt 0 ]; then
    shift
fi

case "$command" in
    fresh)
        python scripts/check_dev_tools.py mutation
        rm -rf mutants
        exec mutmut run "$@"
        ;;
    run|results|browse)
        python scripts/check_dev_tools.py mutation
        exec mutmut "$command" "$@"
        ;;
    check)
        exec python -m envs_xmpp_ops.regression mutation-check
        ;;
    accept)
        exec python -m envs_xmpp_ops.regression mutation-accept
        ;;
    *)
        printf 'Usage: %s [fresh|run|results|browse|check|accept] [mutmut arguments...]\n' "$0" >&2
        exit 2
        ;;
esac
