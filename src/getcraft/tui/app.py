"""Keyboard-first GetCraft terminal application."""

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Select,
    Static,
    Tree,
)

from getcraft.config import load
from getcraft.configuration import edit_load
from getcraft.reports import collect
from getcraft.tui import services
from getcraft.tui.dialogs import ConfirmDialog, RepairDialog, RepositoryDialog, SettingsDialog

PAGES = [
    ("dashboard", "Dashboard"),
    ("repositories", "Repositories"),
    ("settings", "Settings"),
    ("sync", "Sync"),
    ("library", "Library"),
    ("verify", "Verify"),
    ("retention", "Retention"),
]


class JobDone(Message):
    def __init__(self, name: str, result=None, error: str | None = None):
        super().__init__()
        self.name, self.result, self.error = name, result, error


class TransferProgress(Message):
    def __init__(self, item):
        super().__init__()
        self.item = item


class HelpDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static("GetCraft keyboard help", classes="heading")
            yield Static(
                "1–7: pages · arrows/Enter: navigate · Tab/Shift+Tab: fields\n"
                "/: search · Esc: back/cancel · q: quit\n"
                "Space: toggle selections. No installer is ever executed.\n"
                "Sync and deletion always require an explicit preview and confirmation.",
                markup=False,
            )
            yield Button("Close", id="close-help")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


