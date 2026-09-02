"""GitHub latest-release helpers with injectable transport."""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlparse, urlsplit

from .versions import normalize_version

UrlOpen = Callable[..., Any]


def github_api_url_from_release_url(release_url: str) -> str | None:
    parsed = urlparse(str(release_url))
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def release_tag_from_redirect_url(final_url: str) -> str:
    parsed = urlsplit(str(final_url))
    marker = "/releases/tag/"
    if marker not in parsed.path:
        raise ValueError(f"Unexpected release redirect URL: {final_url}")
    raw_tag = parsed.path.split(marker, 1)[1].strip("/")
    if not raw_tag or "/" in raw_tag:
        raise ValueError("Could not extract release tag from redirect URL")
    tag = unquote(raw_tag).strip()
    if not tag:
        raise ValueError("Could not extract release tag from redirect URL")
    return normalize_version(tag)


def fetch_latest_release_version_via_github_api_sync(
    release_url: str,
    *,
    user_agent: str,
    timeout: float = 15.0,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> str:
    api_url = github_api_url_from_release_url(release_url)
    if not api_url:
        raise ValueError("release URL is not a supported GitHub releases URL")
    request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": user_agent},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    tag = str(payload.get("tag_name", "")).strip()
    if not tag:
        raise ValueError("GitHub API response did not contain tag_name")
    return normalize_version(tag)


def fetch_latest_release_version_via_redirect_sync(
    release_url: str,
    *,
    user_agent: str,
    timeout: float = 15.0,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> str:
    if not release_url:
        raise ValueError("release URL is not configured")
    request = urllib.request.Request(release_url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
    return release_tag_from_redirect_url(final_url)


def fetch_latest_release_version_sync(
    release_url: str,
    *,
    user_agent: str,
    timeout: float = 15.0,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> str:
    if not release_url:
        raise ValueError("release URL is not configured")
    try:
        return fetch_latest_release_version_via_github_api_sync(
            release_url, user_agent=user_agent, timeout=timeout, urlopen=urlopen
        )
    except Exception:
        return fetch_latest_release_version_via_redirect_sync(
            release_url, user_agent=user_agent, timeout=timeout, urlopen=urlopen
        )
