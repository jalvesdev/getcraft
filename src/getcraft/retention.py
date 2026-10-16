"""Fail-closed, explicit retention. No recursive deletion and no sync integration."""

import hashlib
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx

from getcraft.archive import atomic_json, inspect, lock, now, read_manifest, rebuild, safe
from getcraft.download import sha256
from getcraft.selection import ordered
from getcraft.storage import inventory


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def snapshot(root: Path) -> dict:
    """Fingerprint names, identities and contents; never follow symlinks/special files."""
    result = {}
    if not root.exists():
        return result
    safe(root, ".getcraft.lock")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if (
            relative == ".getcraft.lock"
            or relative == ".getcraft"
            or relative.startswith(".getcraft/")
        ):
            continue  # Audit records are the only files our apply phase adds.
        safe(root, relative)
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("Special archive file rejected")
        result[relative] = [
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            sha256(path) if path.is_file() else None,
        ]
    return result


def coverage(manifest: dict) -> set[tuple[str, str, str]]:
    return {
        (a["platform"], a["architecture"], a["format"])
        for a in manifest["assets"]
        if a["platform"] != "metadata"
    }


def managed_files(root: Path, manifest: dict) -> list[dict]:
    base = f"{manifest['repository']}/{manifest['tag']}"
    directory = safe(root, base)
    expected = {f"{base}/manifest.json"}
    for asset in manifest["assets"]:
        platform, architecture = asset["platform"], asset["architecture"]
        layout = (
            f"{base}/metadata/{asset['name']}"
            if platform == "metadata"
            else f"{base}/{platform}/{architecture}/{asset['name']}"
        )
        if asset["path"] != layout:
            raise ValueError("Noncanonical managed asset path")
        safe(root, layout)
        expected.add(layout)
    if manifest.get("readme_sha256"):
        readme = safe(root, f"{base}/README.md")
        if not readme.is_file() or sha256(readme) != manifest["readme_sha256"]:
            raise ValueError("Generated README modified or missing")
        expected.add(f"{base}/README.md")
    expected_dirs = {base}
    for relative in expected:
        parent = Path(relative).parent
        while parent.as_posix() != base:
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    actual = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(root).as_posix()
        safe(root, relative)
        if path.is_file():
            actual.add(relative)
        elif not path.is_dir() or relative not in expected_dirs:
            raise ValueError("Unknown directory inside release; preserved")
    if actual != expected:
        raise ValueError("Unknown or missing release files; preserved")
    # Include content hashes in the auditable plan, manifest removed last.
    return [
        {"path": p, "size": safe(root, p).stat().st_size, "sha256": sha256(safe(root, p))}
        for p in sorted(expected, key=lambda p: (p.endswith("/manifest.json"), p))
    ]


def prepare(root: Path, config: dict, projects: list[dict], github) -> dict:
    before = snapshot(root)
    rows = inventory(root)  # Missing/corrupt index must be explicitly rebuilt first.
    if not safe(root, "inventory.json").is_file():
        raise ValueError("Inventory missing; run verify --rebuild-inventory first")
    verified, errors = inspect(root)
    if errors:
        raise ValueError("Invalid archive manifests: " + "; ".join(errors))
    actual = {(r["repository"].lower(), r["release_id"]): r for r in verified}
    indexed = {(r["repository"].lower(), r["release_id"]): r for r in rows}
    if len(actual) != len(verified) or len(indexed) != len(rows) or actual.keys() != indexed.keys():
        raise ValueError("Inventory differs from manifests; rebuild before pruning")
    if any(
        indexed[key]["status"] != actual[key]["status"]
        or ("tag" in indexed[key] and indexed[key]["tag"] != actual[key]["tag"])
        for key in actual
    ):
        raise ValueError("Inventory differs from file verification; rebuild before pruning")
    candidates, kept, skipped, sources = [], [], [], {}
    for project in projects:
        name = f"{project['owner']}/{project['repo']}"
        remote = github.releases(name)  # API errors abort the whole plan without deletion.
        sources[name] = digest(remote)
        stable, warnings = ordered(remote)
        skipped.extend(f"{name}: {warning}" for warning in warnings)
        remote_by_id = {r["id"]: r for r in stable}
        local = [r for r in verified if r["repository"].lower() == name.lower()]
        # Any incomplete managed release makes this project ineligible for deletion.
        if any(r["status"] != "complete" for r in local):
            skipped.append(f"{name}: incomplete or corrupt backup; nothing pruned")
            continue
        manifests = {}
        for row in local:
            manifest = read_manifest(safe(root, row["manifest"]))
            upstream = remote_by_id.get(manifest["release_id"])
            if upstream and upstream["tag_name"] == manifest["tag"]:
                manifests[manifest["release_id"]] = manifest
            else:
                skipped.append(
                    f"{name} {manifest['tag']}: not currently published stable; preserved"
                )
        ranked = [manifests[r["id"]] for r in stable if r["id"] in manifests]
        limit = project.get("keep_versions", config["archive"]["keep_versions"])
        newest = ranked[:limit]
        kept.extend(
            {"repository": name, "tag": m["tag"], "reason": "verified retention window"}
            for m in newest
        )
        pins = set(project.get("pinned_versions", []))
        for manifest in ranked[limit:]:
            label = f"{name} {manifest['tag']}"
            if manifest["tag"] in pins:
                kept.append({"repository": name, "tag": manifest["tag"], "reason": "pinned"})
                continue
            if (
                len(newest) < limit
                or not coverage(manifest)
                or any(not coverage(manifest) <= coverage(m) for m in newest)
            ):
                skipped.append(
                    f"{label}: insufficient complete replacements with matching coverage"
                )
                continue
            try:
                files = managed_files(root, manifest)
                # Replacement manifests with extra unknown files are also ineligible as evidence.
                for replacement in newest:
                    managed_files(root, replacement)
            except ValueError as error:
                skipped.append(f"{label}: {error}")
                continue
            candidates.append(
                {
                    "repository": name,
                    "tag": manifest["tag"],
                    "release_id": manifest["release_id"],
                    "files": files,
                    "bytes": sum(f["size"] for f in files),
                    "reason": f"outside newest {limit} complete stable releases; equivalent coverage verified",
                }
            )
    after = snapshot(root)
    if before != after:
        raise ValueError("Archive changed during planning; aborting")
    plan = {
        "schema_version": 1,
        "root": str(root),
        "config_hash": digest(config),
        "snapshot": before,
        "sources": sources,
        "candidates": candidates,
        "kept": kept,
        "skipped": skipped,
    }
    plan["plan_id"] = digest(plan)
    return plan


