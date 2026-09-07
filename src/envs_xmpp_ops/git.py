"""Git primitives used by deployment frontends."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

GitRunner = Callable[..., subprocess.CompletedProcess[str]]
ErrorFactory = Callable[[str], Exception]
ReleaseRelation = Literal["same", "upgrade", "downgrade", "diverged"]

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


def select_release_remote(
    run_git_command: GitRunner,
    *,
    configured_remote: str | None = None,
    error_factory: ErrorFactory = RuntimeError,
) -> str:
    """Select the Git remote used for stable-release discovery.

    An explicitly configured remote wins.  Otherwise the current branch's
    configured remote is preferred, followed by ``origin`` and finally the
    sole configured remote.  Ambiguous or missing configurations fail closed
    instead of silently guessing.
    """
    result = run_git_command("remote", capture=True, announce=False)
    remotes = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    if configured_remote:
        if configured_remote not in remotes:
            raise error_factory(f"configured Git remote does not exist: {configured_remote}")
        return configured_remote

    branch_result = run_git_command(
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        capture=True,
        check=False,
        announce=False,
    )
    if branch_result.returncode == 0:
        branch = branch_result.stdout.strip()
        if branch:
            remote_result = run_git_command(
                "config",
                "--get",
                f"branch.{branch}.remote",
                capture=True,
                check=False,
                announce=False,
            )
            branch_remote = (
                remote_result.stdout.strip() if remote_result.returncode == 0 else ""
            )
            if branch_remote and branch_remote != "." and branch_remote in remotes:
                return branch_remote

    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    if not remotes:
        raise error_factory("no Git remote is configured for release discovery")
    raise error_factory(
        "multiple Git remotes are configured and no release remote could be selected; "
        "configure the deployment remote explicitly"
    )


def latest_stable_remote_tag(
    run_git_command: GitRunner,
    remote: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> str:
    """Return the newest stable ``vX.Y.Z`` tag advertised by *remote*."""
    tags = [tag for tag in remote_tags(run_git_command, remote) if is_stable_release_tag(tag)]
    if not tags:
        raise error_factory(
            f"no stable Git release tags (vX.Y.Z) found on remote {remote!r}"
        )
    return tags[0]


def sync_release_tag(
    run_git_command: GitRunner,
    remote: str,
    tag: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> None:
    """Fetch exactly one release tag without overwriting a conflicting local tag."""
    remote_object = remote_tag_object(
        run_git_command,
        remote,
        tag,
        error_factory=error_factory,
    )
    local_object = local_tag_object(run_git_command, tag, error_factory=error_factory)
    if local_object is not None:
        if local_object != remote_object:
            raise error_factory(
                f"local release tag {tag!r} conflicts with remote {remote!r}; refusing to "
                "overwrite it. Verify the tag manually before retrying."
            )
        return

    run_git_command(
        "fetch",
        "--no-tags",
        remote,
        f"refs/tags/{tag}:refs/tags/{tag}",
    )


def prepare_release_target(
    run_git_command: GitRunner,
    requested_tag: str | None,
    *,
    configured_remote: str | None = None,
    error_factory: ErrorFactory = RuntimeError,
) -> tuple[str, str]:
    """Refresh release metadata and return ``(remote, stable_tag)``.

    Only branch refs and the selected release tag are fetched.  Bulk tag
    imports are deliberately avoided so unrelated/conflicting local tags are
    left untouched.
    """
    if requested_tag is not None and not is_stable_release_tag(requested_tag):
        raise error_factory("--to must name a stable vX.Y.Z release tag")

    remote = select_release_remote(
        run_git_command,
        configured_remote=configured_remote,
        error_factory=error_factory,
    )
    run_git_command("fetch", "--prune", "--no-tags", remote)
    target = requested_tag or latest_stable_remote_tag(
        run_git_command,
        remote,
        error_factory=error_factory,
    )
    sync_release_tag(
        run_git_command,
        remote,
        target,
        error_factory=error_factory,
    )
    validate_tag(run_git_command, target, error_factory=error_factory)
    return remote, target


def release_target_relation(
    run_git_command: GitRunner,
    target: str,
    *,
    error_factory: ErrorFactory = RuntimeError,
) -> ReleaseRelation:
    """Classify *target* relative to the checkout's current ``HEAD``."""
    head_before_target = git_is_ancestor(
        run_git_command,
        "HEAD",
        target,
        error_factory=error_factory,
    )
    target_before_head = git_is_ancestor(
        run_git_command,
        target,
        "HEAD",
        error_factory=error_factory,
    )
    if head_before_target and target_before_head:
        return "same"
    if head_before_target:
        return "upgrade"
    if target_before_head:
        return "downgrade"
    return "diverged"


def approve_release_target(
    *,
    current: str,
    target: str,
    relation: ReleaseRelation,
    requested_tag: str | None,
    allow_downgrade: bool,
    head_is_detached: bool,
    require_confirmation: Callable[[str], None],
    print_func: Callable[[str], None] = print,
    error_factory: ErrorFactory = RuntimeError,
) -> bool:
    """Apply the shared safety policy for checking out a release target.

    The function is deliberately callback-driven so deployment frontends keep
    control of interactive confirmation and their own exception type.
    """
    if relation == "upgrade":
        require_confirmation(f"Update {current} to {target}?")
        return True

    if relation == "same":
        if head_is_detached:
            print_func(f"Already at release {target}; nothing to update.")
            return False
        require_confirmation(
            f"Current HEAD already matches {target}. Pin this checkout to the release tag?"
        )
        return True

    if relation == "downgrade":
        if requested_tag is None:
            print_func(f"No newer release is available (latest release: {target}).")
            print_func(f"The current checkout {current} contains commits newer than {target}.")
            print_func("Nothing to update; the development branch is never deployed automatically.")
            return False
        if not allow_downgrade:
            raise error_factory(
                f"requested release {target} is older than the current checkout {current}; "
                "refusing downgrade (use --allow-downgrade only for an intentional rollback)"
            )
        print_func(
            "WARNING: this is an explicit code downgrade. The helper does not downgrade the "
            "database schema; an incompatible database may require restoring a matching backup."
        )
        require_confirmation(
            f"Downgrade {current} to {target}? A matching database backup may be required."
        )
        return True

    raise error_factory(
        f"release {target} is not on the current HEAD history; refusing a non-fast-forward "
        "deployment. Resolve the Git history manually before updating."
    )
