"""GetCraft command line interface."""

from functools import wraps
from pathlib import Path

import httpx
import typer
from rich.console import Console

from getcraft.config import default_path, load, save
from getcraft.github import GitHub, repository_name
from getcraft.selection import classify, ordered
from getcraft.storage import inventory, state

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
    """Inspect official releases without downloading installers."""
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


@app.command()
@handled
def status(ctx: typer.Context):
    """Read local inventory without contacting GitHub or verifying files."""
    data = load(ctx.obj)
    rows = inventory(Path(data["archive"]["path"]))
    console.print(
        f"Registered repositories: {len(data['repositories'])}; inventory releases: {len(rows)}"
    )
    for row in rows:
        console.print(f"{row['repository']} id={row['release_id']} recorded={row['status']}")
    console.print("Inventory states are recorded metadata; file verification is planned for M2.")
