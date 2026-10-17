"""Conservative sync orchestration; no deletion or retention operations."""

from pathlib import Path

from getcraft.archive import (
    atomic_json,
    file_problem,
    now,
    read_manifest,
    rebuild,
    safe,
)
from getcraft.download import DownloadCancelled, Downloader, checksums, official_sha256
from getcraft.planning import previous
from getcraft.reports import write_readme
from getcraft.selection import ordered, plan_release


def build_plans(
    config: dict, projects: list[dict], github, known: dict | None = None
) -> tuple[list[dict], list[str]]:
    plans, messages = [], []
    for project in projects:
        name = f"{project['owner']}/{project['repo']}"
        remote = github.releases(name)
        releases, warnings = ordered(remote, config["archive"]["include_prereleases"])
        if known is not None:
            stable, _ = ordered(remote)
            latest = stable[0] if stable else None
            known[name] = {
                "observed_at": now(),
                "latest": {
                    "tag": latest["tag_name"],
                    "release_id": latest["id"],
                    "published_at": latest.get("published_at"),
                }
                if latest
                else None,
            }
        messages.extend(f"{name}: {w}" for w in warnings)
        known_ids = set()
        root = Path(config["archive"]["path"]).expanduser().absolute()
        project_dir = safe(root, name)
        if project_dir.exists():
            for path in project_dir.glob("*/manifest.json"):
                safe(root, path.relative_to(root).as_posix())
                known_ids.add(read_manifest(path)["release_id"])
        remote_ids = {r["id"] for r in releases}
        for missing_id in sorted(known_ids - remote_ids):
            messages.append(
                f"{name}: archived release {missing_id} no longer eligible/published; preserved"
            )
        count = 0
        limit = project.get("keep_versions", config["archive"]["keep_versions"])
        for release in releases:
            if count >= limit and release["id"] not in known_ids:
                continue
            plan = plan_release(config, project, release)
            if not any(a["platform"] != "metadata" for a in plan["assets"]):
                messages.append(f"{name} {plan['tag']}: no eligible installers")
                messages.extend(plan["unresolved"])
                messages.extend(
                    f"{d['decision'].upper()} {d['name']}: {d['reason']}"
                    for d in plan["asset_decisions"]
                )
                continue
            plans.append(plan)
            count += 1
    return plans, messages


def is_checksum(asset: dict) -> bool:
    name = asset["name"].lower()
    return (
        asset["platform"] == "metadata"
        and not name.endswith((".sig", ".asc", ".minisig", ".sign", ".signature"))
        and ("sha256" in name or "checksum" in name)
    )


