"""GetCraft command line interface."""

from functools import wraps
from pathlib import Path

import httpx
import typer
from rich.console import Console

from getcraft.archive import inspect, lock, rebuild
from getcraft.config import default_path, load, save
from getcraft.download import Downloader
from getcraft.github import GitHub, repository_name
from getcraft.selection import classify, ordered
from getcraft.storage import inventory, state
from getcraft.sync import build_plans, synchronize

app = typer.Typer(no_args_is_help=True)
repo_app = typer.Typer(no_args_is_help=True)
app.add_typer(repo_app, name="repo")
console = Console(markup=False)


def handled(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError) as error:
            # Do not print raw HTTP errors, which may contain credentials or URLs.
            message = "Network request failed" if isinstance(error, httpx.HTTPError) else str(error)
            console.print(f"Error: {message}")
            raise typer.Exit(1) from None

    return wrapper


@app.callback()
def main(ctx: typer.Context, config: Path = typer.Option(default_path(), "--config")):
    """Archive and verify official GitHub release installers."""
    ctx.obj = config


@repo_app.command("add")
@handled
def add(ctx: typer.Context, repository: str, dry_run: bool = False):
    """Validate and register a GitHub repository."""
    data = load(ctx.obj)
    name = repository_name(repository)
    if any(f"{r['owner']}/{r['repo']}".lower() == name.lower() for r in data["repositories"]):
        raise ValueError("Repository already registered")
    with GitHub() as github:
        remote = github.repository(name)
    owner, repo = repository_name(remote["full_name"]).split("/")
    data["repositories"].append({"owner": owner, "repo": repo, "enabled": True})
    if not dry_run:
        save(ctx.obj, data)
    console.print(f"{'Would add' if dry_run else 'Added'} {owner}/{repo}")


@repo_app.command("list")
@handled
def list_repos(ctx: typer.Context):
    """List registered repositories, including disabled projects."""
    for row in load(ctx.obj)["repositories"]:
        console.print(
            f"{row['owner']}/{row['repo']} {'enabled' if row.get('enabled', True) else 'disabled'}"
        )


def change(ctx, repository, action, dry_run):
    data = load(ctx.obj)
    name = repository_name(repository)
    matches = [
        r for r in data["repositories"] if f"{r['owner']}/{r['repo']}".lower() == name.lower()
    ]
    if not matches:
        raise ValueError("Repository not registered")
    if action == "remove":
        data["repositories"].remove(matches[0])
    else:
        matches[0]["enabled"] = action == "enable"
    if not dry_run:
        save(ctx.obj, data)
    console.print(f"{'Would ' if dry_run else ''}{action}: {name}")


@repo_app.command()
@handled
def enable(ctx: typer.Context, repository: str, dry_run: bool = False):
    """Enable monitoring."""
    change(ctx, repository, "enable", dry_run)


@repo_app.command()
@handled
def disable(ctx: typer.Context, repository: str, dry_run: bool = False):
    """Disable monitoring."""
    change(ctx, repository, "disable", dry_run)


@repo_app.command()
@handled
def remove(ctx: typer.Context, repository: str, dry_run: bool = False):
    """Remove monitoring; preserve archived data."""
    change(ctx, repository, "remove", dry_run)


@app.command()
@handled
def check(ctx: typer.Context, repo: str | None = None, prereleases: bool = False):
    """Compare remote release IDs with the local inventory."""
    data = load(ctx.obj)
    rows = inventory(Path(data["archive"]["path"]))
    selected = repository_name(repo).lower() if repo else None
    repos = [
        r
        for r in data["repositories"]
        if r.get("enabled", True)
        and (selected is None or f"{r['owner']}/{r['repo']}".lower() == selected)
    ]
    if selected and not repos:
        raise ValueError("Repository not registered or disabled")
    failed = False
    with GitHub() as github:
        for project in repos:
            name = f"{project['owner']}/{project['repo']}"
            try:
                releases, warnings = ordered(
                    github.releases(name), prereleases or data["archive"]["include_prereleases"]
                )
                console.print(name)
                for warning in warnings:
                    console.print(f"Warning: {warning}")
                if not releases:
                    console.print("No eligible releases")
                for release in releases:
                    console.print(
                        f"  {release['tag_name']} id={release['id']} {'prerelease' if release.get('prerelease') else 'stable'} local={state(rows, name, release['id'])}"
                    )
                    if not release.get("assets"):
                        console.print("    Warning: release has no published binary assets")
                    for asset in release.get("assets", []):
                        platform, arch, warning = classify(asset["name"])
                        console.print(
                            f"    {asset['name']} | {platform}/{arch}"
                            + (f" | Warning: {warning}" if warning else "")
                        )
            except (ValueError, httpx.HTTPError) as error:
                failed = True
                console.print(
                    f"Error querying {name}: {error if isinstance(error, ValueError) else 'Network request failed'}"
                )
    if failed:
        raise typer.Exit(1)


