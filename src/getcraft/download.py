"""Bounded streaming downloads. Never execute assets or trust local hashes as provenance."""

import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


class DownloadCancelled(ValueError):
    """Cooperative cancellation; validated existing files are preserved."""


class DownloadError(ValueError):
    """A download did not pass validation."""


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def official_sha256(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("sha256:"):
        return None
    digest = value[7:]
    if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise DownloadError("Malformed official SHA-256 digest")
    return digest.lower()


def valid_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
            "github-releases.githubusercontent.com",
        }
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise DownloadError("Refusing untrusted asset URL")


def checksums(path: Path) -> dict[str, str]:
    """Recognize exact GNU/BSD SHA256 lines; no path expansion or shell parsing."""
    if path.stat().st_size > 8 * 1024 * 1024:
        raise DownloadError("Checksum file exceeds 8 MiB parsing limit")
    result = {}
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise DownloadError("Checksum file is not UTF-8") from error
    for line in text.splitlines():
        match = re.fullmatch(r"([a-fA-F0-9]{64}) [ *](.+)", line)
        bsd = re.fullmatch(r"SHA256 \((.+)\) = ([a-fA-F0-9]{64})", line)
        if match:
            digest, name = match.groups()
        elif bsd:
            name, digest = bsd.groups()
        else:
            continue
        # Entries containing paths are not interpreted; only original basenames match.
        if "/" in name or "\\" in name or name in {".", ".."}:
            continue
        digest = digest.lower()
        if name in result and result[name] != digest:
            raise DownloadError("Conflicting published SHA-256 checksums")
        result[name] = digest
    return result


class Downloader:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        attempts: int = 3,
        sleep=time.sleep,
        cancel=None,
        progress=None,
    ):
        self.client = httpx.Client(
            timeout=httpx.Timeout(60, connect=15),
            transport=transport,
            headers={"Accept-Encoding": "identity"},
        )
        self.attempts = attempts
        self.sleep = sleep
        self.cancel = cancel
        self.progress = progress

    def check_cancelled(self):
        if self.cancel is not None and self.cancel.is_set():
            raise DownloadCancelled("Download cancelled safely")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def fetch(
        self, asset: dict, target: Path, expected: str | None = None, repair: bool = False
    ) -> str:
        self.check_cancelled()
        if target.is_symlink() or target.with_name(target.name + ".part").is_symlink():
            raise DownloadError("Refusing symlink destination")
        valid_url(asset["url"])
        size = asset["size"]
        if type(size) is not int or size < 0:
            raise DownloadError("Invalid asset size")
        digest = official_sha256(asset.get("official_digest"))
        if digest and expected and digest != expected:
            raise DownloadError("Official digest conflicts with published checksum")
        expected = expected or digest
        if target.exists():
            if expected and target.stat().st_size == size and sha256(target) == expected:
                return expected
            if not repair:
                raise DownloadError(
                    "Existing file requires manifest-backed repair; refusing overwrite"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        for attempt in range(self.attempts):
            self.check_cancelled()
            if shutil.disk_usage(target.parent).free < size + 1024 * 1024:
                raise DownloadError("Insufficient disk space")
            try:
                url = asset["url"]
                for redirect in range(6):
                    valid_url(url)
                    self.check_cancelled()
                    with self.client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = str(response.url.join(response.headers["location"]))
                            continue
                        if response.status_code in (403, 429):
                            raise DownloadError("Asset rate limited or forbidden; retry later")
                        if response.status_code >= 500:
                            raise httpx.HTTPStatusError(
                                "Transient server error",
                                request=response.request,
                                response=response,
                            )
                        if response.status_code != 200:
                            raise DownloadError(f"Asset HTTP {response.status_code}")
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise DownloadError("Unexpected content encoding")
                        count = 0
                        hash_value = hashlib.sha256()
                        # Always restart: no remote identity validated for Range resumption.
                        fd = os.open(
                            part,
                            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                            0o600,
                        )
                        with os.fdopen(fd, "wb") as stream:
                            for chunk in response.iter_bytes(1024 * 1024):
                                self.check_cancelled()
                                count += len(chunk)
                                if count > size:
                                    raise DownloadError("Asset exceeds declared size")
                                stream.write(chunk)
                                hash_value.update(chunk)
                                if self.progress:
                                    self.progress(dict(name=asset["name"], bytes=count, size=size))
                            stream.flush()
                            os.fsync(stream.fileno())
                        if count != size:
                            raise DownloadError("Asset size mismatch")
                        actual = hash_value.hexdigest()
                        if expected and actual != expected:
                            raise DownloadError("SHA-256 mismatch")
                        self.check_cancelled()
                        os.replace(part, target)
                        from getcraft.archive import fsync_directory

                        fsync_directory(target.parent)
                        return actual
                raise DownloadError("Too many asset redirects")
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt + 1 == self.attempts:
                    raise DownloadError("Network download failed after retries") from None
                if self.cancel is not None:
                    if self.cancel.wait(2**attempt):
                        self.check_cancelled()
                else:
                    self.sleep(2**attempt)
            finally:
                part.unlink(missing_ok=True)
        raise DownloadError("Download failed")
