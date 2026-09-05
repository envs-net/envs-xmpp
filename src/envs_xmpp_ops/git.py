"""Git primitives used by deployment frontends."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

GitRunner = Callable[..., subprocess.CompletedProcess[str]]
ErrorFactory = Callable[[str], Exception]

_STABLE_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


def run_git(root: str | Path, *args: str) -> str:
    """Run git in *root* and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=Path(root),
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def worktree_is_clean(root: str | Path) -> bool:
    """Return whether git reports no tracked or untracked changes."""
    return not run_git(root, "status", "--porcelain")


def current_revision(root: str | Path) -> str:
    """Return the current commit object name."""
    return run_git(root, "rev-parse", "HEAD")


def is_stable_release_tag(tag: str) -> bool:
    """Return whether *tag* follows the supported stable vX.Y.Z form."""
    return _STABLE_RELEASE_TAG.fullmatch(tag) is not None


def describe_revision(run_git_command: GitRunner) -> str:
    """Return the operator-facing current revision description."""
    result = run_git_command(
        "describe",
        "--tags",
        "--always",
        "--dirty",
        capture=True,
        announce=False,
    )
    return result.stdout.strip() or "unknown"


def head_is_detached(
    run_git_command: GitRunner,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> bool:
    """Return whether HEAD is detached."""
    result = run_git_command(
        "symbolic-ref",
        "--quiet",
        "HEAD",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise error_factory("could not determine whether the Git checkout is attached to a branch")


def remote_tags(run_git_command: GitRunner, remote: str) -> list[str]:
    """Return remote tag names in the order emitted by git."""
    result = run_git_command(
        "ls-remote",
        "--tags",
        "--refs",
        "--sort=-version:refname",
        remote,
        capture=True,
        announce=False,
    )
    prefix = "refs/tags/"
    tags: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not fields[1].startswith(prefix):
            continue
        tag = fields[1][len(prefix) :].strip()
        if tag:
            tags.append(tag)
    return tags


def validate_tag(
    run_git_command: GitRunner,
    tag: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> None:
    """Require *tag* to resolve to a local commit."""
    result = run_git_command(
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/tags/{tag}^{{commit}}",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode != 0:
        raise error_factory(f"release tag does not exist: {tag}")


def local_tag_object(
    run_git_command: GitRunner,
    tag: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> str | None:
    """Return the local tag object ID, or None when the tag is absent."""
    result = run_git_command(
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/tags/{tag}",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    if result.returncode == 1:
        return None
    raise error_factory(f"could not inspect local release tag: {tag}")


def remote_tag_object(
    run_git_command: GitRunner,
    remote: str,
    tag: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> str:
    """Return the remote object ID for *tag*."""
    result = run_git_command(
        "ls-remote",
        "--tags",
        remote,
        f"refs/tags/{tag}",
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode != 0:
        raise error_factory(f"could not query release tag {tag!r} from remote {remote!r}")
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and fields[1] == f"refs/tags/{tag}":
            return fields[0]
    raise error_factory(f"release tag does not exist on remote {remote!r}: {tag}")


def git_is_ancestor(
    run_git_command: GitRunner,
    older: str,
    newer: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> bool:
    """Return whether *older* is an ancestor of *newer*."""
    result = run_git_command(
        "merge-base",
        "--is-ancestor",
        older,
        newer,
        capture=True,
        check=False,
        announce=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise error_factory(f"could not compare Git revisions {older!r} and {newer!r}")


def require_clean_tracked_tree(
    run_git_command: GitRunner,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> None:
    """Reject a checkout with tracked modifications."""
    result = run_git_command(
        "status",
        "--porcelain",
        "--untracked-files=no",
        capture=True,
        announce=False,
    )
    if result.stdout.strip():
        raise error_factory(
            "tracked Git worktree is not clean; commit/stash local code changes before updating\n"
            + result.stdout.rstrip()
        )
