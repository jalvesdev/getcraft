"""Synthetic archives only: destructive tests never use the operator's archive."""

import copy
import hashlib

import httpx
import pytest

from getcraft.archive import atomic_json, rebuild, safe
from getcraft.github import GitHub
from getcraft.selection import plan_release


@pytest.fixture
def archive_fixture(tmp_path):
    root = tmp_path / "archive"
    config = {
        "archive": {"path": str(root), "keep_versions": 3, "include_prereleases": False},
        "repositories": [{"owner": "storytold", "repo": "photocraft", "enabled": True}],
    }
    remote = []

    def add(number, names=None, **changes):
        names = names or ["app-windows-x64.exe", "app-linux-arm64.deb", "app-macos-universal.dmg"]
        release = {
            "id": number,
            "tag_name": f"v{number}.0",
            "draft": False,
            "prerelease": False,
            "published_at": f"2026-01-{number:02}T00:00:00Z",
            "html_url": f"https://github.com/storytold/photocraft/releases/tag/v{number}.0",
            "assets": [],
        }
        for index, name in enumerate(names):
            body = f"fixture {number} {name}".encode()
            release["assets"].append(
                {
                    "id": number * 100 + index,
                    "name": name,
                    "size": len(body),
                    "browser_download_url": f"https://github.com/storytold/photocraft/releases/download/v{number}.0/{name}",
                    "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
                }
            )
        release.update(changes)
        remote.append(release)
        manifest = plan_release(config, config["repositories"][0], release)
        for asset in manifest["assets"]:
            body = f"fixture {number} {asset['name']}".encode()
            path = safe(root, asset["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            asset.update(
                sha256=hashlib.sha256(body).hexdigest(),
                status="verified",
                archived_at="2026-01-16T00:00:00Z",
            )
        manifest.update(status="complete", archived_at="2026-01-16T00:00:00Z")
        atomic_json(
            safe(root, f"storytold/photocraft/{release['tag_name']}/manifest.json"), manifest
        )
        rebuild(root)
        return manifest

    def api(status=200):
        return GitHub(
            httpx.MockTransport(lambda request: httpx.Response(status, json=copy.deepcopy(remote)))
        )

    return root, config, remote, add, api
