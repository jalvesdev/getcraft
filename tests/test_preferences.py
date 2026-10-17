import copy
import json

import pytest
from typer.testing import CliRunner

from getcraft.cli import app
from getcraft.config import load, save
from getcraft.preferences import detect, policy
from getcraft.selection import plan_release


@pytest.mark.parametrize(
    "system,machine,distro,os_name,arch,formats",
    [
        ("Linux", "x86_64", {"ID": "fedora"}, "linux", "x86_64", ["appimage", "flatpak", "rpm"]),
        ("Windows", "AMD64", {}, "windows", "x86_64", ["exe", "msi", "msix", "msixbundle"]),
        ("Darwin", "arm64", {}, "macos", "arm64", ["dmg", "pkg"]),
        (
            "Linux",
            "aarch64",
            {"ID": "ubuntu", "ID_LIKE": "debian"},
            "linux",
            "arm64",
            ["appimage", "flatpak", "deb"],
        ),
    ],
)
def test_host_detection(monkeypatch, system, machine, distro, os_name, arch, formats):
    monkeypatch.setattr("getcraft.preferences.platform.system", lambda: system)
    monkeypatch.setattr("getcraft.preferences.platform.machine", lambda: machine)
    monkeypatch.setattr("getcraft.preferences.platform.freedesktop_os_release", lambda: distro)
    result = detect()
    assert result["platform"] == os_name and result["architecture"] == arch
    assert result["suggested"]["formats_by_platform"][os_name] == formats
    assert ("universal" in result["suggested"]["architectures"]) == (os_name == "macos")


def test_unknown_host_is_not_guessed(monkeypatch):
    monkeypatch.setattr("getcraft.preferences.platform.system", lambda: "Unknown")
    monkeypatch.setattr("getcraft.preferences.platform.machine", lambda: "weird")
    assert detect()["suggested"]["platforms"] == []
    assert detect()["architecture"] == "unknown"


def remote(name, id=1, size=100):
    return {
        "id": id,
        "name": name,
        "size": size,
        "browser_download_url": "https://github.com/a/b/releases/download/v1/" + name,
    }


def release(assets):
    return {"id": 1, "tag_name": "v1.0", "assets": assets}


PROJECT = {"owner": "a", "repo": "b"}


def test_fedora_selection_and_explanations():
    config = {
        "selection": {
            "platforms": ["linux"],
            "architectures": ["x86_64"],
            "formats_by_platform": {"linux": ["rpm", "flatpak", "appimage"]},
        }
    }
    names = [
        "app-linux-x86_64.rpm",
        "app-linux-x86_64.flatpak",
        "app-linux-x86_64.AppImage",
        "app-linux-x86_64.deb",
        "app-linux-arm64.rpm",
        "app-windows-x64.exe",
        "app-macos-universal.dmg",
        "app-linux.zip",
        "mystery.rpm",
        "SHA256SUMS.txt",
    ]
    plan = plan_release(config, PROJECT, release([remote(n, i) for i, n in enumerate(names)]))
    selected = {a["name"] for a in plan["assets"]}
    assert selected == set(names[:3] + ["SHA256SUMS.txt"])
    decisions = {d["name"]: d for d in plan["asset_decisions"]}
    assert decisions[names[3]]["reason"] == "format not selected for platform"
    assert decisions[names[4]]["reason"] == "architecture not selected"
    assert decisions[names[5]]["reason"] == "platform not selected"
    assert decisions["mystery.rpm"]["decision"] == "ambiguous"
    assert plan["selected_bytes"] == 400
    assert plan["missing_platforms"] == []


def test_multiple_platforms_and_universal():
    config = {
        "selection": {
            "platforms": ["windows", "macos"],
            "architectures": ["arm64", "universal"],
            "formats_by_platform": {"windows": ["msi"], "macos": ["dmg"]},
        }
    }
    assets = [
        remote("app-windows-arm64.msi", 1),
        remote("app-macos-universal.dmg", 2),
        remote("app-linux-arm64.rpm", 3),
        remote("app-macos-x64.dmg", 4),
    ]
    plan = plan_release(config, PROJECT, release(assets))
    assert len(plan["assets"]) == 2
    assert plan["missing_platforms"] == []


