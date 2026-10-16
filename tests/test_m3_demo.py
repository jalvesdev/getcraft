"""Repeatable M3 demonstration. All data is synthetic in pytest temporary directories."""

from typer.testing import CliRunner

from getcraft.cli import app
from getcraft.config import save
from getcraft.reports import record_sync
from getcraft.retention import snapshot


def test_m3_demo(archive_fixture, tmp_path, monkeypatch):
    root, config, _, add, api = archive_fixture
    for version in range(1, 6):
        add(version)
    config["repositories"][0]["pinned_versions"] = ["v1.0"]
    path = tmp_path / "demo.toml"
    save(path, config)
    record_sync(
        root,
        {
            "storytold/photocraft": {
                "latest": {"tag": "v6.0", "release_id": 6},
                "observed_at": "2026-10-16T00:00:00Z",
            }
        },
        [],
    )
    monkeypatch.setattr("getcraft.cli.GitHub", api)
    runner = CliRunner()
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
    before = snapshot(root)
    result = runner.invoke(
        app, ["--config", str(path), "prune", "--repo", "storytold/photocraft", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert snapshot(root) == before
    assert "Would remove storytold/photocraft v2.0" in result.output
    assert "Keep storytold/photocraft v1.0: pinned" in result.output
    print("\nM3 synthetic CLI demonstration (mocked HTTP; no real installers):\n" + result.output)
    print(f"Offline catalog: {root / 'catalog.html'}")
