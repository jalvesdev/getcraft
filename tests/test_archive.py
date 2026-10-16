import hashlib
import json
from unittest.mock import patch

import httpx
import pytest

from getcraft.archive import atomic_json, inspect, lock, safe, segment
from getcraft.download import Downloader, DownloadError, checksums

BODY = b"official installer fixture"
HASH = hashlib.sha256(BODY).hexdigest()


def asset(**changes):
    return {
        "url": "https://github.com/a/b/releases/download/v1/app-x64.exe",
        "size": len(BODY),
        "official_digest": f"sha256:{HASH}",
        **changes,
    }


def test_download(tmp_path):
    target = tmp_path / "app.exe"
    with Downloader(httpx.MockTransport(lambda r: httpx.Response(200, content=BODY))) as downloader:
        assert downloader.fetch(asset(), target) == HASH
    assert target.read_bytes() == BODY
    assert not target.with_suffix(".exe.part").exists()


class Interrupted(httpx.SyncByteStream):
    def __iter__(self):
        yield BODY[:3]
        raise httpx.ReadError("interrupted")


def test_interrupted_restart_and_retry(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        return (
            httpx.Response(200, stream=Interrupted())
            if len(calls) == 1
            else httpx.Response(200, content=BODY)
        )

    sleeps = []
    with Downloader(httpx.MockTransport(respond), sleep=sleeps.append) as downloader:
        assert downloader.fetch(asset(), tmp_path / "app.exe") == HASH
    assert len(calls) == 2 and sleeps == [1]
    assert all("range" not in request.headers for request in calls)


def test_interrupted_never_published(tmp_path):
    with Downloader(
        httpx.MockTransport(lambda r: httpx.Response(200, stream=Interrupted())),
        sleep=lambda _: None,
    ) as downloader:
        with pytest.raises(DownloadError, match="after retries"):
            downloader.fetch(asset(), tmp_path / "app.exe")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "change,body",
    [({"official_digest": "sha256:" + "0" * 64}, BODY), ({"size": 1}, BODY), ({"size": 999}, BODY)],
)
def test_bad_integrity(tmp_path, change, body):
    with Downloader(httpx.MockTransport(lambda r: httpx.Response(200, content=body))) as downloader:
        with pytest.raises(DownloadError):
            downloader.fetch(asset(**change), tmp_path / "app.exe")
    assert not (tmp_path / "app.exe").exists()


def test_no_space(tmp_path):
    with patch(
        "getcraft.download.shutil.disk_usage", return_value=type("Usage", (), {"free": 0})()
    ):
        with Downloader(httpx.MockTransport(lambda r: pytest.fail("network called"))) as downloader:
            with pytest.raises(DownloadError, match="space"):
                downloader.fetch(asset(), tmp_path / "app.exe")


def test_atomic_write_failure_preserves_old(tmp_path):
    path = tmp_path / "manifest.json"
    atomic_json(path, {"old": True})
    with patch("getcraft.archive.os.replace", side_effect=OSError("disk error")):
        with pytest.raises(OSError):
            atomic_json(path, {"new": True})
    assert json.loads(path.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "name", ["../evil", ".", "..", "/tmp/evil", "a\\b", "a:b", "x\n.exe", "CON", "x.", "x "]
)
def test_malicious_segments(name):
    with pytest.raises(ValueError):
        segment(name)


def test_symlinks(tmp_path):
    (tmp_path / "evil").symlink_to("/tmp", target_is_directory=True)
    with pytest.raises(ValueError):
        safe(tmp_path, "evil/file")


def test_concurrent_lock(tmp_path):
    with lock(tmp_path):
        with pytest.raises(ValueError, match="locked"):
            with lock(tmp_path):
                pytest.fail("second lock acquired")
    with lock(tmp_path):
        pass


def test_checksum_formats(tmp_path):
    path = tmp_path / "SHA256SUMS"
    path.write_text(f"{HASH}  app.exe\nSHA256 (app.dmg) = {HASH}\n{HASH}  ../evil\n")
    assert checksums(path) == {"app.exe": HASH, "app.dmg": HASH}
    path.write_text(f"{HASH}  app.exe\n" + "0" * 64 + "  app.exe\n")
    with pytest.raises(DownloadError, match="Conflicting"):
        checksums(path)


def test_bad_manifest_is_visible(tmp_path):
    path = tmp_path / "a/b/v1/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    rows, errors = inspect(tmp_path)
    assert rows == [] and errors


def test_untrusted_redirect(tmp_path):
    with Downloader(
        httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://localhost/evil"})
        )
    ) as downloader:
        with pytest.raises(DownloadError, match="untrusted"):
            downloader.fetch(asset(), tmp_path / "file")