def test_repository_overrides_and_legacy_formats():
    config = {
        "platforms": {"linux": True, "windows": False, "macos": False},
        "selection": {"architectures": ["x86_64"], "formats_by_platform": {"linux": ["rpm"]}},
    }
    project = {**PROJECT, "architectures": ["arm64"], "formats_by_platform": {"linux": ["deb"]}}
    result = policy(config, project)
    assert result["formats_by_platform"]["linux"] == ["deb"]
    assert result["architectures"] == ["arm64"] and result["platforms"] == ["linux"]
    legacy_override = policy(config, {**PROJECT, "formats": ["flatpak"]})
    assert legacy_override["formats_by_platform"]["linux"] == ["flatpak"]


@pytest.mark.parametrize("name", ["app-linux-x64.exe", "app-windows-x64.AppImage"])
def test_conflicting_platform_and_extension_never_automatically_select(name):
    config = {"selection": {"include_assets": ["*"]}}
    plan = plan_release(config, PROJECT, release([remote(name)]))
    assert not plan["assets"]
    assert plan["asset_decisions"][0]["decision"] == "ambiguous"


def test_checksum_like_installer_name_is_not_metadata():
    plan = plan_release({}, PROJECT, release([remote("shared-windows-x64.exe")]))
    assert plan["assets"][0]["platform"] == "windows"


def test_metadata_only_does_not_select_an_installer():
    plan = plan_release(
        {"selection": {"platforms": ["linux"]}},
        PROJECT,
        release([remote("app-windows-x64.exe"), remote("SHA256SUMS.txt", 2)]),
    )
    assert not plan["assets"] and plan["status"] != "complete"
    assert plan["asset_decisions"][1]["reason"] == "no relevant installer selected"


def test_legacy_config_roundtrip_without_eager_migration(tmp_path):
    path = tmp_path / "config.toml"
    text = (
        '[archive]\npath = "'
        + str(tmp_path / "archive")
        + '"\n[platforms]\nwindows = false\nlinux = true\nmacos = false\n[selection]\nformats = ["rpm", "flatpak"]\narchitectures = ["amd64"]\n'
    )
    path.write_text(text)
    config = load(path)
    assert path.read_text() == text
    result = policy(config, {})
    assert result["platforms"] == ["linux"]
    assert result["architectures"] == ["x86_64"]
    assert result["formats_by_platform"]["linux"] == ["flatpak", "rpm"]
    config["selection"]["formats_by_platform"] = {"windows": ["msi"], "linux": ["rpm"]}
    save(path, config)
    assert load(path) == config


@pytest.mark.parametrize(
    "text",
    [
        '[selection.formats_by_platform]\nlinux = ["exe"]',
        '[selection.formats_by_platform]\nmacos = ["rpm"]',
        '[selection.formats_by_platform]\nlinux = "rpm"',
        "[selection]\nformats_by_platform = []",
        '[selection]\narchitectures = ["typo"]',
    ],
)
def test_invalid_new_preferences(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load(path)


def test_configuration_cli_edits_scopes_and_dry_run(tmp_path):
    path = tmp_path / "config.toml"
    data = load(path)
    data["archive"]["path"] = str(tmp_path / "archive")
    data["repositories"] = [{**PROJECT, "pinned_versions": ["v1.0"]}]
    save(path, data)
    runner = CliRunner()

    def run(*args, **kwargs):
        return runner.invoke(app, ["--config", str(path), "config", *args], **kwargs)

    before = path.read_bytes()
    assert run("detect").exit_code == 0
    assert run("platforms", "--set", "linux", "--dry-run").exit_code == 0
    assert path.read_bytes() == before
    for args in [
        ("platforms", "--set", "linux,windows"),
        ("architectures", "--set", "AMD64"),
        ("formats", "--platform", "linux", "--set", "AppImage,rpm"),
        ("formats", "--platform", "windows", "--set", "msi"),
        ("architectures", "--repo", "a/b", "--set", "ARM64,universal"),
    ]:
        result = run(*args)
        assert result.exit_code == 0, result.output
    result = json.loads(run("show", "--repo", "a/b").output)
    assert result["effective"]["architectures"] == ["arm64", "universal"]
    assert result["effective"]["formats_by_platform"]["linux"] == ["appimage", "rpm"]
    assert load(path)["repositories"][0]["pinned_versions"] == ["v1.0"]
    assert run("architectures", "--repo", "a/b", "--reset").exit_code == 0
    assert json.loads(run("show", "--repo", "a/b").output)["effective"]["architectures"] == [
        "x86_64"
    ]
    assert run("platforms", "--interactive", input="linux\n").exit_code == 0
    assert json.loads(run("platforms").output)["platforms"] == ["linux"]


def test_detect_can_review_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(
        "getcraft.configuration_commands.detect",
        lambda: {
            "suggested": {
                "platforms": ["linux"],
                "architectures": ["x86_64"],
                "formats_by_platform": {"linux": ["rpm"]},
            }
        },
    )
    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(path), "config", "detect", "--apply", "--dry-run"])
    assert result.exit_code == 0 and not path.exists()


