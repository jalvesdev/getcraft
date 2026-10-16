import json
import shlex
from html.parser import HTMLParser
from urllib.parse import unquote

import pytest
from typer.testing import CliRunner

from getcraft.archive import atomic_json, read_manifest, safe
from getcraft.cli import app
from getcraft.config import save
from getcraft.reports import (
    backfill_readmes,
    collect,
    installation_readme,
    record_sync,
    render,
    write_readme,
    write_report,
)
from getcraft.retention import prepare, snapshot


@pytest.mark.parametrize("format", ["json", "markdown", "html"])
def test_reports_include_required_fields_and_offline_links(archive_fixture, format):
    root, config, _, add, _ = archive_fixture
    manifest = add(1)
    config["repositories"][0]["pinned_versions"] = ["v1.0"]
    record_sync(
        root,
        {
            "storytold/photocraft": {
                "latest": {"tag": "v2.0", "release_id": 2},
                "observed_at": "2026-10-16T00:00:00Z",
            }
        },
        [],
    )
    data = collect(root, config)
    project = data["projects"][0]
    assert project["latest_known"]["tag"] == "v2.0"
    assert project["last_sync"] and project["monitored"]
    assert project["bytes"] >= sum(a["size"] for a in manifest["assets"])
    assert data["total_bytes"] >= project["bytes"]
    assert project["releases"][0]["pinned"]
    output = render(data, format, root, root)
    assert "v2" in output
    if format == "json":
        assert json.loads(output) == data
    elif format == "html":

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
                self.tags = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                for key, value in attrs:
                    if key == "href" and not value.startswith("#"):
                        self.links.append(value)

        parser = Links()
        parser.feed(output)
        assert not {"script", "img", "link"} & set(parser.tags)
        assert len(parser.links) == 3
        assert all((root / unquote(link)).is_file() for link in parser.links)
    else:
        assert "app" in output and "](" in output


def test_installation_instructions_and_untrusted_filename_quoting(archive_fixture):
    root, config, _, add, _ = archive_fixture
    manifest = add(
        1,
        [
            "app-windows-x64.exe",
            "app-macos-universal.dmg",
            "app-linux-arm64.flatpak",
            "app-linux-arm64.flatpakref",
            "app-linux-arm64.AppImage",
            "app-linux-arm64.rpm",
            "app-linux-arm64-'; touch pwned; '.deb",
        ],
    )
    text = installation_readme(manifest)
    for phrase in [
        "Windows",
        "macOS",
        "Linux",
        "flatpak install --user",
        "chmod +x --",
        "dnf install",
        "apt install",
        "not a self-contained installer",
        "future OS versions",
        "not prove publisher authenticity",
        "not been independently verified",
    ]:
        assert phrase in text
    command = next(
        line.strip() for line in text.splitlines() if line.strip().startswith("apt install")
    )
    assert shlex.split(command)[2] == "./app-linux-arm64-'; touch pwned; '.deb"
    assert not (root / "pwned").exists()
    assert write_readme(root, manifest)
    atomic_json(safe(root, "storytold/photocraft/v1.0/manifest.json"), manifest)
    assert (root / "storytold/photocraft/v1.0/README.md").read_text() == text


def test_preserve_user_readme_and_modified_generated_readme(archive_fixture):
    root, _, _, add, _ = archive_fixture
    manifest = add(1)
    path = root / "storytold/photocraft/v1.0/README.md"
    path.write_text("user notes")
    assert not write_readme(root, manifest)
    assert path.read_text() == "user notes"
    path.unlink()
    assert write_readme(root, manifest)
    path.write_text("edited")
    assert not write_readme(root, manifest)
    assert path.read_text() == "edited"


def test_backfill_readmes_and_managed_retention(archive_fixture):
    root, config, _, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    assert backfill_readmes(root) == []
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    assert any(f["path"].endswith("/README.md") for f in plan["candidates"][0]["files"])
    assert backfill_readmes(root) == []


def test_html_injection_and_uri_escaping(archive_fixture):
    root, config, _, add, _ = archive_fixture
    manifest = add(1, ["app-linux-arm64-a#b%20.deb"])
    manifest["warnings"] = ["<script>alert(1)</script>"]
    atomic_json(safe(root, "storytold/photocraft/v1.0/manifest.json"), manifest)
    data = collect(root, config)
    text = render(data, "html", root, root)
    assert "<script>alert" not in text and "&lt;script&gt;" in text
    assert "a%23b%2520.deb" in text
    assert "javascript:" not in text


def test_reports_show_incomplete_and_unknown_latest(archive_fixture):
    root, config, _, add, _ = archive_fixture
    add(1)
    next(root.glob("**/*.exe")).write_bytes(b"bad")
    data = collect(root, config)
    project = data["projects"][0]
    assert project["latest_known"] is None
    assert project["releases"][0]["status"] == "partial"
    assert any(a["integrity"] != "verified" for a in project["releases"][0]["assets"])
    (root / "inventory.json").write_text("bad")
    assert collect(root, config)["projects"][0]["releases"]


