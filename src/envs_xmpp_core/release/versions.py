"""Deterministic version comparison for release tags."""
from __future__ import annotations
import re


def normalize_version(version: str) -> str:
    value = str(version).strip()
    return value[1:] if value.lower().startswith("v") else value


def parse_version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(version)))


def _trim_release_zeros(parts: tuple[int, ...]) -> tuple[int, ...]:
    normalized = list(parts)
    while len(normalized) > 1 and normalized[-1] == 0:
        normalized.pop()
    return tuple(normalized)


def version_sort_key(version: str) -> tuple[tuple[int, ...], int, int] | None:
    value = normalize_version(version).strip().lower()
    match = re.fullmatch(r"(?P<release>\d+(?:\.\d+)*)(?:[-_.]?(?P<label>a|alpha|b|beta|rc)[-_.]?(?P<number>\d*))?(?:[+.-].*)?", value)
    if match is None:
        return None
    release = _trim_release_zeros(tuple(int(part) for part in match.group("release").split(".")))
    label = match.group("label")
    if label is None:
        return release, 3, 0
    rank = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}[label]
    return release, rank, int(match.group("number") or 0)


def compare_versions(left: str, right: str) -> int:
    left_key = version_sort_key(left)
    right_key = version_sort_key(right)
    if left_key is not None and right_key is not None:
        return (left_key > right_key) - (left_key < right_key)
    left_parts = _trim_release_zeros(parse_version_tuple(left))
    right_parts = _trim_release_zeros(parse_version_tuple(right))
    return (left_parts > right_parts) - (left_parts < right_parts)


def is_remote_version_newer(remote_version: str, local_version: str) -> bool:
    return compare_versions(remote_version, local_version) > 0
