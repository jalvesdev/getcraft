import json

import httpx
import pytest
from typer.testing import CliRunner

from getcraft.cli import app
from getcraft.config import load, save
from getcraft.github import GitHub, repository_name
from getcraft.selection import classify, ordered
from getcraft.storage import inventory, state


@pytest.mark.parametrize("name", ["../x", "a/..", "https://evil.com/a/b", "a/b?token=x", "a/b/c"])
def test_invalid_repository(name):
    with pytest.raises(ValueError):
        repository_name(name)


def test_pagination_etag():
    calls = []

    def respond(request):
        calls.append(request)
        if request.headers.get("if-none-match"):
            return httpx.Response(304)
        if "page=2" in str(request.url):
            return httpx.Response(200, json=[{"id": 2}])
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={
                "etag": "test",
                "link": '<https://api.github.com/repos/a/b/releases?page=2>; rel="next"',
            },
        )

    with GitHub(httpx.MockTransport(respond)) as github:
        assert github.releases("a/b") == [{"id": 1}, {"id": 2}]
        assert github.releases("a/b") == [{"id": 1}, {"id": 2}]
    assert len(calls) == 4


@pytest.mark.parametrize("code", [403, 404, 429, 500])
def test_http_errors(code):
    with GitHub(httpx.MockTransport(lambda r: httpx.Response(code))) as github:
        with pytest.raises(ValueError):
            github.repository("a/b")


def test_untrusted_pagination():
    with GitHub(
        httpx.MockTransport(
            lambda r: httpx.Response(
                200, json=[], headers={"link": '<https://evil.com/releases>; rel="next"'}
            )
        )
    ) as github:
        with pytest.raises(ValueError, match="non-GitHub"):
            github.releases("a/b")


def release(id, tag, **kwargs):
    return {"id": id, "tag_name": tag, "published_at": f"2026-01-{id:02}T00:00:00Z", **kwargs}


def test_ordering():
    rows = [
        release(1, "v1.9"),
        release(2, "v1.10"),
        release(3, "v2.0rc1"),
        release(4, "v3", draft=True),
    ]
    assert [r["id"] for r in ordered(rows)[0]] == [2, 1]
    assert [r["id"] for r in ordered(rows, True)[0]] == [3, 2, 1]
    rows.append(release(5, "nightly"))
    result, warnings = ordered(rows)
    assert result[0]["id"] == 5 and warnings


@pytest.mark.parametrize(
    "name,platform,arch",
    [
        ("app-win64-x64.exe", "windows", "x86_64"),
        ("app-macos-arm64.dmg", "macos", "arm64"),
        ("app-linux-amd64.AppImage", "linux", "x86_64"),
        ("app-universal.pkg", "macos", "universal"),
        ("unknown.zip", "unknown", "unknown"),
        ("../evil.exe", "unknown", "unknown"),
        ("SHA256SUMS", "metadata", "unknown"),
        ("source.tar.gz", "source", "unknown"),
    ],
)
def test_classification(name, platform, arch):
    assert classify(name)[:2] == (platform, arch)


def test_flatpak_warning():
    assert "pointer" in classify("app.flatpakref")[2]


def test_registry_and_check(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "getcraft.cli.GitHub",
        lambda: GitHub(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=(
                        [release(1, "v1.0", assets=[{"name": "app-x64.exe"}])]
                        if "/releases" in request.url.path
                        else {"full_name": "storytold/photocraft"}
                    ),
                )
            )
        ),
    )
    runner = CliRunner()
    path = tmp_path / "config.toml"

    def run(*args):
        return runner.invoke(app, ["--config", str(path), *args])

    assert run("repo", "add", "storytold/photocraft", "--dry-run").exit_code == 0
    assert not path.exists()
    assert run("repo", "add", "https://github.com/storytold/photocraft").exit_code == 0
    assert run("repo", "add", "Storytold/PhotoCraft").exit_code == 1
    assert "enabled" in run("repo", "list").output
    assert "local=missing" in run("check").output
    assert run("repo", "disable", "storytold/photocraft").exit_code == 0
    assert run("check", "--repo", "storytold/photocraft").exit_code == 1
    assert run("repo", "enable", "storytold/photocraft").exit_code == 0
    assert run("repo", "remove", "storytold/photocraft", "--dry-run").exit_code == 0
    assert len(load(path)["repositories"]) == 1
    assert run("repo", "remove", "storytold/photocraft").exit_code == 0
    assert load(path)["repositories"] == []
    assert run("status").exit_code == 0


def test_inventory(tmp_path):
    assert inventory(tmp_path) == []
    row = {"repository": "a/b", "release_id": 123, "status": "partial"}
    (tmp_path / "inventory.json").write_text(json.dumps({"schema_version": 1, "releases": [row]}))
    assert state(inventory(tmp_path), "a/b", 123) == "partial"
    assert state(inventory(tmp_path), "a/b", 124) == "missing"
    (tmp_path / "inventory.json").write_text("{}")
    with pytest.raises(ValueError):
        inventory(tmp_path)


def test_preserve_overrides(tmp_path):
    path = tmp_path / "config.toml"
    data = load(path)
    data["repositories"] = [{"owner": "a", "repo": "b", "platforms": ["linux"], "keep_versions": 2}]
    save(path, data)
    assert load(path) == data


def test_auxiliary_assets():
    assert classify("app-linux-x64.AppImage.zsync")[0] == "metadata"
    assert classify("app-windows-x64.wixpdb")[0] == "metadata"


@pytest.mark.parametrize(
    "contents",
    [
        "[archive]\nkeep_versions = 0",
        '[archive]\ninclude_prereleases = "yes"',
        '[[repositories]]\nowner = "a"\nrepo = "../b"',
        '[[repositories]]\nowner = "a"\nrepo = "b"\n[[repositories]]\nowner = "A"\nrepo = "B"',
    ],
)
def test_invalid_config(tmp_path, contents):
    path = tmp_path / "config.toml"
    path.write_text(contents)
    with pytest.raises(ValueError):
        load(path)