class GetCraftApp(App):
    TITLE = "GetCraft"
    SUB_TITLE = "Official release archive"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("1", "page('dashboard')", "Dashboard"),
        ("2", "page('repositories')", "Projects"),
        ("3", "page('settings')", "Settings"),
        ("4", "page('sync')", "Sync"),
        ("5", "page('library')", "Library"),
        ("6", "page('verify')", "Verify"),
        ("7", "page('retention')", "Retention"),
        ("/", "search", "Search"),
        ("escape", "back", "Back"),
        ("?", "help", "Help"),
        ("q", "quit", "Quit"),
    ]
    CSS = """
    Screen { background: #111827; color: #dbe4ef; }
    Header, Footer { background: #1b2638; }
    #body { height: 1fr; }
    #navigation { width: 22; background: #172235; padding: 1; }
    #navigation ListItem { padding: 1 0; }
    #pages { width: 1fr; }
    .page { padding: 1 2; }
    .heading { text-style: bold; color: #9fc6ff; margin-bottom: 1; }
    SelectionList { height: auto; max-height: 12; min-height: 4; }
    #archive-tree { height: 18; }
    #toml-editor { height: 18; }
    #state { height: auto; max-height: 5; background: #1b2638; padding: 0 1; }
    #size-hint { height: auto; color: #f1c87b; }
    .compact #navigation { width: 15; padding: 0; }
    .compact .page { padding: 0 1; }
    ModalScreen { align: center middle; background: #00000099; }
    #dialog { width: 80%; max-width: 90; max-height: 90%; height: auto; padding: 1 2; background: #1b2638; border: round #709ad0; }
    Button { margin: 0 1 1 0; }
    """

    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = config_path
        self.busy = False
        self.library_data = None
        self.selected_release = None
        self.preview = None
        self.cancel_event = None
        self.job_name = None
        self.transfer_events = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield ListView(
                *(ListItem(Label(title), id="nav-" + name) for name, title in PAGES),
                id="navigation",
            )
            with ContentSwitcher(initial="dashboard", id="pages"):
                for name, title in PAGES:
                    with VerticalScroll(id=name, classes="page"):
                        yield Static(title, classes="heading")
                        if name == "dashboard":
                            yield Button("Refresh dashboard", id="refresh-dashboard")
                        elif name == "repositories":
                            yield Input(
                                placeholder="Search registered projects", id="project-search"
                            )
                            yield Select([], prompt="Select project", id="project")
                            for caption, identifier in [
                                ("Add project", "add"),
                                ("Enable", "enable"),
                                ("Disable", "disable"),
                                ("Remove monitoring", "remove"),
                                ("Preferences", "preferences"),
                                ("Consult releases", "releases"),
                            ]:
                                yield Button(caption, id="repo-" + identifier)
                        elif name == "settings":
                            yield Button("Edit global preferences", id="edit-settings")
                            yield Button("Reload configuration", id="reload-config")
                        elif name in ("sync", "verify", "retention"):
                            yield Select(
                                [("All enabled projects", "*")], value="*", id=name + "-project"
                            )
                            yield Button(
                                {
                                    "sync": "Preview downloads",
                                    "verify": "Verify local files offline",
                                    "retention": "Simulate cleanup",
                                }[name],
                                id=name + "-preview",
                            )
                            if name != "verify":
                                yield Button(
                                    "Download selected files"
                                    if name == "sync"
                                    else "Review deletion",
                                    id=name + "-apply",
                                    disabled=True,
                                )
                            if name == "sync":
                                yield Label("Current file")
                                yield ProgressBar(total=100, id="download-progress")
                                yield Label("Overall: processed files (includes reused/failed)")
                                yield ProgressBar(total=1, id="overall-progress")
                                yield Static("", id="transfer-log", markup=False)
                                yield Button("Cancel safely", id="cancel-operation", disabled=True)
                        elif name == "library":
                            yield Button("Refresh library", id="refresh-library")
                            yield Tree("Archive", id="archive-tree")
                            yield Button(
                                "Installation instructions", id="instructions", disabled=True
                            )
                            yield Button("Toggle pinned version", id="pin-version", disabled=True)
                            yield Button(
                                "Verify selected project offline",
                                id="library-verify",
                                disabled=True,
                            )
                        yield Static(
                            "Select an action. No operation has started.",
                            id=name + "-content",
                            markup=False,
                        )
        yield Static("", id="size-hint")
        yield Static("Ready · No automatic downloads or deletions", id="state", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        self.screen_stack[0].query_one("#navigation", ListView).focus()
        self.refresh_dashboard()
        self.refresh_projects()

    def run_job(self, name: str, function) -> None:
        from threading import Thread

        Thread(
            target=self._execute_job,
            args=(name, function),
            name="getcraft-" + name,
            daemon=name not in ("registry", "settings", "pin", "sync-apply", "retention-apply"),
        ).start()

    def _execute_job(self, name: str, function) -> None:
        try:
            self.post_message(JobDone(name, function()))
        except Exception as error:
            import httpx

            message = (
                "Network unavailable or request timed out. Check connection/token and retry."
                if isinstance(error, httpx.HTTPError)
                else str(error)
            )
            self.post_message(JobDone(name, error=message))

    def refresh_dashboard(self) -> None:
        self.screen_stack[0].query_one("#dashboard-content", Static).update(
            "Loading local archive…"
        )

        def read():
            config = load(self.config_path)
            data = collect(Path(config["archive"]["path"]).expanduser().absolute(), config)
            return config, data

        self.run_job("dashboard", read)

    def on_job_done(self, event: JobDone) -> None:
        if event.name != "dashboard":
            self.busy = False
            self.query_main("#cancel-operation", Button).disabled = True
            self.query_main("#state", Static).update(
                "Error: " + event.error if event.error else "Operation finished"
            )
            page = {
                "library": "library",
                "library-text": "library",
                "releases": "repositories",
                "sync-preview": "sync",
                "sync-apply": "sync",
                "verify": "verify",
                "retention-preview": "retention",
                "retention-apply": "retention",
            }.get(event.name)
            if event.error:
                if page:
                    self.query_main("#" + page + "-content", Static).update(
                        event.error + "\nCorrect the issue and retry."
                    )
                return
            if event.name == "library":
                self.populate_library(event.result)
            elif event.name in ("sync-preview", "retention-preview"):
                self.preview = (event.name, event.result)
                self.query_main("#" + page + "-content", Static).update(event.result["text"])
                self.query_main("#" + page + "-apply", Button).disabled = not event.result[
                    "actionable"
                ]
            elif page:
                self.query_main("#" + page + "-content", Static).update(str(event.result))
            else:
                self.query_main("#state", Static).update(str(event.result))
                self.refresh_projects()
                if event.name == "pin":
                    self.start_job("library", lambda: services.catalog(self.config_path))
            return
        if event.error:
            self.screen_stack[0].query_one("#state", Static).update(
                "Error: " + event.error + " · correct settings or retry"
            )
            self.screen_stack[0].query_one("#dashboard-content", Static).update(event.error)
            return
        if event.name == "dashboard":
            config, data = event.result
            releases = [r for p in data["projects"] for r in p["releases"]]
            problems = data["problems"] + [
                problem for p in data["projects"] for problem in p["problems"]
            ]
            problems += [problem for r in releases for problem in r["problems"] + r["unresolved"]]
            problems += [
                f"{r['repository']} {r['tag']}: {r['status']}"
                for r in releases
                if r["status"] != "complete"
            ]
            latest = max(
                (p["last_sync"] for p in data["projects"] if p["last_sync"]), default="Unknown"
            )
            text = (
                f"Projects registered: {len(config['repositories'])}\nArchived versions: {len(releases)}\n"
                f"Logical storage: {data['total_bytes']:,} bytes\nLast known sync: {latest}\n"
                f"Integrity: {'attention required' if problems else 'verified local files' if releases else 'no archived versions'}\n\n"
                + ("\n".join(problems) if problems else "No reported problems.")
            )
            self.screen_stack[0].query_one("#dashboard-content", Static).update(text)
            if not self.busy:
                self.query_main("#state", Static).update(
                    "Local dashboard loaded · No network or automatic sync"
                )

    def query_main(self, selector, kind):
        return self.screen_stack[0].query_one(selector, kind)

    def start_job(self, name, function):
        if self.busy:
            self.notify("Wait for the current operation or cancel it first.")
            return
        self.busy, self.job_name = True, name
        self.query_main("#state", Static).update("Working… " + name)
        self.run_job(name, function)

    def refresh_projects(self):
        try:
            data = load(self.config_path)
            rows = data["repositories"]
            options = [
                (
                    f"{p['owner']}/{p['repo']} ({'enabled' if p.get('enabled', True) else 'disabled'})",
                    f"{p['owner']}/{p['repo']}",
                )
                for p in rows
            ]
            self.query_main("#project", Select).set_options(options)
            for page in ("sync", "verify", "retention"):
                self.query_main("#" + page + "-project", Select).set_options(
                    [("All enabled projects", "*")] + [(n, n) for _, n in options]
                )
                self.query_main("#" + page + "-project", Select).value = "*"
            self.query_main("#repositories-content", Static).update(
                f"{len(rows)} registered projects. Removing monitoring preserves all backups."
            )
            self.query_main("#settings-content", Static).update(
                f"Configuration: {self.config_path}\nArchive: {data['archive']['path']}"
            )
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.query_main("#state", Static).update("Invalid configuration: " + str(error))

    def project_name(self):
        value = self.query_main("#project", Select).value
        if value is Select.BLANK:
            raise ValueError("Select a registered project first")
        return value

    def scope(self, page):
        value = self.query_main("#" + page + "-project", Select).value
        return None if value in ("*", Select.BLANK) else value

    def edit_preferences(self, repository=None):
        from getcraft.configuration import config_fingerprint

        try:
            data, baseline = edit_load(self.config_path)
        except (ValueError, KeyError, TypeError):
            baseline = config_fingerprint(self.config_path)
            self.push_screen(
                RepairDialog(self.config_path.read_text()),
                lambda result: (
                    self.start_job(
                        "settings",
                        lambda: (
                            services.save_settings(self.config_path, result, baseline)
                            or "Configuration repaired."
                        ),
                    )
                    if result is not None
                    else None
                ),
            )
            return

        def saved(result):
            if result is not None:
                self.start_job(
                    "settings",
                    lambda: (
                        services.save_settings(self.config_path, result, baseline)
                        or "Preferences saved; existing backups preserved."
                    ),
                )

        self.push_screen(SettingsDialog(data, repository), saved)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if len(self.screen_stack) > 1:
            return
        try:
            if button == "cancel-operation":
                self.action_cancel_operation()
                return
            if self.busy:
                self.notify("An operation is running; wait or cancel safely.")
                return
            if button == "refresh-dashboard":
                self.refresh_dashboard()
            elif button == "reload-config":
                self.refresh_projects()
                self.refresh_dashboard()
            elif button == "edit-settings":
                self.edit_preferences()
            elif button == "repo-add":
                self.push_screen(
                    RepositoryDialog(),
                    lambda name: (
                        self.start_job(
                            "registry",
                            lambda: services.registry_edit(self.config_path, "add", name),
                        )
                        if name
                        else None
                    ),
                )
            elif button in ("repo-enable", "repo-disable", "repo-remove"):
                name, action = self.project_name(), button.removeprefix("repo-")

                def apply(confirmed):
                    if confirmed:
                        self.start_job(
                            "registry",
                            lambda: services.registry_edit(self.config_path, action, name),
                        )

                if action == "remove":
                    self.push_screen(
                        ConfirmDialog(
                            "Remove monitoring?", name + "\nExisting backups will be preserved."
                        ),
                        apply,
                    )
                else:
                    apply(True)
            elif button == "repo-preferences":
                self.edit_preferences(self.project_name())
            elif button == "repo-releases":
                name = self.project_name()
                self.start_job("releases", lambda: services.releases(self.config_path, name))
            elif button == "refresh-library":
                self.start_job("library", lambda: services.catalog(self.config_path))
            elif button in ("instructions", "pin-version", "library-verify"):
                row = self.selected_release
                if row:
                    if button == "instructions":
                        self.start_job(
                            "library-text", lambda: services.instructions(self.config_path, row)
                        )
                    elif button == "library-verify":
                        self.start_job(
                            "library-text",
                            lambda: services.verify(self.config_path, row["repository"]),
                        )
                    else:
                        self.start_job(
                            "pin",
                            lambda: services.toggle_pin(
                                self.config_path, row["repository"], row["tag"]
                            ),
                        )
            elif button == "verify-preview":
                name = self.scope("verify")
                self.start_job("verify", lambda: services.verify(self.config_path, name))
            elif button in ("sync-preview", "retention-preview"):
                page = button.removesuffix("-preview")
                name = self.scope(page)
                self.preview = None
                self.query_main("#" + page + "-apply", Button).disabled = True
                self.start_job(
                    button, lambda: services.preview_operation(self.config_path, page, name)
                )
            elif button in ("sync-apply", "retention-apply"):
                page = button.removesuffix("-apply")
                if self.preview and self.preview[0] == page + "-preview":
                    preview = self.preview[1]
                    self.push_screen(
                        ConfirmDialog(
                            "Download files?"
                            if page == "sync"
                            else "Permanently delete these managed files?",
                            preview["text"],
                        ),
                        lambda accepted: self.apply_operation(page, preview) if accepted else None,
                    )
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.query_main("#state", Static).update("Error: " + str(error))

    def on_select_changed(self, event: Select.Changed):
        if event.select.id in ("sync-project", "retention-project"):
            page = event.select.id.removesuffix("-project")
            self.preview = None
            self.query_main("#" + page + "-apply", Button).disabled = True

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != "project-search":
            return
        try:
            rows = load(self.config_path)["repositories"]
            names = [f"{p['owner']}/{p['repo']}" for p in rows]
            self.query_main("#project", Select).set_options(
                [(n, n) for n in names if event.value.lower() in n.lower()]
            )
        except (ValueError, KeyError, TypeError, OSError):
            pass

    def populate_library(self, data):
        self.library_data = data
        self.selected_release = None
        for identifier in ("instructions", "pin-version", "library-verify"):
            self.query_main("#" + identifier, Button).disabled = True
        tree = self.query_main("#archive-tree", Tree)
        tree.clear()
        for project in data["projects"]:
            pn = tree.root.add(Text(project["repository"]))
            for release in project["releases"]:
                rn = pn.add(
                    Text(
                        release["tag"]
                        + (" [pinned]" if release["pinned"] else "")
                        + " · "
                        + release["status"]
                    ),
                    data=(release, None),
                )
                platforms = {}
                architectures = {}
                for asset in release["assets"]:
                    platform, arch = asset["platform"], asset["architecture"]
                    if platform not in platforms:
                        platforms[platform] = rn.add(platform, data=(release, None))
                    if (platform, arch) not in architectures:
                        architectures[platform, arch] = platforms[platform].add(
                            arch, data=(release, None)
                        )
                    architectures[platform, arch].add_leaf(
                        Text(asset["name"]), data=(release, asset)
                    )
        tree.root.expand()
        self.query_main("#library-content", Static).update(
            "Select a version or file. " + "; ".join(data["problems"])
        )

    def on_tree_node_selected(self, event: Tree.NodeSelected):
        if event.node.data:
            release, asset = event.node.data
            self.selected_release = release
            for identifier in ("instructions", "pin-version", "library-verify"):
                self.query_main("#" + identifier, Button).disabled = False
            text = f"{release['repository']} {release['tag']}\nState: {release['status']} · pinned: {release['pinned']}\nArchived: {release['archived_at']}"
            if asset:
                text += f"\n{asset['name']}\nSize: {asset['size']:,} bytes\nSHA-256: {asset.get('sha256') or 'Unknown'}\nIntegrity: {asset['integrity']}\nPath: {asset['path']}"
            text += "\nLocal SHA-256 detects corruption; it does not prove publisher authenticity."
            self.query_main("#library-content", Static).update(text)

    def apply_operation(self, page, preview):
        from threading import Event

        self.cancel_event = Event()
        self.transfer_events = []
        self.query_main("#transfer-log", Static).update("")
        self.query_main("#overall-progress", ProgressBar).update(total=1, progress=0)
        self.query_main("#" + page + "-apply", Button).disabled = True
        if page == "sync":
            self.query_main("#cancel-operation", Button).disabled = False
        self.start_job(
            page + "-apply",
            lambda: services.apply_operation(
                self.config_path,
                page,
                preview,
                self.cancel_event,
                lambda item: self.post_message(TransferProgress(item)),
            ),
        )
        if page == "sync":
            self.query_main("#cancel-operation", Button).disabled = False
        self.preview = None

    def on_transfer_progress(self, event):
        item = event.item
        if "processed" in item:
            self.query_main("#overall-progress", ProgressBar).update(
                total=item["total"], progress=item["processed"]
            )
            self.transfer_events.append(f"{item['outcome'].upper()} {item['name']}")
            self.query_main("#transfer-log", Static).update("\n".join(self.transfer_events))
        self.query_main("#download-progress", ProgressBar).update(
            total=item["size"] or 1, progress=item["bytes"]
        )
        self.query_main("#state", Static).update(
            f"{item['name']}: {item['bytes']:,}/{item['size']:,} bytes"
        )

    def action_cancel_operation(self):
        if self.busy and self.job_name == "sync-apply" and self.cancel_event:
            self.cancel_event.set()
            self.query_main("#state", Static).update(
                "Cancellation requested. Waiting for current network read; preserving validated files…"
            )
        elif self.busy:
            self.notify("This operation must finish safely before closing.")

    def action_quit(self):
        if len(self.screen_stack) > 1:
            return
        if self.busy:
            self.action_cancel_operation()
            self.notify("Wait for the operation to finish, then press q again.")
        else:
            self.exit()

    def on_resize(self, event) -> None:
        if not self.is_mounted:
            return
        self.set_class(event.size.width < 90, "compact")
        self.screen_stack[0].query_one("#size-hint", Static).update(
            "Small terminal: use 1–7 and Tab; panels can scroll."
            if event.size.width < 60 or event.size.height < 20
            else ""
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "navigation":
            self.action_page(event.item.id.removeprefix("nav-"))

    def action_page(self, page: str) -> None:
        if len(self.screen_stack) > 1:
            return
        self.screen_stack[0].query_one("#pages", ContentSwitcher).current = page
        self.query_main("#navigation", ListView).index = [name for name, _ in PAGES].index(page)
        if page == "library" and self.library_data is None and not self.busy:
            self.start_job("library", lambda: services.catalog(self.config_path))

    def action_help(self) -> None:
        if len(self.screen_stack) == 1:
            self.push_screen(HelpDialog())

    def action_back(self) -> None:
        if len(self.screen_stack) == 1:
            if self.busy:
                self.action_cancel_operation()
            else:
                self.action_page("dashboard")

    def action_search(self) -> None:
        if len(self.screen_stack) == 1:
            self.action_page("repositories")
            self.query_main("#project-search", Input).focus()


def launch(config_path: Path) -> None:
    GetCraftApp(config_path).run()
