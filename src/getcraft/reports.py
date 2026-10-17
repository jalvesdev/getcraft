"""Offline installation guidance and portable catalogs. No external resources required."""

import hashlib
import html
import json
import os
import re
import shlex
from pathlib import Path
from urllib.parse import quote

from getcraft.archive import (
    atomic_json,
    atomic_text,
    file_problem,
    inspect,
    now,
    read_manifest,
    safe,
)
from getcraft.download import sha256
from getcraft.planning import local_selection
from getcraft.preferences import policy
from getcraft.storage import inventory


def md(value: object) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", html.escape(str(value)))


def installation_readme(manifest: dict) -> str:
    lines = [
        f"# {md(manifest.get('name', manifest['repository']))} — {md(manifest['version'])}",
        "",
        f"Release: {md(manifest['tag'])}; recorded state: {md(manifest['status'])}.",
        "",
        "## Archived files",
        "",
        "| File | Platform / architecture | Format | State |",
        "| --- | --- | --- | --- |",
    ]
    for asset in manifest["assets"]:
        lines.append(
            f"| {md(asset['name'])} | {md(asset['platform'])} / {md(asset['architecture'])} | {md(asset['format'])} | {md(asset['status'])} |"
        )
    lines += [
        "",
        "## Integrity",
        "",
        "Run `getcraft verify --all` with the archive configuration before installation.",
        "The following recorded SHA-256 values detect corruption; they do not prove publisher authenticity.",
        "Signatures are preserved but are not cryptographically verified by GetCraft.",
        "",
    ]
    for asset in manifest["assets"]:
        if asset.get("sha256"):
            lines += [f"- {md(asset['name'])}: `{asset['sha256']}`"]
    lines += [
        "",
        "## General installation guidance",
        "",
        "Commands below are examples for a compatible target OS, run from the directory containing the named file.",
        "They are documentation only: GetCraft never executes installers.",
        "Only install files whose integrity you have verified; failed/pending files are not usable backups.",
        "",
    ]
    formats = {a["format"] for a in manifest["assets"]}
    if any(a["platform"] == "windows" for a in manifest["assets"]):
        lines += [
            "### Windows",
            "",
            "On a compatible Windows system, open a verified EXE/MSI/MSIX installer and follow its prompts.",
            "An EXE filename alone does not reveal whether it is a complete installer or an online bootstrapper.",
            "Portable ZIP contents and prerequisites must be checked in the upstream documentation.",
            "",
        ]
    if any(a["platform"] == "macos" for a in manifest["assets"]):
        lines += [
            "### macOS",
            "",
            "On a compatible Mac, open a verified DMG in Finder or a PKG in Installer.",
            "Follow the publisher’s instructions; do not bypass Gatekeeper or signature checks.",
            "A DMG/PKG or universal label does not establish minimum OS compatibility.",
            "",
        ]
    if any(a["platform"] == "linux" for a in manifest["assets"]):
        lines += [
            "### Linux",
            "",
            "Choose the matching architecture and distribution. Package-manager installation may require authorization.",
            "",
        ]
    for asset in manifest["assets"]:
        if asset["platform"] != "linux":
            continue
        path = shlex.quote("./" + asset["name"])
        commands = {
            "flatpak": [f"flatpak install --user {path}"],
            "flatpakref": [f"flatpak install --user {path}"],
            "appimage": [f"chmod +x -- {path}", path],
            "rpm": [f"dnf install {path}"],
            "deb": [f"apt install {path}"],
        }.get(asset["format"], [])
        if commands:
            lines += [f"For {md(asset['name'])} ({md(asset['status'])}):", ""]
            lines.extend("    " + command for command in commands)
            lines.append("")
    lines += [
        "## External dependencies and offline limitations",
        "",
        "Application-specific dependencies and minimum OS versions have not been independently verified.",
        "Windows prerequisites, macOS compatibility and Linux library/package dependencies may require external downloads.",
        "A preserved installer is not a guarantee of fully offline installation or compatibility with future OS versions.",
    ]
    if formats & {"flatpak", "flatpakref"}:
        lines += [
            "Flatpak may need external runtimes, extensions and configured remotes, even for a local .flatpak bundle."
        ]
    if "flatpakref" in formats:
        lines += [
            "A .flatpakref is a repository/application reference, not a self-contained installer; network access is normally required."
        ]
    if "appimage" in formats:
        lines += [
            "AppImage may require compatible host libraries/FUSE; exact requirements are not established by its filename."
        ]
    if formats & {"rpm", "deb"}:
        lines += [
            "RPM/DEB packages can require dependency packages not preserved in this archive; package managers may access repositories."
        ]
    lines += [
        "ZIP/tar files are preserved without inspecting their contents. No unverified application-specific commands are provided.",
        "GetCraft cannot determine from a filename whether an installer is a full payload or downloads components online.",
        "Inspect upstream guidance before relying on a file for disaster recovery.",
        "",
    ]
    if manifest.get("missing_platforms"):
        lines += [
            "Not published upstream for requested platforms: "
            + ", ".join(md(p) for p in manifest["missing_platforms"]),
            "",
        ]
    if manifest.get("unresolved") or manifest.get("warnings"):
        lines += ["## Archive warnings", ""]
        lines.extend(
            "- " + md(w) for w in manifest.get("unresolved", []) + manifest.get("warnings", [])
        )
        lines.append("")
    lines += [
        "## Format references (optional online documentation)",
        "",
        "- [Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html)",
        "- [AppImage quickstart](https://docs.appimage.org/introduction/quickstart.html)",
        "- [DNF command reference](https://dnf.readthedocs.io/en/latest/command_ref.html)",
        "- [Ubuntu package management](https://ubuntu.com/server/docs/how-to/software/package-management/)",
        "",
    ]
    return "\n".join(lines)


