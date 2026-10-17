"""Cancellation uses only synthetic data and temporary archives."""

import hashlib
from threading import Event

import httpx
import pytest

from getcraft.archive import inspect, safe
from getcraft.download import DownloadCancelled, Downloader
from getcraft.sync import synchronize


def test_cancel_before_download_does_not_touch_existing_file(tmp_path):
    target = tmp_path / "installer.exe"
    target.write_bytes(b"intact")
    token = Event()
    token.set()
    with Downloader(cancel=token) as downloader, pytest.raises(DownloadCancelled):
        downloader.fetch({}, target)
    assert target.read_bytes() == b"intact"
    assert not list(tmp_path.glob("*.part"))


def test_cancel_during_stream_cleans_part_and_preserves_original(tmp_path):
    token = Event()
    body = b"x" * (1024 * 1024 + 20)
    target = tmp_path / "installer.exe"
    target.write_bytes(b"previous")
    events = []

    def progress(item):
        events.append(item)
        token.set()

    asset = dict(
        name="installer.exe",
        size=len(body),
        url="https://github.com/o/r/releases/download/v1/installer.exe",
    )
    with (
        Downloader(
            httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
            cancel=token,
            progress=progress,
        ) as downloader,
        pytest.raises(DownloadCancelled),
    ):
        downloader.fetch(asset, target, repair=True)
    assert events[0]["bytes"] == 1024 * 1024
    assert target.read_bytes() == b"previous"
    assert not target.with_suffix(".exe.part").exists()


def test_progress_does_not_publish_until_validated(tmp_path):
    body = b"installer"
    target = tmp_path / "installer.exe"
    events = []

    def progress(item):
        assert not target.exists()
        events.append(item)

    asset = dict(
        name="installer.exe",
        size=len(body),
        url="https://github.com/o/r/releases/download/v1/installer.exe",
    )
    with Downloader(
        httpx.MockTransport(lambda request: httpx.Response(200, content=body)), progress=progress
    ) as downloader:
        assert downloader.fetch(asset, target) == hashlib.sha256(body).hexdigest()
    assert events == [dict(name="installer.exe", size=9, bytes=9)]


def test_cancelled_sync_journals_partial_and_can_retry(archive_fixture):
    root, config, remote, add, api = archive_fixture
    manifest = add(1)
    from getcraft.selection import plan_release

    plan = plan_release(config, config["repositories"][0], remote[0])
    for asset in manifest["assets"]:
        safe(root, asset["path"]).unlink()
    token = Event()

    def progress(item):
        token.set()

    with Downloader(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=f"fixture 1 {request.url.path.split('/')[-1]}".encode()
            )
        ),
        cancel=token,
        progress=progress,
    ) as downloader:
        result = synchronize(root, [plan], downloader)
    assert result[0]["status"] != "complete"
    assert any("cancelled" in item for item in result[0]["failures"])
    assert not list(root.rglob("*.part"))
    rows, errors = inspect(root)
    assert rows and not errors and rows[0]["status"] != "complete"
