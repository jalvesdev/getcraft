"""TUI adapters exercise existing archive protections, never production data."""

from threading import Event

import pytest

from getcraft.archive import safe
from getcraft.config import load, save
from getcraft.configuration_commands import edit_load
from getcraft.tui import services


def setup_config(tmp_path, data):
    path = tmp_path / "tui.toml"
    save(path, data)
    return path


def test_preferences_reject_concurrent_changes(tmp_path, archive_fixture):
    root, data, remote, add, api = archive_fixture
    path = setup_config(tmp_path, data)
    edited, baseline = edit_load(path)
    save(path, {**data, "selection": {"platforms": ["windows"]}})
    edited["selection"] = {"platforms": ["linux"]}
    with pytest.raises(ValueError, match="changed"):
        services.save_settings(path, edited, baseline)
    assert load(path)["selection"]["platforms"] == ["windows"]


def test_prune_plan_stale_config_cannot_apply(tmp_path, archive_fixture, monkeypatch):
    root, data, remote, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    path = setup_config(tmp_path, data)
    monkeypatch.setattr(services, "GitHub", api)
    preview = services.preview_operation(path, "retention")
    assert preview["actionable"] and "v1.0" in preview["text"]
    data["repositories"][0]["pinned_versions"] = ["v1.0"]
    save(path, data)
    with pytest.raises(ValueError, match="changed"):
        services.apply_operation(path, "retention", preview, Event(), lambda _: None)
    assert safe(root, "storytold/photocraft/v1.0/manifest.json").exists()


def test_confirmed_prune_uses_existing_service_only_in_temporary_archive(
    tmp_path, archive_fixture, monkeypatch
):
    root, data, remote, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    path = setup_config(tmp_path, data)
    monkeypatch.setattr(services, "GitHub", api)
    preview = services.preview_operation(path, "retention")
    result = services.apply_operation(path, "retention", preview, Event(), lambda _: None)
    assert "Removed 1 releases" in result
    assert not safe(root, "storytold/photocraft/v1.0/manifest.json").exists()
    assert safe(root, "storytold/photocraft/v4.0/manifest.json").exists()


def test_changed_archive_blocks_tui_prune(tmp_path, archive_fixture, monkeypatch):
    root, data, remote, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    path = setup_config(tmp_path, data)
    monkeypatch.setattr(services, "GitHub", api)
    preview = services.preview_operation(path, "retention")
    (root / "unknown.txt").write_text("keep")
    with pytest.raises(ValueError):
        services.apply_operation(path, "retention", preview, Event(), lambda _: None)
    assert safe(root, "storytold/photocraft/v1.0/manifest.json").exists()


def test_repo_preferences_keep_archives_and_restore_globals(tmp_path, archive_fixture):
    from getcraft.preferences import policy

    root, data, remote, add, api = archive_fixture
    add(1)
    before = {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".getcraft.lock"
    }
    path = setup_config(tmp_path, data)
    edited, baseline = edit_load(path)
    edited["selection"] = {"platforms": ["linux"]}
    edited["repositories"][0]["platforms"] = ["windows"]
    services.save_settings(path, edited, baseline)
    result = load(path)
    assert policy(result, result["repositories"][0])["platforms"] == ["windows"]
    assert before == {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".getcraft.lock"
    }


def test_sync_cancelled_before_start_has_no_download(tmp_path, archive_fixture, monkeypatch):
    root, data, remote, add, api = archive_fixture
    add(1)
    path = setup_config(tmp_path, data)
    monkeypatch.setattr(services, "GitHub", api)
    preview = services.preview_operation(path, "sync")
    cancel = Event()
    cancel.set()
    assert "no files downloaded" in services.apply_operation(
        path, "sync", preview, cancel, lambda _: None
    )


def test_archive_path_edit_preserves_original_archive(tmp_path, archive_fixture):
    root, data, remote, add, api = archive_fixture
    add(1)
    before = {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".getcraft.lock"
    }
    path = setup_config(tmp_path, data)
    edited, baseline = edit_load(path)
    edited["archive"]["path"] = str(tmp_path / "other")
    services.save_settings(path, edited, baseline)
    assert before == {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".getcraft.lock"
    }


def test_sync_preview_api_failure_does_not_write_archive(tmp_path, archive_fixture, monkeypatch):
    root, data, remote, add, api = archive_fixture
    add(1)
    before = {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".getcraft.lock"
    }
    path = setup_config(tmp_path, data)
    monkeypatch.setattr(services, "GitHub", lambda: api(503))
    with pytest.raises(ValueError):
        services.preview_operation(path, "sync")
    assert before == {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != ".getcraft.lock"
    }


def test_pin_changed_while_waiting_for_retention_lock_blocks_deletion(
    tmp_path, archive_fixture, monkeypatch
):
    import getcraft.retention

    root, data, remote, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    path = setup_config(tmp_path, data)
    monkeypatch.setattr(services, "GitHub", api)
    preview = services.preview_operation(path, "retention")
    real_apply = getcraft.retention.apply

    def concurrent(*args):
        updated = load(path)
        updated["repositories"][0]["pinned_versions"] = ["v1.0"]
        save(path, updated)
        return real_apply(*args)

    monkeypatch.setattr(getcraft.retention, "apply", concurrent)
    with pytest.raises(ValueError, match="Configuration changed"):
        services.apply_operation(path, "retention", preview, Event(), lambda _: None)
    assert safe(root, "storytold/photocraft/v1.0/manifest.json").exists()