def selected_projects(data: dict, repo: str | None, all_repos: bool) -> list[dict]:
    if repo and all_repos:
        raise ValueError("Use either --repo or --all")
    name = repository_name(repo).lower() if repo else None
    projects = [
        p
        for p in data["repositories"]
        if p.get("enabled", True) and (name is None or f"{p['owner']}/{p['repo']}".lower() == name)
    ]
    if name and not projects:
        raise ValueError("Repository not registered or disabled")
    return projects


@app.command()
@handled
def sync(
    ctx: typer.Context,
    repo: str | None = None,
    all_repos: bool = typer.Option(False, "--all"),
    dry_run: bool = False,
):
    """Back up selected releases; never delete archived versions."""
    data = load(ctx.obj)
    root = Path(data["archive"]["path"]).expanduser().absolute()
    projects = selected_projects(data, repo, all_repos)

    def discover():
        with GitHub() as github:
            plans, messages = build_plans(data, projects, github)
        for message in messages:
            console.print(f"Warning: {message}")
        for plan in plans:
            console.print(
                f"{plan['repository']} {plan['tag']}: {len(plan['assets'])} assets, "
                f"{sum(a['size'] for a in plan['assets'])} bytes"
            )
            for asset in plan["assets"]:
                console.print(f"  {asset['size']} bytes | {asset['path']}")
            for warning in plan["warnings"] + plan["unresolved"]:
                console.print(f"Warning: {warning}")
            if plan["missing_platforms"]:
                console.print(
                    "Not published for platforms: " + ", ".join(plan["missing_platforms"])
                )
        console.print(
            f"Plan: {len(plans)} releases; "
            f"{sum(a['size'] for p in plans for a in p['assets'])} bytes total selected "
            "(upper bound; intact local files are reused)."
        )
        return plans

    if dry_run:
        discover()
        console.print("Dry run: no archive files written or downloaded.")
        return
    with lock(root):
        plans = discover()
        with Downloader() as downloader:
            reports = synchronize(root, plans, downloader)
        failed = False
        for report in reports:
            console.print(
                f"{report['repository']} {report['tag']}: {report['status']}; "
                f"downloaded={report['downloaded']}, reused={report['reused']}"
            )
            for failure in report["failures"]:
                console.print(f"Error: {failure}")
            failed |= report["status"] != "complete"
        if failed:
            raise typer.Exit(1)


def show_local(root: Path, repo: str | None = None) -> bool:
    rows, errors = inspect(root, repository_name(repo) if repo else None)
    console.print(f"Archived releases: {len(rows)}")
    for row in rows:
        console.print(f"{row['repository']} {row['tag']} id={row['release_id']} {row['status']}")
        if row.get("missing_platforms"):
            console.print("  Not published for platforms: " + ", ".join(row["missing_platforms"]))
        for problem in row["problems"]:
            console.print(f"  Error: {problem}")
    for error in errors:
        console.print(f"Error: {error}")
    console.print(
        "SHA-256 validates local integrity; it does not establish publisher authenticity."
    )
    return not errors and all(row["status"] == "complete" for row in rows)


@app.command()
@handled
def status(ctx: typer.Context):
    """Inspect actual archived files and SHA-256 hashes, offline."""
    data = load(ctx.obj)
    root = Path(data["archive"]["path"]).expanduser().absolute()
    if root.exists():
        with lock(root):
            good = show_local(root)
    else:
        good = show_local(root)
    if not good:
        raise typer.Exit(1)


@app.command()
@handled
def verify(
    ctx: typer.Context,
    repo: str | None = None,
    all_repos: bool = typer.Option(False, "--all"),
    rebuild_inventory: bool = False,
    dry_run: bool = False,
):
    """Verify offline; optionally rebuild inventory from local manifests."""
    if repo and all_repos:
        raise ValueError("Use either --repo or --all")
    data = load(ctx.obj)
    root = Path(data["archive"]["path"]).expanduser().absolute()
    if root.exists():
        with lock(root):
            good = show_local(root, repo)
            if rebuild_inventory and not dry_run:
                _, errors = rebuild(root)
                if errors:
                    raise ValueError("Cannot rebuild inventory: invalid manifests")
                console.print("Inventory rebuilt from local manifests.")
    else:
        good = show_local(root, repo)
    if not good:
        raise typer.Exit(1)