def write_readme(root: Path, manifest: dict) -> bool:
    """Only replace a README if its exact previous generated hash is recorded."""
    path = safe(root, f"{manifest['repository']}/{manifest['tag']}/README.md")
    if path.exists() and (
        not manifest.get("readme_sha256") or sha256(path) != manifest["readme_sha256"]
    ):
        warning = "README.md is not an unchanged GetCraft-generated file; preserved"
        if warning not in manifest["warnings"]:
            manifest["warnings"].append(warning)
        return False
    text = installation_readme(manifest)
    atomic_text(path, text)
    manifest["readme_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return True


def backfill_readmes(root: Path) -> list[str]:
    rows, errors = inspect(root)
    for row in rows:
        path = safe(root, row["manifest"])
        manifest = read_manifest(path)
        if not write_readme(root, manifest):
            errors.append(f"{row['repository']} {row['tag']}: existing README preserved")
        atomic_json(path, manifest)
    return errors


def read_knowledge(root: Path) -> tuple[dict, list[str]]:
    path = safe(root, ".getcraft/knowledge.json")
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("projects"), dict):
            raise ValueError("Invalid knowledge schema")
        for name, project in data["projects"].items():
            from getcraft.github import repository_name

            if repository_name(name) != name or not isinstance(project, dict):
                raise ValueError("Invalid project knowledge")
            if not isinstance(project.get("results", []), list) or not all(
                isinstance(result, dict) for result in project.get("results", [])
            ):
                raise ValueError("Invalid synchronization results")
            latest = project.get("latest")
            if latest is not None and (
                not isinstance(latest, dict)
                or not isinstance(latest.get("tag"), str)
                or type(latest.get("release_id")) is not int
            ):
                raise ValueError("Invalid latest-known release")
            if any(
                project.get(k) is not None and not isinstance(project[k], str)
                for k in ("last_sync", "observed_at")
            ):
                raise ValueError("Invalid known timestamp")
        return data["projects"], []
    except (ValueError, OSError, AttributeError) as error:
        return {}, [f"Last-known discovery/sync metadata unreadable: {error}"]


