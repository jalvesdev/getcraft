import copy
import hashlib
import json

import httpx
from typer.testing import CliRunner

from getcraft.cli import app
from getcraft.config import load, save
from getcraft.download import Downloader
from getcraft.github import GitHub
from getcraft.planning import estimate
from getcraft.reports import collect
from getcraft.selection import plan_release

PROJECT = {"owner": "storytold", "repo": "photocraft", "enabled": True}


def source():
    bodies = {
        "app-linux-x86_64.rpm": b"linux rpm payload",
        "app-linux-arm64.rpm": b"ARM rpm payload",
        "app-linux-x86_64.deb": b"deb payload",
        "app-windows-x64.exe": b"windows payload",
        "app-macos-universal.dmg": b"mac payload",
        "app-linux-x86_64.rpm.sig": b"linux signature",
        "app-windows-x64.exe.sig": b"windows signature",
        "SHA256SUMS.txt": b"",
    }
    bodies["SHA256SUMS.txt"] = (
        hashlib.sha256(bodies["app-linux-x86_64.rpm"]).hexdigest() + "  app-linux-x86_64.rpm\n"
    ).encode()
    release = {
        "id": 1,
        "tag_name": "v1.0",
        "published_at": "2026-01-01T00:00:00Z",
        "html_url": "https://github.com/storytold/photocraft/releases/tag/v1.0",
        "assets": [
            {
                "id": i + 1,
                "name": n,
                "size": len(b),
                "digest": "sha256:" + hashlib.sha256(b).hexdigest(),
                "browser_download_url": "https://github.com/storytold/photocraft/releases/download/v1.0/"
                + n,
            }
            for i, (n, b) in enumerate(bodies.items())
        ],
    }
    return release, bodies


def fedora_config(path, root):
    config = load(path)
    config["archive"]["path"] = str(root)
    config["repositories"] = [copy.deepcopy(PROJECT)]
    config["selection"] = {
        "platforms": ["linux"],
        "architectures": ["x86_64"],
        "formats_by_platform": {"linux": ["rpm", "flatpak", "appimage"]},
    }
    save(path, config)
    return config


def test_check_sync_share_selection_estimates_and_metadata(tmp_path, monkeypatch):
    root, path = tmp_path / "archive", tmp_path / "config.toml"
    config = fedora_config(path, root)
    release, bodies = source()
    monkeypatch.setattr(
        "getcraft.cli.GitHub",
        lambda: GitHub(httpx.MockTransport(lambda r: httpx.Response(200, json=[release]))),
    )
    requests = []

    def download(request):
        name = request.url.path.rsplit("/", 1)[-1]
        requests.append(name)
        return httpx.Response(200, content=bodies[name])

    monkeypatch.setattr(
        "getcraft.cli.Downloader", lambda: Downloader(httpx.MockTransport(download))
    )
    runner = CliRunner()
    prefix = ["--config", str(path)]
    check = runner.invoke(app, [*prefix, "check", "--repo", "storytold/photocraft"])
    assert check.exit_code == 0, check.output
    assert "SELECTED app-linux-x86_64.rpm" in check.output
    assert "IGNORED app-windows-x64.exe" in check.output
    assert "IGNORED app-linux-arm64.rpm" in check.output
    assert "local=missing" in check.output and "Not published targets:" in check.output
    assert not root.exists()
    dry = runner.invoke(app, [*prefix, "sync", "--dry-run"])
    assert dry.exit_code == 0 and not requests and not root.exists()
    sync = runner.invoke(app, [*prefix, "sync"])
    assert sync.exit_code == 0, sync.output
    expected = {"app-linux-x86_64.rpm", "app-linux-x86_64.rpm.sig", "SHA256SUMS.txt"}
    assert set(requests) == expected
    plan = plan_release(config, PROJECT, release)
    assert estimate(root, plan)["download_bytes"] == 0
    assert estimate(root, plan)["reused_bytes"] == sum(len(bodies[n]) for n in expected)
    requests.clear()
    again = runner.invoke(app, [*prefix, "sync"])
    assert again.exit_code == 0, again.output
    assert requests == [] and "downloaded=0" in again.output
    next(root.glob("**/*.rpm")).write_bytes(b"bad")
    assert estimate(root, plan)["download_bytes"] == len(bodies["app-linux-x86_64.rpm"])


