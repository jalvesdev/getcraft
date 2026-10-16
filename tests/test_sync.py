import copy
import hashlib
import json

import httpx
import pytest
from typer.testing import CliRunner

from getcraft.archive import inspect, lock, rebuild
from getcraft.cli import app
from getcraft.config import save
from getcraft.download import Downloader
from getcraft.selection import plan_release
from getcraft.sync import build_plans, synchronize

BODY = b"installer"
DIGEST = hashlib.sha256(BODY).hexdigest()
PROJECT = {"owner": "storytold", "repo": "photocraft", "enabled": True}


@pytest.fixture
def config(tmp_path):
    return {
        "archive": {
            "path": str(tmp_path / "archive"),
            "keep_versions": 3,
            "include_prereleases": False,
        },
        "repositories": [copy.deepcopy(PROJECT)],
    }


def remote_asset(name="app-windows-x64.exe", id=1, body=BODY, digest=True):
    return {
        "id": id,
        "name": name,
        "size": len(body),
        "browser_download_url": f"https://github.com/storytold/photocraft/releases/download/v1/{name}",
        "digest": "sha256:" + hashlib.sha256(body).hexdigest() if digest else None,
    }


def release(assets=None, id=1):
    return {
        "id": id,
        "tag_name": f"v{id}.0",
        "published_at": "2026-01-01T00:00:00Z",
        "html_url": f"https://github.com/storytold/photocraft/releases/tag/v{id}.0",
        "assets": assets if assets is not None else [remote_asset()],
    }


def run_sync(config, root, response=None, data=None):
    plan = plan_release(config, PROJECT, data or release())
    with (
        lock(root),
        Downloader(
            httpx.MockTransport(response or (lambda r: httpx.Response(200, content=BODY)))
        ) as downloader,
    ):
        return synchronize(root, [plan], downloader)


def test_repeated_sync_and_repair(config, tmp_path):
    root = tmp_path / "archive"
    assert run_sync(config, root)[0]["status"] == "complete"
    rows, errors = inspect(root)
    assert not errors and rows[0]["status"] == "complete"
    report = run_sync(config, root, lambda r: pytest.fail("unnecessary download"))[0]
    assert report["reused"] == 1 and report["downloaded"] == 0
    path = root / "storytold/photocraft/v1.0/windows/x86_64/app-windows-x64.exe"
    path.write_bytes(b"corrupted")
    assert inspect(root)[0][0]["status"] == "partial"
    assert run_sync(config, root)[0]["downloaded"] == 1
    path.unlink()
    assert run_sync(config, root)[0]["downloaded"] == 1


def test_published_checksum_without_api_digest(config, tmp_path):
    checksum = f"{DIGEST}  app-windows-x64.exe\n".encode()
    data = release([remote_asset(digest=False), remote_asset("SHA256SUMS.txt", 2, checksum, False)])
    calls = []

    def response(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=checksum if request.url.path.endswith(".txt") else BODY)

    report = run_sync(config, tmp_path / "archive", response, data)[0]
    assert report["status"] == "complete"
    assert calls[0].endswith("SHA256SUMS.txt")
    manifest = json.loads(
        (tmp_path / "archive/storytold/photocraft/v1.0/manifest.json").read_text()
    )
    binary = next(a for a in manifest["assets"] if a["platform"] == "windows")
    assert binary["published_sha256"] == DIGEST
    assert binary["official_digest"] is None
    assert (
        run_sync(config, tmp_path / "archive", lambda r: pytest.fail("redownload"), data)[0][
            "reused"
        ]
        == 2
    )


def test_invalid_published_checksum(config, tmp_path):
    checksum = ("0" * 64 + "  app-windows-x64.exe\n").encode()
    data = release([remote_asset(digest=False), remote_asset("SHA256SUMS", 2, checksum)])
    report = run_sync(
        config,
        tmp_path / "archive",
        lambda r: httpx.Response(
            200, content=checksum if r.url.path.endswith("SHA256SUMS") else BODY
        ),
        data,
    )[0]
    assert report["status"] == "partial"
    assert not list((tmp_path / "archive").glob("**/*.exe"))
    assert report["failures"]


def test_missing_asset(config, tmp_path):
    report = run_sync(config, tmp_path / "archive", lambda r: httpx.Response(404))[0]
    assert report["status"] == "failed"
    assert inspect(tmp_path / "archive")[0][0]["status"] == "partial"


