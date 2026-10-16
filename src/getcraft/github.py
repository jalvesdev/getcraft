"""Official GitHub REST API access; no asset downloads."""

import os
import re
from urllib.parse import urlparse

import httpx


def repository_name(value: str) -> str:
    value = value.strip()
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/").rstrip("/")
    value = value.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_.-]+", value):
        raise ValueError("Expected owner/repo or https://github.com/owner/repo")
    if value.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository name")
    return value


class GitHub:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(headers=headers, timeout=30, transport=transport)
        self.cache: dict[str, tuple[str, object]] = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def get(self, url: str) -> tuple[object, str | None]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("Refusing non-GitHub API pagination URL")
        cached = self.cache.get(url)
        response = self.client.get(url, headers={"If-None-Match": cached[0]} if cached else {})
        if response.status_code == 304 and cached:
            data, next_url = cached[1]
            return data, next_url
        if response.status_code in (403, 429):
            raise ValueError(
                "GitHub denied access or rate limited the request; "
                f"remaining={response.headers.get('x-ratelimit-remaining', 'unknown')}, "
                f"reset={response.headers.get('x-ratelimit-reset', 'unknown')}, "
                f"retry-after={response.headers.get('retry-after', 'unknown')}"
            )
        if response.status_code != 200:
            raise ValueError(f"GitHub API returned HTTP {response.status_code}")
        data = response.json()
        next_url = response.links.get("next", {}).get("url")
        if etag := response.headers.get("etag"):
            self.cache[url] = etag, (data, next_url)
        return data, next_url

    def repository(self, name: str) -> dict:
        data, _ = self.get(f"https://api.github.com/repos/{repository_name(name)}")
        return data

    def releases(self, name: str) -> list[dict]:
        url = f"https://api.github.com/repos/{repository_name(name)}/releases?per_page=100"
        releases = {}
        visited = set()
        while url:
            if url in visited:
                raise ValueError("Repeated GitHub pagination URL")
            visited.add(url)
            data, url = self.get(url)
            if not isinstance(data, list):
                raise ValueError("Invalid releases response")
            for release in data:
                releases[release["id"]] = release
        return list(releases.values())