def test_report_write_never_overwrites_unmanaged_files(archive_fixture):
    root, _, _, add, _ = archive_fixture
    add(1)
    (root / "catalog.html").write_text("user catalog")
    with pytest.raises(ValueError, match="unmanaged"):
        write_report(root, "catalog.html", "<html></html>")
    (root / "catalog.html").unlink()
    write_report(root, "catalog.html", "<html>first</html>")
    write_report(root, "catalog.html", "<html>second</html>")
    assert (root / "catalog.html").read_text() == "<html>second</html>"
    for name in [
        "inventory.json",
        "../outside",
        ".hidden",
        "storytold/photocraft/v1.0/manifest.json",
    ]:
        with pytest.raises(ValueError):
            write_report(root, name, "bad")


def test_report_cli_and_read_only_simulation(archive_fixture, tmp_path, monkeypatch):
    root, config, _, add, _ = archive_fixture
    add(1)
    path = tmp_path / "config.toml"
    save(path, config)
    monkeypatch.setattr("getcraft.cli.GitHub", lambda: pytest.fail("report made HTTP request"))
    runner = CliRunner()
    before = snapshot(root)
    result = runner.invoke(app, ["--config", str(path), "report", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["projects"]
    result = runner.invoke(
        app,
        [
            "--config",
            str(path),
            "report",
            "--format",
            "html",
            "--output",
            "catalog.html",
            "--write-readmes",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert snapshot(root) == before
    assert not (root / "catalog.html").exists()
    result = runner.invoke(
        app,
        [
            "--config",
            str(path),
            "report",
            "--format",
            "html",
            "--output",
            "catalog.html",
            "--write-readmes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (root / "catalog.html").exists()
    manifest = read_manifest(next(root.glob("storytold/**/manifest.json")))
    assert manifest["readme_sha256"]


def test_sync_automatically_generates_managed_readme(archive_fixture, tmp_path, monkeypatch):
    import httpx

    from getcraft.download import Downloader

    root, config, remote, add, api = archive_fixture
    manifest = add(1)
    path = tmp_path / "config.toml"
    save(path, config)
    monkeypatch.setattr("getcraft.cli.GitHub", api)
    monkeypatch.setattr(
        "getcraft.cli.Downloader",
        lambda: Downloader(httpx.MockTransport(lambda r: pytest.fail("redownload"))),
    )
    result = CliRunner().invoke(app, ["--config", str(path), "sync"])
    assert result.exit_code == 0, result.output
    manifest = read_manifest(next(root.glob("storytold/**/manifest.json")))
    assert manifest["readme_sha256"]
    knowledge = json.loads((root / ".getcraft/knowledge.json").read_text())
    assert knowledge["projects"]["storytold/photocraft"]["latest"]["tag"] == "v1.0"


@pytest.mark.parametrize(
    "contents", ["{bad", "[]", '{"schema_version":1,"projects":{"a/b":{"latest":"bad"}}}']
)
def test_corrupt_known_metadata_is_reported_not_invented(archive_fixture, contents):
    root, config, _, add, _ = archive_fixture
    add(1)
    path = root / ".getcraft/knowledge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    data = collect(root, config)
    assert data["problems"]
    assert data["projects"][0]["latest_known"] is None
    for format in ["html", "markdown", "json"]:
        assert render(data, format, root, root)


def test_no_reported_sync_date_is_invented_for_m2_archive(archive_fixture):
    root, config, _, add, _ = archive_fixture
    add(1)
    project = collect(root, config)["projects"][0]
    assert project["last_sync"] is None
    assert project["latest_archive_time"]


def test_report_shows_sync_failure_even_when_preserved_backup_is_intact(archive_fixture):
    root, config, _, add, _ = archive_fixture
    add(1)
    record_sync(
        root,
        {"storytold/photocraft": {"latest": {"tag": "v1.0", "release_id": 1}}},
        [
            {
                "repository": "storytold/photocraft",
                "tag": "v1.0",
                "status": "failed",
                "failures": ["remote asset identity changed"],
            }
        ],
    )
    data = collect(root, config)
    assert data["projects"][0]["releases"][0]["status"] == "complete"
    for format in ["json", "markdown", "html"]:
        assert "identity changed" in render(data, format, root, root)


def test_report_warns_about_corrupt_index_without_losing_catalog(archive_fixture):
    root, config, _, add, _ = archive_fixture
    add(1)
    (root / "inventory.json").write_text("broken")
    data = collect(root, config)
    assert any("Inventory unreadable" in problem for problem in data["problems"])
    assert data["projects"][0]["releases"][0]["status"] == "complete"
