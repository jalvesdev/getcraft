import json

import pytest
from typer.testing import CliRunner

from getcraft.archive import atomic_json, rebuild
from getcraft.cli import app
from getcraft.config import load, save
from getcraft.retention import apply, prepare, snapshot


def fill(fixture, count=5):
    root, config, remote, add, api = fixture
    for i in range(1, count + 1):
        add(i)
    return root, config, remote, add, api


def test_retains_three_releases_not_installer_count(archive_fixture):
    root, config, _, _, api = fill(archive_fixture)
    before = snapshot(root)
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    assert [c["tag"] for c in plan["candidates"]] == ["v2.0", "v1.0"]
    assert len(plan["kept"]) == 3
    assert all(len(c["files"]) == 4 for c in plan["candidates"])
    assert snapshot(root) == before
    assert not (root / ".getcraft.lock").exists()
    with api() as github:
        result = apply(root, config, config["repositories"], plan, github)
    assert result["removed_releases"] == 2
    assert sorted(p.name for p in (root / "storytold/photocraft").iterdir()) == [
        "v3.0",
        "v4.0",
        "v5.0",
    ]
    audit = json.loads((root / result["audit"]).read_text())
    assert audit["status"] == "complete" and len(audit["removed"]) == 8
    with api() as github:
        again = prepare(root, config, config["repositories"], github)
    assert again["candidates"] == []


def test_pins_are_additional_to_window(archive_fixture):
    root, config, _, _, api = fill(archive_fixture)
    config["repositories"][0]["pinned_versions"] = ["v1.0"]
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    assert [c["tag"] for c in plan["candidates"]] == ["v2.0"]
    assert any(k["tag"] == "v1.0" and k["reason"] == "pinned" for k in plan["kept"])


def test_individual_limit(archive_fixture):
    root, config, _, _, api = fill(archive_fixture)
    config["repositories"][0]["keep_versions"] = 4
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    assert [c["tag"] for c in plan["candidates"]] == ["v1.0"]


@pytest.mark.parametrize("change", ["partial", "corrupt", "missing"])
def test_incomplete_and_verification_failures_block_pruning(archive_fixture, change):
    root, config, _, _, api = fill(archive_fixture)
    path = root / "storytold/photocraft/v5.0/manifest.json"
    if change == "partial":
        manifest = json.loads(path.read_text())
        manifest["status"] = "partial"
        atomic_json(path, manifest)
    else:
        asset = next((path.parent / "windows").rglob("*.exe"))
        asset.unlink() if change == "missing" else asset.write_bytes(b"corrupted")
    rebuild(root)
    with api() as github:
        assert prepare(root, config, config["repositories"], github)["candidates"] == []


@pytest.mark.parametrize("contents", [None, "{broken", "[]", "{}"])
def test_inventory_must_be_present_and_valid(archive_fixture, contents):
    root, config, _, _, api = fill(archive_fixture)
    path = root / "inventory.json"
    path.unlink() if contents is None else path.write_text(contents)
    with api() as github, pytest.raises(ValueError):
        prepare(root, config, config["repositories"], github)
    assert (root / "storytold/photocraft/v1.0").exists()


def test_api_unavailable_plan_and_apply(archive_fixture):
    root, config, _, _, api = fill(archive_fixture)
    with api(503) as github, pytest.raises(ValueError):
        prepare(root, config, config["repositories"], github)
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    with api(503) as github, pytest.raises(ValueError):
        apply(root, config, config["repositories"], plan, github)
    assert (root / "storytold/photocraft/v1.0").exists()


@pytest.mark.parametrize("unknown", ["notes.txt", "empty-directory"])
def test_unknown_files_and_directories_preserved(archive_fixture, unknown):
    root, config, _, _, api = fill(archive_fixture)
    path = root / "storytold/photocraft/v1.0" / unknown
    path.mkdir() if unknown == "empty-directory" else path.write_text("unmanaged")
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    assert "v1.0" not in [c["tag"] for c in plan["candidates"]]
    with api() as github:
        apply(root, config, config["repositories"], plan, github)
    assert path.exists()


def test_unknown_release_directory_blocks(archive_fixture):
    root, config, _, _, api = fill(archive_fixture)
    (root / "storytold/photocraft/unknown").mkdir()
    with api() as github, pytest.raises(ValueError, match="manifest"):
        prepare(root, config, config["repositories"], github)


