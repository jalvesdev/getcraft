"""Application adapters. No widget dependencies or alternate backup rules."""

from copy import deepcopy
from pathlib import Path

from getcraft.archive import inspect, lock, read_manifest, safe, segment
from getcraft.config import load, validate
from getcraft.configuration import edit_load, persist, target
from getcraft.github import GitHub
from getcraft.planning import estimate
from getcraft.registry import change, register
from getcraft.reports import collect
from getcraft.selection import ordered, plan_release


def root_of(config):
    return Path(config["archive"]["path"]).expanduser().absolute()


def projects(config, name=None):
    rows = [p for p in config["repositories"] if p.get("enabled", True)]
    if name:
        rows = [p for p in rows if f"{p['owner']}/{p['repo']}" == name]
        if not rows:
            raise ValueError("Repository not registered or disabled")
    return rows


def save_settings(path, data, baseline):
    validate(data)
    # Lock the old archive as well when redirecting new backups to a different root.
    try:
        old = load(path)
    except (ValueError, KeyError, TypeError):
        old = data  # Explicit validated repair; never silently reset a broken config.
    if root_of(old) != root_of(data):
        with lock(root_of(old)):
            persist(path, data, False, baseline)
    else:
        persist(path, data, False, baseline)


def registry_edit(path, action, name):
    data, baseline = edit_load(path)
    if action == "add":
        with GitHub() as github:
            register(data, name, github)
    else:
        change(data, name, action)
    save_settings(path, data, baseline)
    return f"{action}: {name}. Existing backups preserved."


def toggle_pin(path, name, tag):
    data, baseline = edit_load(path)
    segment(tag)
    project = target(data, name)
    tags = set(project.get("pinned_versions", []))
    tags.remove(tag) if tag in tags else tags.add(tag)
    project["pinned_versions"] = sorted(tags)
    save_settings(path, data, baseline)
    return "Protection updated; no files deleted."


def catalog(path):
    data = load(path)
    return collect(root_of(data), data)


def releases(path, name):
    data = load(path)
    project = target(data, name)
    with GitHub() as github:
        rows, warnings = ordered(github.releases(name), data["archive"]["include_prereleases"])
    lines = list(warnings)
    for row in rows:
        plan = plan_release(data, project, row)
        transfer = estimate(root_of(data), plan)
        lines.append(f"{plan['tag']}: estimated download {transfer['download_bytes']:,} bytes")
        lines.extend(
            f"{a['decision'].upper()} {a['name']} — {a['reason']}" for a in plan["asset_decisions"]
        )
        lines.extend(plan["warnings"])
    return "\n".join(lines) or "No eligible releases."


def verify(path, name=None):
    root = root_of(load(path))
    if root.exists():
        with lock(root):
            rows, errors = inspect(root, name)
    else:
        rows, errors = inspect(root, name)
    lines = [f"{r['repository']} {r['tag']}: {r['status']}" for r in rows]
    lines.extend(p for r in rows for p in r["problems"])
    lines.extend(errors)
    return "\n".join(lines) or "No archived versions to verify."


def instructions(path, release):
    root = root_of(load(path))
    manifest = read_manifest(safe(root, release["manifest"]))
    from getcraft.reports import installation_readme

    return installation_readme(deepcopy(manifest))


def preview_operation(path, operation, name=None):
    from getcraft.configuration import config_fingerprint
    from getcraft.retention import prepare
    from getcraft.sync import build_plans

    data, baseline = edit_load(path)
    root = root_of(data)
    selected = projects(data, name)
    known = {}
    with GitHub() as github:
        if operation == "retention":
            plan = prepare(root, data, selected, github)
            lines = [f"Prune plan {plan['plan_id']}: simulation only"]
            for candidate in plan["candidates"]:
                lines.append(
                    f"{candidate['repository']} {candidate['tag']}: {candidate['bytes']:,} bytes — {candidate['reason']}"
                )
                lines.extend(f"{f['path']} | {f['size']:,} bytes" for f in candidate["files"])
            lines.extend("Preserved: " + reason for reason in plan["skipped"])
            lines.append(f"Recoverable: {sum(c['bytes'] for c in plan['candidates']):,} bytes")
            payload = plan
            actionable = bool(plan["candidates"])
        else:
            payload, messages = build_plans(data, selected, github, known)
            lines = list(messages)
            estimated = reused = 0
            for plan in payload:
                transfer = estimate(root, plan)
                estimated += transfer["download_bytes"]
                reused += transfer["reused_bytes"]
                lines.append(f"{plan['repository']} {plan['tag']}")
                lines.extend(
                    f"{d['decision'].upper()} {d['name']} ({d['size']:,} bytes): {d['reason']}"
                    for d in plan["asset_decisions"]
                )
                lines.extend(plan["warnings"] + transfer["problems"])
            lines.append(
                f"Estimated download: {estimated:,} bytes; reusable: {reused:,} bytes; {len(payload)} releases."
            )
            actionable = bool(payload)
    if config_fingerprint(path) != baseline:
        raise ValueError("Configuration changed while planning; preview again")
    return dict(
        payload=payload,
        known=known,
        config=data,
        baseline=baseline,
        name=name,
        text="\n".join(lines),
        actionable=actionable,
    )


def apply_operation(path, operation, preview, cancel, progress):
    from getcraft.configuration import config_fingerprint
    from getcraft.download import Downloader
    from getcraft.reports import record_sync
    from getcraft.retention import apply
    from getcraft.sync import synchronize

    if config_fingerprint(path) != preview["baseline"]:
        raise ValueError("Configuration changed after preview; preview again")
    data = load(path)
    root = root_of(data)
    selected = projects(data, preview["name"])
    if operation == "retention":
        with GitHub() as github:

            class ReviewedSource:
                def releases(self, name):
                    if config_fingerprint(path) != preview["baseline"]:
                        raise ValueError("Configuration changed; preview again")
                    result = github.releases(name)
                    if config_fingerprint(path) != preview["baseline"]:
                        raise ValueError("Configuration changed; preview again")
                    return result

            result = apply(root, data, selected, preview["payload"], ReviewedSource())
        return f"Removed {result['removed_releases']} releases; {result['removed_bytes']:,} bytes. Audit: {result['audit']}"
    with lock(root):
        if config_fingerprint(path) != preview["baseline"]:
            raise ValueError("Configuration changed; preview again")
        if cancel.is_set():
            return "Cancelled before download; no files downloaded."
        # Asset identity and selection come from the explicit preview. The existing
        # sync service revalidates every prior manifest and file before use.
        processed = 0
        total = sum(len(p["assets"]) for p in preview["payload"])

        def completed(asset, outcome):
            nonlocal processed
            processed += 1
            progress(
                dict(
                    name=asset["name"],
                    bytes=asset["size"] if outcome != "failed" else 0,
                    size=asset["size"],
                    outcome=outcome,
                    processed=processed,
                    total=total,
                )
            )

        with Downloader(cancel=cancel, progress=progress, completed=completed) as downloader:
            results = synchronize(root, deepcopy(preview["payload"]), downloader)
        record_sync(root, preview["known"], results)
    lines = ["Cancelled safely." if cancel.is_set() else "Synchronization finished."]
    for plan in preview["payload"]:
        lines.extend(
            f"{d['decision'].upper()} {d['name']}: {d['reason']}"
            for d in plan["asset_decisions"]
            if d["decision"] != "selected"
        )
    for row in results:
        lines.append(
            f"{row['repository']} {row['tag']}: {row['status']}; downloaded={row['downloaded']}, reused={row['reused']}"
        )
        lines.extend(row["failures"])
    return "\n".join(lines)