def test_inventory_rebuild(config, tmp_path):
    root = tmp_path / "archive"
    run_sync(config, root)
    (root / "inventory.json").write_text("broken")
    with lock(root):
        rows, errors = rebuild(root)
    assert rows and not errors
    assert json.loads((root / "inventory.json").read_text())["releases"][0]["status"] == "complete"
    (root / "inventory.json").unlink()
    assert len(rebuild(root)[0]) == 1


def test_multiple_platforms_and_policy(config, tmp_path):
    data = release(
        [
            remote_asset(),
            remote_asset("app-macos-universal.dmg", 2),
            remote_asset("app-linux-arm64.deb", 3),
        ]
    )
    report = run_sync(config, tmp_path / "archive", data=data)[0]
    assert report["status"] == "complete" and report["downloaded"] == 3
    plan = plan_release(config, {**PROJECT, "platforms": ["linux"], "formats": ["deb"]}, data)
    assert [a["platform"] for a in plan["assets"]] == ["linux"]
    assert plan["missing_platforms"] == []


def test_missing_platform_is_distinct_from_failed_download(config):
    plan = plan_release(config, PROJECT, release())
    assert plan["missing_platforms"] == ["linux", "macos"]
    assert not plan["unresolved"]


def test_ambiguity_and_rules(config):
    data = release([remote_asset(), remote_asset("mystery.zip", 2)])
    assert plan_release(config, PROJECT, data)["unresolved"]
    project = {**PROJECT, "include_assets": ["mystery.zip"]}
    included = plan_release(config, project, data)
    assert not included["unresolved"] and len(included["assets"]) == 2
    excluded = plan_release(config, {**project, "exclude_assets": ["*.zip"]}, data)
    assert not excluded["unresolved"] and len(excluded["assets"]) == 1
    assert plan_release(config, project, release([remote_asset("source.zip")]))["assets"] == []


def test_select_three_eligible_releases(config):
    class API:
        def releases(self, _):
            return [release([], 5), release(id=4), release(id=3), release(id=2), release(id=1)]

    plans, messages = build_plans(config, [PROJECT], API())
    assert [p["release_id"] for p in plans] == [4, 3, 2]
    assert messages


def test_remote_changed_preserves_archive(config, tmp_path):
    root = tmp_path / "archive"
    run_sync(config, root)
    path = root / "storytold/photocraft/v1.0/manifest.json"
    before = path.read_bytes()
    data = release([remote_asset(id=99)])
    report = run_sync(config, root, lambda r: pytest.fail("download on conflict"), data)[0]
    assert report["status"] == "failed"
    assert path.read_bytes() == before
    assert inspect(root)[0][0]["status"] == "complete"


def test_offline_cli(config, tmp_path, monkeypatch):
    root = tmp_path / "archive"
    run_sync(config, root)
    path = tmp_path / "config.toml"
    save(path, config)
    monkeypatch.setattr("getcraft.cli.GitHub", lambda: pytest.fail("network during verify"))
    runner = CliRunner()
    for args in [["verify"], ["verify", "--all"], ["status"]]:
        result = runner.invoke(app, ["--config", str(path), *args])
        assert result.exit_code == 0, result.output
    next(root.glob("**/*.exe")).write_bytes(b"bad")
    result = runner.invoke(app, ["--config", str(path), "verify", "--all"])
    assert result.exit_code == 1 and "size mismatch" in result.output