def test_preference_changes_do_not_reinterpret_historical_integrity(
    archive_fixture, tmp_path, monkeypatch
):
    root, config, _, add, _ = archive_fixture
    add(1)
    manifests = {p: p.read_bytes() for p in root.glob("**/manifest.json")}
    installers = {
        p: p.read_bytes() for p in root.glob("**/*") if p.suffix in {".exe", ".deb", ".dmg"}
    }
    config["selection"] = {
        "platforms": ["linux"],
        "architectures": ["arm64"],
        "formats_by_platform": {"linux": ["rpm"]},
    }
    path = tmp_path / "config.toml"
    save(path, config)
    monkeypatch.setattr(
        "getcraft.cli.GitHub",
        lambda: (_ for _ in ()).throw(AssertionError("offline command made HTTP request")),
    )
    runner = CliRunner()
    for command in [
        ["config", "show"],
        ["status"],
        ["verify", "--all"],
        ["report", "--format", "json"],
    ]:
        result = runner.invoke(app, ["--config", str(path), *command])
        assert result.exit_code == 0, result.output
        if command[0] == "status":
            assert "no_installers_selected" in result.output
        if command[0] == "report":
            release = json.loads(result.output)["projects"][0]["releases"][0]
            assert release["status"] == "complete"
            assert release["current_selection"]["state"] == "no_installers_selected"
            assert all(a["integrity"] == "verified" for a in release["assets"])
    assert all(p.read_bytes() == text for p, text in manifests.items())
    assert all(p.read_bytes() == data for p, data in installers.items())


def test_sync_narrower_preferences_preserves_existing_files(archive_fixture, tmp_path, monkeypatch):
    root, config, _, add, api = archive_fixture
    add(1)
    before = {p: p.read_bytes() for p in root.glob("**/*") if p.suffix in {".exe", ".deb", ".dmg"}}
    config["selection"] = {
        "platforms": ["linux"],
        "architectures": ["arm64"],
        "formats_by_platform": {"linux": ["deb"]},
    }
    path = tmp_path / "config.toml"
    save(path, config)
    monkeypatch.setattr("getcraft.cli.GitHub", api)
    monkeypatch.setattr(
        "getcraft.cli.Downloader",
        lambda: Downloader(
            httpx.MockTransport(
                lambda r: (_ for _ in ()).throw(AssertionError("unnecessary download"))
            )
        ),
    )
    result = CliRunner().invoke(app, ["--config", str(path), "sync"])
    assert result.exit_code == 0, result.output
    assert all(p.read_bytes() == data for p, data in before.items())
    data = collect(root, config)
    release = data["projects"][0]["releases"][0]
    assert release["status"] == "complete"
    assert len(release["assets"]) == 3
    assert sum(a["required"] for a in release["assets"]) == 1


def test_unknown_architecture_and_publication_states():
    release, _ = source()
    config = {
        "selection": {
            "platforms": ["linux"],
            "architectures": ["x86_64"],
            "formats_by_platform": {"linux": ["rpm", "flatpak"]},
        }
    }
    plan = plan_release(config, PROJECT, release)
    states = {r["format"]: r["state"] for r in plan["availability"]}
    assert states == {"rpm": "published", "flatpak": "not_published"}
    release["assets"] = [dict(release["assets"][0], name="app-linux.rpm")]
    plan = plan_release(config, PROJECT, release)
    assert not plan["assets"]
    assert plan["asset_decisions"][0]["decision"] == "ambiguous"
    assert plan["availability"][0]["state"] == "ambiguous"
    project = {**PROJECT, "include_assets": ["app-linux.rpm"]}
    assert len(plan_release(config, project, release)["assets"]) == 1


def test_estimate_is_read_only_and_reports_changed_identity(archive_fixture):
    root, config, remote, add, _ = archive_fixture
    add(1)
    plan = plan_release(config, config["repositories"][0], remote[0])
    path = next(root.glob("**/manifest.json"))
    original = path.read_bytes()
    assert estimate(root, plan)["download_bytes"] == 0
    plan["assets"][0]["id"] += 10000
    changed = estimate(root, plan)
    assert changed["problems"] and changed["assets"][0]["state"] == "manual_review"
    assert path.read_bytes() == original


def test_removed_repository_archives_still_support_status_and_report(archive_fixture, tmp_path):
    root, config, _, add, _ = archive_fixture
    add(1)
    config["repositories"] = []
    path = tmp_path / "config.toml"
    save(path, config)
    runner = CliRunner()
    for args in [["status"], ["report", "--format", "json"], ["verify", "--all"]]:
        result = runner.invoke(app, ["--config", str(path), *args])
        assert result.exit_code == 0, result.output
    data = collect(root, config)
    assert not data["projects"][0]["monitored"]
    assert data["projects"][0]["releases"][0]["status"] == "complete"