def record_sync(root: Path, known: dict, results: list[dict]) -> None:
    projects, _ = read_knowledge(root)
    timestamp = now()
    by_project = {}
    for result in results:
        by_project.setdefault(result["repository"], []).append(result)
    for repository, value in known.items():
        projects[repository] = {
            **projects.get(repository, {}),
            **value,
            "last_sync": timestamp,
            "results": by_project.get(repository, []),
        }
    atomic_json(safe(root, ".getcraft/knowledge.json"), {"schema_version": 1, "projects": projects})


def collect(root: Path, config: dict) -> dict:
    rows, errors = inspect(root)
    known, knowledge_errors = read_knowledge(root)
    errors.extend(knowledge_errors)
    index = safe(root, "inventory.json")
    if rows and not index.exists():
        errors.append("Inventory missing; run verify --rebuild-inventory")
    elif index.exists():
        try:
            inventory(root)
        except (ValueError, OSError) as error:
            errors.append(f"Inventory unreadable; run verify --rebuild-inventory: {error}")
    registered = {f"{p['owner']}/{p['repo']}": p for p in config["repositories"]}
    names = sorted(set(registered) | {r["repository"] for r in rows} | set(known))
    projects = []
    for name in names:
        settings = registered.get(name, {})
        project = {
            "repository": name,
            "monitored": name in registered,
            "enabled": settings.get("enabled", False),
            "selection_policy": policy(config, settings),
            "pinned_versions": settings.get("pinned_versions", []),
            "latest_known": known.get(name, {}).get("latest"),
            "last_observed": known.get(name, {}).get("observed_at"),
            "last_sync": known.get(name, {}).get("last_sync"),
            "sync_results": known.get(name, {}).get("results", []),
            "bytes": 0,
            "releases": [],
        }
        project["problems"] = [
            f"Last sync {result.get('tag', '')}: {message}"
            for result in project["sync_results"]
            if result.get("status") != "complete"
            for message in result.get("failures", ["Incomplete synchronization"])
        ]
        for row in rows:
            if row["repository"] != name:
                continue
            manifest = read_manifest(safe(root, row["manifest"]))
            release = {
                **row,
                "pinned": row["tag"] in project["pinned_versions"],
                "current_selection": local_selection(config, settings, manifest, root),
                "last_remote_selection": manifest.get("asset_decisions"),
                "assets": [],
                "bytes": 0,
                "archived_at": manifest.get("archived_at"),
                "readme": f"{name}/{row['tag']}/README.md"
                if manifest.get("readme_sha256")
                else None,
                "warnings": manifest["warnings"],
                "unresolved": manifest["unresolved"],
            }
            decisions = {d["id"]: d for d in release["current_selection"]["decisions"]}
            for asset in manifest["assets"]:
                target = safe(root, asset["path"])
                size = target.stat().st_size if target.is_file() else 0
                problem = file_problem(root, asset)
                release["assets"].append(
                    {
                        **asset,
                        "actual_bytes": size,
                        "integrity": problem or "verified",
                        "selection": decisions.get(asset["id"]),
                    }
                )
                release["bytes"] += size
            project["releases"].append(release)
        # M2 did not record sync runs; expose archive time separately, never invent a sync time.
        project["latest_archive_time"] = (
            max((r["archived_at"] or "" for r in project["releases"]), default="") or None
        )
        # Account for all regular project files, including metadata and unmanaged files.
        from getcraft.github import repository_name

        repository_name(name)
        directory = safe(root, name)
        for path in directory.rglob("*") if directory.exists() else []:
            safe(root, path.relative_to(root).as_posix())
            if path.is_file():
                project["bytes"] += path.stat().st_size
        projects.append(project)
    total = 0
    if root.exists():
        for path in root.rglob("*"):
            safe(root, path.relative_to(root).as_posix())
            if path.is_file():
                total += path.stat().st_size
    return {
        "schema_version": 1,
        "generated_at": now(),
        "projects": projects,
        "total_bytes": total,
        "problems": errors,
        "space_measure": "logical file bytes, including metadata and unmanaged files; not allocated filesystem blocks",
        "latest_note": "Last successfully observed remote metadata; no network request during report",
        "integrity_note": "Local hashes detect corruption; publisher authenticity and offline installation are not guaranteed",
    }