def test_symlink_and_malicious_path(archive_fixture, tmp_path):
    root, config, _, _, api = fill(archive_fixture)
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    (root / "storytold/photocraft/v1.0/link").symlink_to(outside)
    with api() as github, pytest.raises(ValueError, match="Symlink"):
        prepare(root, config, config["repositories"], github)
    (root / "storytold/photocraft/v1.0/link").unlink()
    path = root / "storytold/photocraft/v1.0/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["assets"][0]["path"] = "../../outside"
    atomic_json(path, manifest)
    with api() as github, pytest.raises(ValueError):
        prepare(root, config, config["repositories"], github)
    assert outside.read_text() == "preserve"


@pytest.mark.parametrize("mutation", ["file", "pin", "new_file", "remote"])
def test_changes_between_plan_and_apply_abort(archive_fixture, mutation):
    root, config, remote, _, api = fill(archive_fixture)
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    if mutation == "file":
        path = next(root.glob("**/*.exe"))
        path.write_bytes(b"corrupt")
    elif mutation == "pin":
        config["repositories"][0]["pinned_versions"] = ["v1.0"]
    elif mutation == "new_file":
        (root / "new-file").write_text("preserve")
    else:
        remote[0]["html_url"] += "?changed"
    with api() as github, pytest.raises(ValueError):
        apply(root, config, config["repositories"], plan, github)
    assert (root / "storytold/photocraft/v1.0").exists()


def test_prereleases_never_replace_stable_backups(archive_fixture):
    root, config, remote, _, api = fill(archive_fixture)
    remote[-1]["prerelease"] = True
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    assert [c["tag"] for c in plan["candidates"]] == ["v1.0"]


def test_loss_of_platform_coverage_blocks_deletion(archive_fixture):
    root, config, _, add, api = archive_fixture
    add(1)
    for number in [2, 3, 4]:
        add(number, ["app-linux-arm64.deb"])
    with api() as github:
        assert prepare(root, config, config["repositories"], github)["candidates"] == []


def test_prune_cli_defaults_to_simulation_and_requires_confirmation(
    archive_fixture, tmp_path, monkeypatch
):
    root, config, _, _, api = fill(archive_fixture)
    path = tmp_path / "config.toml"
    save(path, config)
    monkeypatch.setattr("getcraft.cli.GitHub", api)
    runner = CliRunner()
    before = snapshot(root)
    for args in [[], ["--all", "--dry-run"], ["--repo", "storytold/photocraft", "--dry-run"]]:
        result = runner.invoke(app, ["--config", str(path), "prune", *args])
        assert result.exit_code == 0, result.output
    assert snapshot(root) == before
    assert not (root / ".getcraft.lock").exists()
    result = runner.invoke(app, ["--config", str(path), "prune", "--apply"], input="n\n")
    assert result.exit_code != 0
    assert snapshot(root) == before
    result = runner.invoke(app, ["--config", str(path), "prune", "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Removed 2 releases" in result.output


def test_pin_cli(archive_fixture, tmp_path):
    root, config, _, _, _ = archive_fixture
    path = tmp_path / "config.toml"
    save(path, config)
    runner = CliRunner()
    prefix = ["--config", str(path)]
    assert (
        runner.invoke(app, [*prefix, "pin", "storytold/photocraft", "v1.0", "--dry-run"]).exit_code
        == 0
    )
    assert not root.exists()
    assert runner.invoke(app, [*prefix, "pin", "storytold/photocraft", "v1.0"]).exit_code == 0
    assert "v1.0" in runner.invoke(app, [*prefix, "pins"]).output
    assert load(path)["repositories"][0]["pinned_versions"] == ["v1.0"]
    assert runner.invoke(app, [*prefix, "unpin", "storytold/photocraft", "v1.0"]).exit_code == 0
    assert load(path)["repositories"][0]["pinned_versions"] == []


def test_audit_write_failure_happens_before_any_delete(archive_fixture, monkeypatch):
    root, config, _, _, api = fill(archive_fixture)
    with api() as github:
        plan = prepare(root, config, config["repositories"], github)
    monkeypatch.setattr(
        "getcraft.retention.atomic_json",
        lambda *args: (_ for _ in ()).throw(OSError("write failed")),
    )
    with api() as github, pytest.raises(OSError):
        apply(root, config, config["repositories"], plan, github)
    assert (root / "storytold/photocraft/v1.0").exists()