def apply(root: Path, config: dict, projects: list[dict], plan: dict, github) -> dict:
    """Re-plan under the exclusive lock; no arbitrary user-supplied deletion list is trusted."""
    with lock(root):
        fresh = prepare(root, config, projects, github)
        if plan != fresh:
            raise ValueError("Archive, configuration or source changed since planning; aborting")
        audit_path = safe(root, f".getcraft/prune/{uuid4().hex}.json")
        audit = {
            "schema_version": 1,
            "started_at": now(),
            "status": "prepared",
            "plan": plan,
            "removed": [],
        }
        atomic_json(audit_path, audit)  # An audit write failure must precede any deletion.
        expected = dict(plan["snapshot"])
        try:
            for candidate in plan["candidates"]:
                if (
                    digest(github.releases(candidate["repository"]))
                    != plan["sources"][candidate["repository"]]
                ):
                    raise ValueError("Source changed or unavailable before deletion; aborting")
                if snapshot(root) != expected:
                    raise ValueError("Archive changed before deletion; aborting")
                # Rehash all retained replacements, pins and candidates before each release.
                files = candidate["files"]
                for item in files:
                    path = safe(root, item["path"])
                    if path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                        raise ValueError("Planned file changed; aborting")
                for item in files:
                    path = safe(root, item["path"])
                    # Safe paths and exact hashes are rechecked immediately before unlink.
                    if path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                        raise ValueError("Planned file changed before unlink; aborting")
                    path.unlink()
                    audit["removed"].append(item)
                base = safe(root, f"{candidate['repository']}/{candidate['tag']}")
                directories = [p for p in base.rglob("*") if p.is_dir()]
                for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                    safe(root, directory.relative_to(root).as_posix()).rmdir()
                base.rmdir()
                # Compare all other entries to their pre-delete fingerprint; only our deleted
                # directory ancestors may have a changed timestamp/size.
                deleted_base = f"{candidate['repository']}/{candidate['tag']}"
                current = snapshot(root)
                survivors = {
                    k: v
                    for k, v in expected.items()
                    if k != deleted_base and not k.startswith(deleted_base + "/")
                }
                ancestors = {
                    str(Path(deleted_base).parent.as_posix()),
                    str(Path(deleted_base).parent.parent.as_posix()),
                }
                for key in ancestors:
                    if key in survivors and key in current:
                        survivors[key] = current[key]
                if current != survivors:
                    raise ValueError("Archive changed during deletion; stopping")
                expected = current
                atomic_json(audit_path, audit)
            _, errors = rebuild(root)
            if errors:
                raise ValueError("Inventory reconstruction failed after pruning")
            audit["status"] = "complete"
        except (ValueError, OSError, httpx.HTTPError):
            audit["status"] = "interrupted"
            atomic_json(audit_path, audit)
            raise
        finally:
            audit["finished_at"] = now()
            atomic_json(audit_path, audit)
        return {
            "removed_releases": len(plan["candidates"]),
            "removed_bytes": sum(c["bytes"] for c in plan["candidates"]),
            "audit": audit_path.relative_to(root).as_posix(),
        }
