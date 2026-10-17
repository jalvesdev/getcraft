"""Keyboard-accessible editable forms and explicit confirmations."""

from copy import deepcopy

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, SelectionList, Static

from getcraft.config import validate
from getcraft.configuration import target
from getcraft.preferences import ARCHITECTURES, PLATFORM_FORMATS, PLATFORMS, detect, policy


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title, text):
        super().__init__()
        self.title_text, self.body_text = title, text

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static(self.title_text, classes="heading", markup=False)
            yield Static(self.body_text, markup=False)
            yield Button("Cancel", id="cancel")
            yield Button("Confirm", variant="error", id="confirm")

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "confirm")


class RepositoryDialog(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Label("GitHub URL or owner/repo")
            yield Input(placeholder="storytold/photocraft", id="repository")
            yield Static("", id="form-error", markup=False)
            yield Button("Validate and add", id="save")
            yield Button("Cancel", id="cancel")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.action_cancel()
        else:
            from getcraft.github import repository_name

            try:
                name = repository_name(self.query_one(Input).value.strip())
            except ValueError as error:
                self.query_one("#form-error", Static).update(str(error))
            else:
                self.dismiss(name)


class SettingsDialog(ModalScreen[dict | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, data, repository=None):
        super().__init__()
        self.data, self.repository = deepcopy(data), repository
        self.restore_inheritance = False
        self.effective = policy(data, target(data, repository) if repository else {})

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static(self.repository or "Global preferences", classes="heading", markup=False)
            if not self.repository:
                yield Label("Archive directory (existing backups will not be moved)")
                yield Input(str(self.data["archive"]["path"]), id="archive-path")
            yield Label("Versions kept (prune only; never deletes during sync)")
            settings = (
                target(self.data, self.repository) if self.repository else self.data["archive"]
            )
            yield Input(
                str(settings.get("keep_versions", self.data["archive"]["keep_versions"])),
                id="keep-versions",
            )
            yield Label("Platforms · Space to toggle")
            yield SelectionList(
                *[(p, p, p in self.effective["platforms"]) for p in PLATFORMS], id="platforms"
            )
            yield Label("Architectures · Space to toggle")
            yield SelectionList(
                *[(p, p, p in self.effective["architectures"]) for p in ARCHITECTURES],
                id="architectures",
            )
            for platform in PLATFORMS:
                yield Label(platform + " formats")
                yield SelectionList(
                    *[
                        (f, f, f in self.effective["formats_by_platform"][platform])
                        for f in PLATFORM_FORMATS[platform]
                    ],
                    id="formats-" + platform,
                )
            yield Static("", id="form-error", markup=False)
            yield Button("Suggest detected environment", id="detect")
            if self.repository:
                yield Button("Restore global inheritance", id="inherit")
            yield Button("Save preferences", variant="primary", id="save")
            yield Button("Cancel", id="cancel")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed):
        button = event.button.id
        if button == "cancel":
            self.action_cancel()
            return
        if button == "detect":
            detected = detect()
            suggestion = detected["suggested"]
            for key in ("platforms", "architectures"):
                widget = self.query_one("#" + key, SelectionList)
                widget.deselect_all()
                for value in suggestion[key]:
                    widget.select(value)
            for platform, formats in suggestion["formats_by_platform"].items():
                widget = self.query_one("#formats-" + platform, SelectionList)
                widget.deselect_all()
                for value in formats:
                    widget.select(value)
            self.query_one("#form-error", Static).update(
                "Suggestion only. Review selections and Save to apply. " + str(detected)
            )
            return
        data = deepcopy(self.data)
        settings = target(data, self.repository)
        if button == "inherit":
            self.restore_inheritance = True
            global_policy = policy(self.data, {})
            for key in ("platforms", "architectures"):
                widget = self.query_one("#" + key, SelectionList)
                widget.deselect_all()
                for value in global_policy[key]:
                    widget.select(value)
            for platform in PLATFORMS:
                widget = self.query_one("#formats-" + platform, SelectionList)
                widget.deselect_all()
                for value in global_policy["formats_by_platform"][platform]:
                    widget.select(value)
            self.query_one("#keep-versions", Input).value = str(
                self.data["archive"]["keep_versions"]
            )
            self.query_one("#form-error", Static).update(
                "Global values restored in this form. Save to apply, or Cancel."
            )
            return
        try:
            keep = int(self.query_one("#keep-versions", Input).value)
            if self.repository:
                settings["keep_versions"] = keep
            else:
                data["archive"]["keep_versions"] = keep
                path = self.query_one("#archive-path", Input).value.strip()
                if not path:
                    raise ValueError("Archive directory is required")
                data["archive"]["path"] = path
            for key in ("platforms", "architectures"):
                settings[key] = list(self.query_one("#" + key, SelectionList).selected)
                if not settings[key]:
                    raise ValueError("Select at least one " + key)
            settings.pop("formats", None)
            settings["formats_by_platform"] = {}
            for platform in PLATFORMS:
                values = list(self.query_one("#formats-" + platform, SelectionList).selected)
                if platform in settings["platforms"] and not values:
                    raise ValueError("Select at least one format for " + platform)
                settings["formats_by_platform"][platform] = values
            if self.repository and self.restore_inheritance:
                global_policy = policy(self.data, {})
                if (
                    all(
                        settings[key] == global_policy[key]
                        for key in ("platforms", "architectures", "formats_by_platform")
                    )
                    and keep == self.data["archive"]["keep_versions"]
                ):
                    for key in (
                        "platforms",
                        "architectures",
                        "formats",
                        "formats_by_platform",
                        "keep_versions",
                    ):
                        settings.pop(key, None)
            validate(data)
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.query_one("#form-error", Static).update(str(error))
        else:
            self.dismiss(data)


class RepairDialog(ModalScreen[dict | None]):
    """Explicit recovery for malformed TOML; never overwrite it with defaults."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, text):
        super().__init__()
        self.original = text

    def compose(self):
        from textual.widgets import TextArea

        with VerticalScroll(id="dialog"):
            yield Static(
                "Repair configuration TOML. Save validates the entire document.", markup=False
            )
            yield TextArea(self.original, id="toml-editor")
            yield Static("", id="form-error", markup=False)
            yield Button("Validate and save", id="save")
            yield Button("Cancel", id="cancel")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        import tomllib

        from textual.widgets import TextArea

        if event.button.id == "cancel":
            self.action_cancel()
            return
        try:
            data = validate(tomllib.loads(self.query_one(TextArea).text))
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.query_one("#form-error", Static).update(str(error))
        else:
            self.dismiss(data)