def render_markdown(data: dict, root: Path, parent: Path) -> str:
    lines = [
        "# GetCraft archive catalog",
        "",
        data["latest_note"],
        "",
        f"Total logical file bytes: {data['total_bytes']}",
        "",
    ]
    for project in data["projects"]:
        latest = project["latest_known"]
        lines += [
            f"## {md(project['repository'])}",
            "",
            f"Monitored: {project['monitored']}; enabled: {project['enabled']}",
            "",
            f"Latest known: {md(latest['tag'] if latest else 'unknown (not queried)')}",
            "",
            "Current preferences: " + md(json.dumps(project["selection_policy"], sort_keys=True)),
            "",
            f"Last sync: {md(project['last_sync'] or 'unknown')}; bytes: {project['bytes']}",
            "",
            "Pinned tags: " + (", ".join(md(t) for t in project["pinned_versions"]) or "none"),
            "",
        ]
        lines.extend("- Sync problem: " + md(p) for p in project["problems"])
        lines.append("")
        for release in project["releases"]:
            lines += [
                f"### {md(release['tag'])} — historical integrity: {release['status']}",
                "",
                "Current selection (archived assets only): "
                + release["current_selection"]["state"],
                "",
            ]
            if release.get("readme"):
                readme_link = quote(
                    os.path.relpath(root / release["readme"], parent).replace(os.sep, "/"), safe="/"
                )
                lines += [f"[Installation instructions]({readme_link})", ""]
            for asset in release["assets"]:
                link = quote(
                    os.path.relpath(root / asset["path"], parent).replace(os.sep, "/"), safe="/"
                )
                lines.append(
                    f"- [{md(asset['name'])}]({link}) — {md(asset['platform'])}/{md(asset['architecture'])}; {md(asset['integrity'])}; {asset['actual_bytes']} bytes; current policy: {md(asset['selection']['decision'])} ({md(asset['selection']['reason'])})"
                )
            if release.get("last_remote_selection"):
                lines += [
                    "",
                    "Last remote selection snapshot (historical policy; not refreshed):",
                    "",
                ]
                lines.extend(
                    f"- {md(d['decision'])} {md(d['name'])}: {md(d['reason'])}; {d['size']} bytes"
                    for d in release["last_remote_selection"]
                )
            lines.extend("- Problem: " + md(p) for p in release["problems"] + release["unresolved"])
            lines.append("")
    lines += ["## Problems", ""]
    lines.extend("- " + md(p) for p in data["problems"])
    lines += ["", data["integrity_note"], ""]
    return "\n".join(lines)


