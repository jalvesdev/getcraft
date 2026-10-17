"""Reviewable configuration CLI; suggestions do not mutate preferences implicitly."""

import json

import typer

from getcraft.configuration import (
    config_fingerprint as config_fingerprint,
)
from getcraft.configuration import (
    edit_load,
    parse_list,
    persist,
    target,
)
from getcraft.preferences import (
    ARCHITECTURES,
    PLATFORM_FORMATS,
    PLATFORMS,
    detect,
    normalize_architecture,
    normalize_format,
    policy,
    validate_preferences,
)


def register(app, handled, console):
    commands = typer.Typer(
        no_args_is_help=True, help="Inspect, suggest and edit archive selection preferences."
    )
    app.add_typer(commands, name="config")

    @commands.command("show")
    @handled
    def show(ctx: typer.Context, repo: str | None = None):
        """Show stored configuration and effective policies without writing files."""
        data, baseline = edit_load(ctx.obj)
        project = target(data, repo) if repo else {}
        result = {
            "config_path": str(ctx.obj),
            "effective": policy(data, project),
            "stored": data if repo is None else project,
        }
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))

    @commands.command("detect")
    @handled
    def detect_command(
        ctx: typer.Context,
        apply: bool = False,
        yes: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
    ):
        """Suggest the host's targets; --apply requires confirmation or --yes."""
        detected = detect()
        typer.echo(json.dumps(detected, ensure_ascii=False, indent=2))
        if yes and not apply:
            raise ValueError("--yes requires --apply")
        if interactive and not apply:
            raise ValueError("--interactive requires --apply")
        if not apply:
            return
        suggested = detected["suggested"]
        if interactive:
            suggested["platforms"] = parse_list(
                typer.prompt("Platforms", default=",".join(suggested["platforms"])), PLATFORMS
            )
            suggested["architectures"] = parse_list(
                typer.prompt("Architectures", default=",".join(suggested["architectures"])),
                ARCHITECTURES,
                normalize_architecture,
            )
            suggested["formats_by_platform"] = {
                p: parse_list(
                    typer.prompt(
                        f"{p} formats",
                        default=",".join(
                            suggested["formats_by_platform"].get(p, PLATFORM_FORMATS[p])
                        ),
                    ),
                    PLATFORM_FORMATS[p],
                    normalize_format,
                )
                for p in suggested["platforms"]
            }
        if not suggested["platforms"] or not suggested["architectures"]:
            raise ValueError("Unsupported host; choose targets explicitly with config commands")
        if not yes and not dry_run:
            typer.confirm(
                "Apply these suggested global preferences? Repository overrides stay in effect.",
                abort=True,
            )
        data, baseline = edit_load(ctx.obj)
        selection = data.setdefault("selection", {})
        selection.update({k: v for k, v in suggested.items() if k != "formats_by_platform"})
        selection.setdefault("formats_by_platform", {}).update(suggested["formats_by_platform"])
        validate_preferences(data["selection"])
        persist(ctx.obj, data, dry_run, baseline)
        console.print(
            "Would apply preferences"
            if dry_run
            else "Preferences saved; existing archives preserved"
        )

    def change_list(ctx, key, values, repo, reset, interactive, dry_run):
        data, baseline = edit_load(ctx.obj)
        settings = target(data, repo)
        effective = policy(data, settings if repo else {})
        if reset and (values is not None or interactive):
            raise ValueError("--reset cannot be combined with --set or --interactive")
        if interactive:
            if values is not None:
                raise ValueError("Use --set or --interactive")
            values = typer.prompt(key, default=",".join(effective[key]))
        if values is None and not reset:
            typer.echo(json.dumps({"scope": repo or "global", key: effective[key]}, indent=2))
            return
        if reset:
            settings.pop(key, None)
        else:
            allowed = PLATFORMS if key == "platforms" else ARCHITECTURES
            settings[key] = parse_list(
                values, allowed, normalize_architecture if key == "architectures" else str.lower
            )
        validate_preferences(settings)
        persist(ctx.obj, data, dry_run, baseline)
        console.print(
            ("Would save " if dry_run else "Saved ")
            + key
            + ": "
            + ", ".join(policy(data, settings if repo else {})[key])
        )

    @commands.command("platforms")
    @handled
    def platforms(
        ctx: typer.Context,
        values: str | None = typer.Option(None, "--set"),
        repo: str | None = None,
        reset: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
    ):
        """Show/set target OSes; repository --reset restores global inheritance."""
        change_list(ctx, "platforms", values, repo, reset, interactive, dry_run)

    @commands.command("architectures")
    @handled
    def architectures(
        ctx: typer.Context,
        values: str | None = typer.Option(None, "--set"),
        repo: str | None = None,
        reset: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
    ):
        """Show/set x86_64, arm64 or universal; AMD64/AArch64 aliases are accepted."""
        change_list(ctx, "architectures", values, repo, reset, interactive, dry_run)

    @commands.command("formats")
    @handled
    def formats(
        ctx: typer.Context,
        platform: str | None = None,
        values: str | None = typer.Option(None, "--set"),
        repo: str | None = None,
        reset: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
    ):
        """Show formats per OS; --platform OS --set FORMAT,... edits one platform."""
        data, baseline = edit_load(ctx.obj)
        settings = target(data, repo)
        effective = policy(data, settings if repo else {})
        if platform is not None and platform not in PLATFORMS:
            raise ValueError("Unsupported platform")
        if reset and (values is not None or interactive):
            raise ValueError("--reset cannot be combined with --set or --interactive")
        if values is None and not reset and not interactive:
            typer.echo(
                json.dumps(
                    effective["formats_by_platform"]
                    if platform is None
                    else {platform: effective["formats_by_platform"][platform]},
                    indent=2,
                )
            )
            return
        if platform is None:
            raise ValueError("--platform is required when changing formats")
        if interactive:
            if values is not None:
                raise ValueError("Use --set or --interactive")
            values = typer.prompt(
                f"{platform} formats", default=",".join(effective["formats_by_platform"][platform])
            )
        mapping = settings.setdefault("formats_by_platform", {})
        if reset:
            mapping.pop(platform, None)
        else:
            mapping[platform] = parse_list(values, PLATFORM_FORMATS[platform], normalize_format)
        validate_preferences(settings)
        persist(ctx.obj, data, dry_run, baseline)
        console.print(
            ("Would save " if dry_run else "Saved ")
            + platform
            + " formats: "
            + ", ".join(policy(data, settings if repo else {})["formats_by_platform"][platform])
        )