def test_dry_run_is_read_only(config, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save(path, config)

    class API:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def releases(self, _):
            return [release()]

    monkeypatch.setattr("getcraft.cli.GitHub", API)
    result = CliRunner().invoke(app, ["--config", str(path), "sync", "--all", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "9 bytes total selected" in result.output
    assert not (tmp_path / "archive").exists()


def test_excluded_assets_preserved(config, tmp_path):
    root = tmp_path / "archive"
    data = release([remote_asset(), remote_asset("app-macos-universal.dmg", 2)])
    run_sync(config, root, data=data)
    config["selection"] = {"exclude_assets": ["*.dmg"]}
    run_sync(config, root, lambda r: pytest.fail("redownload"), data)
    manifest = json.loads(next(root.glob("**/manifest.json")).read_text())
    assert len(manifest["assets"]) == 2
    assert next(root.glob("**/*.dmg")).read_bytes() == BODY


def test_manifest_write_failure_is_reported_and_preserves_files(config, tmp_path, monkeypatch):
    root = tmp_path / "archive"
    run_sync(config, root)
    before = next(root.glob("**/manifest.json")).read_bytes()
    monkeypatch.setattr(
        "getcraft.sync.atomic_json", lambda *a: (_ for _ in ()).throw(OSError("write failed"))
    )
    report = run_sync(config, root, lambda r: pytest.fail("redownload"))[0]
    assert report["status"] == "failed"
    assert next(root.glob("**/manifest.json")).read_bytes() == before
    assert next(root.glob("**/*.exe")).read_bytes() == BODY


def test_download_write_failure_preserves_previous_target(tmp_path, monkeypatch):
    from getcraft.download import official_sha256

    assert official_sha256("sha512:abc") is None
    target = tmp_path / "file.exe"
    target.write_bytes(b"bad")
    monkeypatch.setattr(
        "getcraft.download.os.replace", lambda *a: (_ for _ in ()).throw(OSError("write failed"))
    )
    with Downloader(httpx.MockTransport(lambda r: httpx.Response(200, content=BODY))) as downloader:
        with pytest.raises(OSError):
            downloader.fetch(
                {"url": remote_asset()["browser_download_url"], "size": len(BODY)},
                target,
                repair=True,
            )
    assert target.read_bytes() == b"bad"


def test_missing_and_invalid_manifest(config, tmp_path):
    root = tmp_path / "archive"
    run_sync(config, root)
    path = next(root.glob("**/manifest.json"))
    path.unlink()
    assert "Missing release manifest" in inspect(root)[1][0]
    path.write_text("[]")
    assert "Invalid manifest" in inspect(root)[1][0]


def test_same_size_corruption_offline(config, tmp_path):
    root = tmp_path / "archive"
    run_sync(config, root)
    next(root.glob("**/*.exe")).write_bytes(b"X" * len(BODY))
    assert "SHA-256 mismatch" in inspect(root)[0][0]["problems"][0]


def test_crash_after_publish_restarts_without_digest(config, tmp_path):
    root = tmp_path / "archive"
    data = release([remote_asset(digest=False)])
    # A pending manifest is the durable identity journal before the first publication.
    plan = plan_release(config, PROJECT, data)
    from getcraft.archive import atomic_json, safe

    atomic_json(safe(root, "storytold/photocraft/v1.0/manifest.json"), plan)
    path = safe(root, plan["assets"][0]["path"])
    path.parent.mkdir(parents=True)
    path.write_bytes(BODY)
    assert run_sync(config, root, data=data)[0]["status"] == "complete"


def test_manifest_path_traversal_and_symlink(config, tmp_path):
    root = tmp_path / "archive"
    run_sync(config, root)
    path = next(root.glob("**/manifest.json"))
    manifest = json.loads(path.read_text())
    manifest["assets"][0]["path"] = "../../outside/app-windows-x64.exe"
    path.write_text(json.dumps(manifest))
    assert inspect(root)[1]


def test_sync_cli_end_to_end(config, tmp_path, monkeypatch):
    from getcraft.download import Downloader as RealDownloader

    class API:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def releases(self, _):
            return [release()]

    monkeypatch.setattr("getcraft.cli.GitHub", API)
    monkeypatch.setattr(
        "getcraft.cli.Downloader",
        lambda: RealDownloader(httpx.MockTransport(lambda r: httpx.Response(200, content=BODY))),
    )
    path = tmp_path / "config.toml"
    save(path, config)
    runner = CliRunner()
    for args in [["sync"], ["sync", "--all"], ["sync", "--repo", "storytold/photocraft"]]:
        result = runner.invoke(app, ["--config", str(path), *args])
        assert result.exit_code == 0, result.output
    (tmp_path / "archive/inventory.json").write_text("corrupt")
    result = runner.invoke(app, ["--config", str(path), "verify", "--rebuild-inventory"])
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "archive/inventory.json").read_text())["schema_version"] == 1


def test_older_archived_releases_are_repaired_beyond_backfill_window(config, tmp_path):
    root = tmp_path / "archive"
    run_sync(config, root, data=release(id=1))

    class API:
        def releases(self, _):
            return [release(id=i) for i in [5, 4, 3, 2, 1]]

    plans, _ = build_plans(config, [PROJECT], API())
    assert [p["release_id"] for p in plans] == [5, 4, 3, 1]


def test_api_failure_preserves_backup(config, tmp_path, monkeypatch):
    root = tmp_path / "archive"
    run_sync(config, root)
    before = next(root.glob("**/manifest.json")).read_bytes()

    class API:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def releases(self, _):
            raise ValueError("GitHub rate limited")

    monkeypatch.setattr("getcraft.cli.GitHub", API)
    path = tmp_path / "config.toml"
    save(path, config)
    result = CliRunner().invoke(app, ["--config", str(path), "sync"])
    assert result.exit_code == 1
    assert next(root.glob("**/manifest.json")).read_bytes() == before