def sync_release(root: Path, plan: dict, downloader: Downloader) -> dict:
    old = previous(root, plan)
    priors = {a["path"]: a for a in old["assets"]} if old else {}
    # Resolve all paths before any download, so a symlink cannot redirect metadata writes.
    for asset in plan["assets"]:
        safe(root, asset["path"])
    if old is None:
        for asset in plan["assets"]:
            if safe(root, asset["path"]).exists() and not official_sha256(
                asset.get("official_digest")
            ):
                raise ValueError(
                    "Untracked existing file without official digest; manual review required"
                )
        # Journal pending identity before publishing any files, allowing safe restart after a crash.
        atomic_json(safe(root, f"{plan['repository']}/{plan['tag']}/manifest.json"), plan)
    published = {}
    checksum_failed = False
    downloaded = reused = 0
    failures = []
    assets = sorted(plan["assets"], key=lambda a: a["platform"] != "metadata")
    cancelled = False
    for asset in assets:
        was_downloaded = downloaded
        if cancelled:
            break
        prior = priors.get(asset["path"])
        if prior:
            asset["sha256"] = prior.get("sha256")
            asset["archived_at"] = prior.get("archived_at")
            if prior.get("published_sha256"):
                asset["published_sha256"] = prior["published_sha256"]
        try:
            expected = published.get(asset["name"])
            if (
                prior
                and prior.get("published_sha256")
                and expected
                and prior["published_sha256"] != expected
            ):
                raise ValueError("Published checksum changed; preserving local file for review")
            if expected:
                asset["published_sha256"] = expected
            if checksum_failed and asset["platform"] != "metadata":
                raise ValueError("Checksum metadata failed; binary download blocked")
            target = safe(root, asset["path"])
            # Check the current official and published digest as well as prior local SHA-256.
            candidate = {
                **asset,
                "sha256": prior.get("sha256") if prior else None,
                "status": "verified",
            }
            if prior and file_problem(root, candidate) is None:
                asset.update(
                    sha256=prior["sha256"], status="verified", archived_at=prior["archived_at"]
                )
                reused += 1
            else:
                expected = (
                    expected
                    or official_sha256(asset.get("official_digest"))
                    or (prior.get("sha256") if prior else None)
                )
                # Orphan files without known digests cannot be silently replaced/adopted.
                digest = downloader.fetch(
                    asset, target, expected, repair=bool(prior and file_problem(root, prior))
                )
                asset.update(sha256=digest, status="verified", archived_at=now())
                downloaded += 1
            if is_checksum(asset):
                entries = checksums(target)
                if not entries:
                    plan["warnings"].append(
                        f"{asset['name']}: unrecognized SHA-256 checksum format"
                    )
                for name, digest in entries.items():
                    if name in published and published[name] != digest:
                        raise ValueError("Conflicting published checksum files")
                    published[name] = digest
        except DownloadCancelled:
            cancelled = True
            failures.append("Synchronization cancelled; pending files can be retried")
            # Preserve a prior record even when cancellation occurs during repair.
            if prior:
                asset.update(prior)
            break
        except (ValueError, OSError) as error:
            asset["status"] = "failed"
            asset["error"] = str(error)
            failures.append(f"{asset['name']}: {error}")
            if asset["platform"] == "metadata":
                checksum_failed = True
        if getattr(downloader, "completed", None):
            outcome = (
                "failed"
                if asset["status"] == "failed"
                else "downloaded"
                if downloaded > was_downloaded
                else "reused"
            )
            downloader.completed(asset, outcome)
    if cancelled:
        for asset in assets:
            prior = priors.get(asset["path"])
            if prior and asset["status"] != "verified" and not asset.get("error"):
                asset.update(prior)
    # Also validate checksum/signature assets referenced by a later checksum document.
    for asset in assets:
        digest = published.get(asset["name"])
        if digest:
            asset["published_sha256"] = digest
            if asset["status"] == "verified" and asset["sha256"] != digest:
                asset.update(status="failed", error="Published SHA-256 mismatch")
                failures.append(f"{asset['name']}: published SHA-256 mismatch")
    # Preserve records for previously archived assets removed from the selection policy.
    selected_paths = {a["path"] for a in assets}
    assets.extend({**a, "required": False} for p, a in priors.items() if p not in selected_paths)
    required = [a for a in assets if a.get("required", True)]
    plan["assets"] = assets
    complete = (
        any(a["platform"] != "metadata" for a in required)
        and all(a["status"] == "verified" for a in required)
        and not plan["unresolved"]
    )
    plan["status"] = (
        "complete"
        if complete
        else ("partial" if any(a["status"] == "verified" for a in required) else "failed")
    )
    plan["archived_at"] = now()
    plan["warnings"] = list(dict.fromkeys(plan["warnings"]))
    if old and old.get("readme_sha256"):
        plan["readme_sha256"] = old["readme_sha256"]
    write_readme(root, plan)
    atomic_json(safe(root, f"{plan['repository']}/{plan['tag']}/manifest.json"), plan)
    return {
        "repository": plan["repository"],
        "tag": plan["tag"],
        "status": plan["status"],
        "downloaded": downloaded,
        "reused": reused,
        "failures": failures,
    }


def synchronize(root: Path, plans: list[dict], downloader: Downloader) -> list[dict]:
    reports = []
    for plan in plans:
        if getattr(downloader, "cancel", None) is not None and downloader.cancel.is_set():
            break
        try:
            reports.append(sync_release(root, plan, downloader))
        except (ValueError, OSError) as error:
            reports.append(
                {
                    "repository": plan["repository"],
                    "tag": plan["tag"],
                    "status": "failed",
                    "downloaded": 0,
                    "reused": 0,
                    "failures": [str(error)],
                }
            )
    rows, errors = rebuild(root)
    if errors:
        raise ValueError("Inventory reconstruction failed: " + "; ".join(errors))
    actual = {(row["repository"], row["tag"]): row for row in rows}
    for report in reports:
        row = actual.get((report["repository"], report["tag"]))
        if report["status"] == "complete" and row and row["status"] != "complete":
            report["status"] = row["status"]
            report["failures"].extend(row["problems"])
    return reports
