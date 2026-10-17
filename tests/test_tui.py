import asyncio

from textual.widgets import ContentSwitcher
from typer.testing import CliRunner

from getcraft.cli import app
from getcraft.tui.app import GetCraftApp, HelpDialog


def test_no_arguments_launches_tui_and_help_stays_cli(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("getcraft.tui.app.launch", calls.append)
    result = CliRunner().invoke(app, ["--config", str(tmp_path / "config.toml")])
    assert result.exit_code == 0 and calls == [tmp_path / "config.toml"]
    assert CliRunner().invoke(app, ["--help"]).exit_code == 0
    assert len(calls) == 1


def test_keyboard_navigation_help_and_small_terminal(tmp_path):
    async def scenario():
        application = GetCraftApp(tmp_path / "config.toml")
        async with application.run_test(size=(58, 19)) as pilot:
            await pilot.press("2")
            assert application.query_one("#pages", ContentSwitcher).current == "repositories"
            await pilot.press("?")
            assert isinstance(application.screen, HelpDialog)
            await pilot.press("escape", "escape")
            assert application.query_one("#pages", ContentSwitcher).current == "dashboard"

    asyncio.run(scenario())


def configured(tmp_path, config=None):
    from getcraft.config import save

    path = tmp_path / "tui.toml"
    save(
        path,
        config
        or dict(archive=dict(path=str(tmp_path / "archive"), keep_versions=3), repositories=[]),
    )
    return path


async def settled(pilot, application):
    for _ in range(100):
        await pilot.pause(0.02)
        if not application.busy:
            await pilot.pause(0.02)
            return
    raise AssertionError("TUI operation did not finish")


def test_empty_dashboard_and_no_automatic_network(tmp_path, monkeypatch):
    from textual.widgets import Static

    def forbidden(*args, **kwargs):
        raise AssertionError("No network on startup")

    monkeypatch.setattr("getcraft.github.GitHub.releases", forbidden)

    async def scenario():
        app = GetCraftApp(configured(tmp_path))
        async with app.run_test() as p:
            await p.pause(0.15)
            text = str(app.query_one("#dashboard-content", Static).content)
            assert "Projects registered: 0" in text and "Unknown" in text
            assert not (tmp_path / "archive").exists()

    asyncio.run(scenario())


def test_global_preferences_cancel_and_save(tmp_path):
    from textual.widgets import Button, Input, SelectionList

    from getcraft.config import load

    async def scenario():
        path = configured(tmp_path)
        before = path.read_bytes()
        app = GetCraftApp(path)
        async with app.run_test(size=(120, 50)) as p:
            await p.press("3")
            app.query_one("#edit-settings", Button).press()
            await p.pause()
            app.screen.query_one("#keep-versions", Input).value = "5"
            await p.press("escape")
            assert path.read_bytes() == before
            app.query_one("#edit-settings", Button).press()
            await p.pause()
            app.screen.query_one("#keep-versions", Input).value = "5"
            app.screen.query_one("#platforms", SelectionList).deselect_all().select("linux")
            app.screen.query_one("#architectures", SelectionList).deselect_all().select("x86_64")
            app.screen.query_one("#formats-linux", SelectionList).deselect_all().select("rpm")
            app.screen.query_one("#save", Button).press()
            await settled(p, app)
            data = load(path)
            assert data["archive"]["keep_versions"] == 5
            assert data["selection"]["platforms"] == ["linux"]
            assert data["selection"]["architectures"] == ["x86_64"]
            assert data["selection"]["formats_by_platform"]["linux"] == ["rpm"]

    asyncio.run(scenario())


def test_invalid_form_stays_open_and_detect_is_only_suggestion(tmp_path):
    from textual.widgets import Button, Input, Static

    from getcraft.tui.dialogs import SettingsDialog

    async def scenario():
        path = configured(tmp_path)
        before = path.read_bytes()
        app = GetCraftApp(path)
        async with app.run_test() as p:
            app.edit_preferences()
            await p.pause()
            app.screen.query_one("#keep-versions", Input).value = "0"
            app.screen.query_one("#save", Button).press()
            await p.pause()
            assert isinstance(app.screen, SettingsDialog)
            assert "positive" in str(app.screen.query_one("#form-error", Static).content)
            app.screen.query_one("#detect", Button).press()
            await p.pause()
            assert path.read_bytes() == before
            await p.press("escape")

    asyncio.run(scenario())


def test_add_search_disable_remove_confirmation(tmp_path, monkeypatch):
    from textual.widgets import Button, Input, Select

    from getcraft.config import load
    from getcraft.tui.dialogs import ConfirmDialog

    monkeypatch.setattr(
        "getcraft.github.GitHub.repository",
        lambda self, name: dict(full_name="storytold/photocraft"),
    )

    async def scenario():
        path = configured(tmp_path)
        app = GetCraftApp(path)
        async with app.run_test(size=(110, 45)) as p:
            await p.press("2")
            app.query_one("#repo-add", Button).press()
            await p.pause()
            app.screen.query_one(
                "#repository", Input
            ).value = "https://github.com/storytold/photocraft"
            app.screen.query_one("#save", Button).press()
            await settled(p, app)
            assert len(load(path)["repositories"]) == 1
            await p.press("/")
            assert app.focused.id == "project-search"
            app.query_one("#project", Select).value = "storytold/photocraft"
            app.query_one("#repo-disable", Button).press()
            await settled(p, app)
            assert not load(path)["repositories"][0]["enabled"]
            app.query_one("#project", Select).value = "storytold/photocraft"
            app.query_one("#repo-remove", Button).press()
            await p.pause()
            assert isinstance(app.screen, ConfirmDialog)
            await p.press("escape")
            assert load(path)["repositories"]

    asyncio.run(scenario())


def test_library_navigation_offline_instructions_and_pins(tmp_path, archive_fixture):
    from textual.widgets import Button, Static, Tree

    from getcraft.config import load

    root, config, remote, add, api = archive_fixture
    add(1)

    async def scenario():
        path = configured(tmp_path, config)
        app = GetCraftApp(path)
        async with app.run_test(size=(110, 45)) as p:
            await p.press("5")
            await settled(p, app)
            tree = app.query_one("#archive-tree", Tree)
            release_node = tree.root.children[0].children[0]
            file_node = release_node.children[0].children[0].children[0]
            tree.select_node(file_node)
            await p.pause()
            assert "SHA-256:" in str(app.query_one("#library-content", Static).content)
            app.query_one("#instructions", Button).press()
            await settled(p, app)
            assert "offline limitations" in str(app.query_one("#library-content", Static).content)
            app.query_one("#pin-version", Button).press()
            await settled(p, app)
            assert load(path)["repositories"][0]["pinned_versions"] == ["v1.0"]
            assert list(root.rglob("*.exe"))

    asyncio.run(scenario())


def test_network_errors_are_recoverable_and_sanitized(tmp_path, monkeypatch):
    import httpx
    from textual.widgets import Button, Static

    def broken(*args):
        raise httpx.ConnectError("secret-token https://user:password@example.invalid")

    monkeypatch.setattr("getcraft.tui.services.preview_operation", broken)

    async def scenario():
        app = GetCraftApp(configured(tmp_path))
        async with app.run_test() as p:
            await p.press("4")
            app.query_one("#sync-preview", Button).press()
            await settled(p, app)
            assert "Network unavailable" in str(app.query_one("#sync-content", Static).content)
            assert "secret-token" not in str(app.query_one("#state", Static).content)
            assert app.query_one("#sync-apply", Button).disabled
            await p.press("1")
            assert app.query_one("#pages", ContentSwitcher).current == "dashboard"

    asyncio.run(scenario())


def test_sync_requires_preview_confirmation_and_supports_cancellation(tmp_path, monkeypatch):
    from threading import Event

    from textual.widgets import Button, Static

    from getcraft.tui.dialogs import ConfirmDialog

    started, stopped = Event(), Event()
    preview = dict(text="1 file; 20 bytes", actionable=True)
    monkeypatch.setattr("getcraft.tui.services.preview_operation", lambda *a: preview)

    def sync(path, operation, plan, cancel, progress):
        started.set()
        cancel.wait(3)
        stopped.set()
        return "Cancelled safely."

    monkeypatch.setattr("getcraft.tui.services.apply_operation", sync)

    async def scenario():
        app = GetCraftApp(configured(tmp_path))
        async with app.run_test() as p:
            await p.press("4")
            assert app.query_one("#sync-apply", Button).disabled
            app.query_one("#sync-preview", Button).press()
            await settled(p, app)
            app.query_one("#sync-apply", Button).press()
            await p.pause()
            assert isinstance(app.screen, ConfirmDialog) and not started.is_set()
            await p.press("escape")
            assert not started.is_set()
            app.query_one("#sync-apply", Button).press()
            await p.pause()
            app.screen.query_one("#confirm", Button).press()
            await p.pause(0.05)
            assert started.is_set()
            await p.press("escape")
            await settled(p, app)
            assert stopped.is_set() and "Cancelled safely" in str(
                app.query_one("#sync-content", Static).content
            )

    asyncio.run(scenario())


def test_retention_preview_and_cancel_never_delete(tmp_path, archive_fixture, monkeypatch):
    from textual.widgets import Button, Static

    root, config, remote, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    monkeypatch.setattr("getcraft.tui.services.GitHub", api)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    async def scenario():
        app = GetCraftApp(configured(tmp_path, config))
        async with app.run_test() as p:
            await p.press("7")
            app.query_one("#retention-preview", Button).press()
            await settled(p, app)
            assert "v1.0" in str(app.query_one("#retention-content", Static).content)
            app.query_one("#retention-apply", Button).press()
            await p.pause()
            await p.press("escape")
        after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        assert before == after

    asyncio.run(scenario())


def test_invalid_config_can_be_repaired_without_restart(tmp_path):
    from textual.widgets import Button, TextArea

    from getcraft.config import load
    from getcraft.tui.dialogs import RepairDialog

    async def scenario():
        path = tmp_path / "broken.toml"
        path.write_text("not valid TOML!")
        app = GetCraftApp(path)
        async with app.run_test() as p:
            await p.press("3")
            app.query_one("#edit-settings", Button).press()
            await p.pause()
            assert isinstance(app.screen, RepairDialog)
            app.screen.query_one(TextArea).load_text(
                '[archive]\npath = "' + str(tmp_path / "archive") + '"\nkeep_versions = 3\n'
            )
            app.screen.query_one("#save", Button).press()
            await settled(p, app)
            assert load(path)["archive"]["keep_versions"] == 3

    asyncio.run(scenario())


def test_repo_restore_inheritance_can_be_cancelled(tmp_path, archive_fixture):
    from textual.widgets import Button

    from getcraft.config import load

    root, config, remote, add, api = archive_fixture
    config["repositories"][0]["platforms"] = ["windows"]

    async def scenario():
        path = configured(tmp_path, config)
        before = path.read_bytes()
        app = GetCraftApp(path)
        async with app.run_test() as p:
            app.edit_preferences("storytold/photocraft")
            await p.pause()
            app.screen.query_one("#inherit", Button).press()
            await p.pause()
            assert path.read_bytes() == before
            await p.press("escape")
            assert path.read_bytes() == before
            app.edit_preferences("storytold/photocraft")
            await p.pause()
            app.screen.query_one("#inherit", Button).press()
            await p.pause()
            app.screen.query_one("#save", Button).press()
            await settled(p, app)
            assert "platforms" not in load(path)["repositories"][0]

    asyncio.run(scenario())


def test_retention_confirmed_apply_only_temporary_fixture(tmp_path, archive_fixture, monkeypatch):
    from textual.widgets import Button, Static

    root, config, remote, add, api = archive_fixture
    for number in range(1, 5):
        add(number)
    monkeypatch.setattr("getcraft.tui.services.GitHub", api)

    async def scenario():
        app = GetCraftApp(configured(tmp_path, config))
        async with app.run_test() as p:
            await p.press("7")
            app.query_one("#retention-preview", Button).press()
            await settled(p, app)
            app.query_one("#retention-apply", Button).press()
            await p.pause()
            app.screen.query_one("#confirm", Button).press()
            await settled(p, app)
            assert "Removed 1 releases" in str(app.query_one("#retention-content", Static).content)
            assert not (root / "storytold/photocraft/v1.0/manifest.json").exists()
            assert (root / "storytold/photocraft/v4.0/manifest.json").exists()

    asyncio.run(scenario())