def render_html(data: dict, root: Path, parent: Path) -> str:
    def e(value):
        return html.escape(str(value), quote=True)

    lines = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'\">",
        "<title>GetCraft archive catalog</title>",
        "<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem}table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;text-align:left;padding:.5rem;overflow-wrap:anywhere}section{margin:2rem 0}a{color:#0755a4}</style>",
        "<h1>GetCraft archive catalog</h1>",
        f"<p>{e(data['latest_note'])}</p>",
        f"<p>Total logical file bytes: {data['total_bytes']}</p><nav><ul>",
    ]
    for index, project in enumerate(data["projects"]):
        lines.append(f'<li><a href="#project-{index}">{e(project["repository"])}</a></li>')
    lines.append("</ul></nav>")
    for index, project in enumerate(data["projects"]):
        latest = project["latest_known"]
        lines += [
            f'<section id="project-{index}"><h2>{e(project["repository"])}</h2>',
            f"<p>Monitored: {project['monitored']}; enabled: {project['enabled']}; bytes: {project['bytes']}</p>",
            f"<p>Latest known: {e(latest.get('tag') if latest else 'unknown (not queried)')}; last sync: {e(project['last_sync'] or 'unknown')}</p>",
            "<p>Pinned tags: " + e(", ".join(project["pinned_versions"]) or "none") + "</p>",
            "<p>Current preferences: "
            + e(json.dumps(project["selection_policy"], sort_keys=True))
            + "</p>",
        ]
        for problem in project["problems"]:
            lines.append("<p>Sync problem: " + e(problem) + "</p>")
        for release in project["releases"]:
            lines += [
                f"<h3>{e(release['tag'])} — historical integrity: {e(release['status'])}{' (pinned)' if release['pinned'] else ''}</h3>",
                "<p>Current selection (archived assets only): "
                + e(release["current_selection"]["state"])
                + "</p>",
                "<table><tr><th>File</th><th>Platform / architecture</th><th>Integrity</th><th>Bytes</th></tr>",
            ]
            if release.get("readme"):
                readme_link = quote(
                    os.path.relpath(root / release["readme"], parent).replace(os.sep, "/"), safe="/"
                )
                lines.append(
                    f'<tr><td colspan="4"><a href="{e(readme_link)}">Installation instructions</a></td></tr>'
                )
            for asset in release["assets"]:
                link = quote(
                    os.path.relpath(root / asset["path"], parent).replace(os.sep, "/"), safe="/"
                )
                lines.append(
                    f'<tr><td><a href="{e(link)}">{e(asset["name"])}</a></td><td>{e(asset["platform"])}/{e(asset["architecture"])}</td><td>{e(asset["integrity"])}; current policy: {e(asset["selection"]["decision"])} ({e(asset["selection"]["reason"])})</td><td>{asset["actual_bytes"]}</td></tr>'
                )
            lines.append("</table>")
            if release.get("last_remote_selection"):
                lines.append(
                    "<details><summary>Last remote selection snapshot (historical policy; not refreshed)</summary><ul>"
                )
                lines.extend(
                    f"<li>{e(d['decision'])} {e(d['name'])}: {e(d['reason'])}; {e(d['size'])} bytes</li>"
                    for d in release["last_remote_selection"]
                )
                lines.append("</ul></details>")
            for problem in release["problems"] + release["unresolved"] + release["warnings"]:
                lines.append("<p>Problem/warning: " + e(problem) + "</p>")
        lines.append("</section>")
    for problem in data["problems"]:
        lines.append("<p>Problem: " + e(problem) + "</p>")
    lines += ["<p>" + e(data["integrity_note"]) + "</p>", "</html>"]
    return "\n".join(lines) + "\n"


def render(data: dict, format: str, root: Path, parent: Path) -> str:
    if format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if format == "markdown":
        return render_markdown(data, root, parent)
    if format == "html":
        return render_html(data, root, parent)
    raise ValueError("Unsupported report format; use json, markdown or html")


def write_report(root: Path, relative: str, text: str) -> Path:
    path = safe(root, relative)
    # Catalogs belong at the archive root, never in release/metadata directories.
    if (
        "/" in relative
        or relative in {"inventory.json", ".getcraft.lock"}
        or relative.startswith(".")
    ):
        raise ValueError("Report output must be a non-hidden filename at the archive root")
    registry = safe(root, ".getcraft/reports.json")
    records = json.loads(registry.read_text()) if registry.exists() else {}
    if not isinstance(records, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and re.fullmatch("[a-f0-9]{64}", v)
        for k, v in records.items()
    ):
        raise ValueError("Invalid generated report registry; refusing overwrite")
    if path.exists() and records.get(relative) != sha256(path):
        raise ValueError("Existing report is unmanaged or modified; refusing overwrite")
    atomic_text(path, text)
    records[relative] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    atomic_json(registry, records)
    return path