def test_concurrent_pin_edit_is_not_overwritten_by_preferences(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    config = load(path)
    config["archive"]["path"] = str(tmp_path / "archive")
    config["repositories"] = [copy.deepcopy(PROJECT)]
    save(path, config)

    def prompt(*args, **kwargs):
        changed = load(path)
        changed["repositories"][0]["pinned_versions"] = ["v1.0"]
        save(path, changed)
        return "linux"

    monkeypatch.setattr("getcraft.configuration_commands.typer.prompt", prompt)
    result = CliRunner().invoke(
        app, ["--config", str(path), "config", "platforms", "--interactive"]
    )
    assert result.exit_code == 1 and "changed during review" in result.output
    assert load(path)["repositories"][0]["pinned_versions"] == ["v1.0"]


def test_legacy_explicit_generic_archives_remain_supported():
    for name, fmt in [
        ("app-linux-x64.zip", "zip"),
        ("app-macos-arm64.tar.gz", "tar.gz"),
        ("app-windows-x64.tar.xz", "tar.xz"),
        ("app-linux-x64.bin", "unknown"),
    ]:
        config = {"selection": {"formats": [fmt], "include_assets": [name]}}
        plan = plan_release(config, PROJECT, release([remote(name)]))
        assert len(plan["assets"]) == 1, name


@pytest.mark.parametrize(
    "name", ["app-windows-notarm64.exe", "app-windows-x64Setup.exe", "app-macos-notuniversal.dmg"]
)
def test_architecture_substrings_do_not_establish_compatibility(name):
    plan = plan_release({}, PROJECT, release([remote(name)]))
    assert not plan["assets"]
    assert plan["asset_decisions"][0]["decision"] == "ambiguous"


def test_detect_apply_and_cancel_preserve_unrelated_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    data = load(path)
    data["archive"].update(path=str(tmp_path / "archive"), keep_versions=7)
    data["selection"] = {"formats_by_platform": {"windows": ["msi"]}}
    data["repositories"] = [{**PROJECT, "platforms": ["windows"], "pinned_versions": ["v1.0"]}]
    save(path, data)
    monkeypatch.setattr(
        "getcraft.configuration_commands.detect",
        lambda: {
            "suggested": {
                "platforms": ["linux"],
                "architectures": ["x86_64"],
                "formats_by_platform": {"linux": ["rpm"]},
            }
        },
    )
    runner = CliRunner()
    prefix = ["--config", str(path), "config", "detect", "--apply"]
    before = path.read_bytes()
    assert runner.invoke(app, prefix, input="n\n").exit_code != 0
    assert path.read_bytes() == before
    result = runner.invoke(app, [*prefix, "--yes"])
    assert result.exit_code == 0, result.output
    saved = load(path)
    assert saved["selection"]["platforms"] == ["linux"]
    assert saved["selection"]["formats_by_platform"] == {"linux": ["rpm"], "windows": ["msi"]}
    assert saved["archive"]["keep_versions"] == 7
    assert saved["repositories"] == data["repositories"]


@pytest.mark.parametrize("architecture", ["x86_64", "x86-64", "amd64", "x64"])
def test_x86_64_filename_aliases_do_not_match_32_bit_x86(architecture):
    plan = plan_release({}, PROJECT, release([remote(f"app-linux-{architecture}.rpm")]))
    assert plan["assets"][0]["architecture"] == "x86_64"
