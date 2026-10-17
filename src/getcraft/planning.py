"""Read-only disk comparison shared by check, sync and local policy previews."""

from pathlib import Path

from getcraft.archive import file_problem, read_manifest, safe
from getcraft.download import official_sha256


def previous(root: Path, plan: dict) -> dict | None:
    path = safe(root, f"{plan['repository']}/{plan['tag']}/manifest.json")
    if not path.exists():
        return None
    old = read_manifest(path)
    if old["repository"] != plan["repository"] or old["release_id"] != plan["release_id"]:
        raise ValueError("Release tag collision with different stable release ID")
    old_assets = {a["path"]: a for a in old["assets"]}
    for asset in plan["assets"]:
        prior = old_assets.get(asset["path"])
        if prior and any(
            prior.get(key) != asset.get(key) for key in ("id", "size", "url", "official_digest")
        ):
            raise ValueError(
                "Remote asset identity changed; preserving existing release for review"
            )
    return old


def estimate(root: Path, plan: dict) -> dict:
    result = {
        "selected_bytes": sum(a["size"] for a in plan["assets"]),
        "download_bytes": 0,
        "reused_bytes": 0,
        "assets": [],
        "problems": [],
    }
    try:
        old = previous(root, plan)
    except (ValueError, OSError) as error:
        result["problems"].append(str(error))
        result["download_bytes"] = result["selected_bytes"]
        result["assets"] = [
            {"id": a["id"], "state": "manual_review", "reason": str(error)} for a in plan["assets"]
        ]
        return result
    priors = {a["path"]: a for a in old["assets"]} if old else {}
    for asset in plan["assets"]:
        prior = priors.get(asset["path"])
        path = safe(root, asset["path"])
        candidate = {
            **asset,
            "sha256": prior.get("sha256")
            if prior
            else official_sha256(asset.get("official_digest")),
            "status": "verified",
        }
        if prior and prior.get("published_sha256"):
            candidate["published_sha256"] = prior["published_sha256"]
        problem = file_problem(root, candidate)
        state = (
            "present"
            if problem is None
            else "missing"
            if not path.is_file()
            else "corrupt"
            if prior
            else "untracked"
        )
        result["assets"].append({"id": asset["id"], "state": state, "reason": problem})
        result["reused_bytes" if state == "present" else "download_bytes"] += asset["size"]
    return result


def local_selection(config: dict, project: dict, manifest: dict, root: Path | None = None) -> dict:
    from getcraft.selection import plan_release

    remote = {
        "id": manifest["release_id"],
        "tag_name": manifest["tag"],
        "published_at": manifest.get("published_at"),
        "assets": [
            {
                "id": a["id"],
                "name": a["name"],
                "size": a["size"],
                "browser_download_url": a["url"],
                "digest": a.get("official_digest"),
            }
            for a in manifest["assets"]
        ],
    }
    owner, repo = manifest["repository"].split("/")
    preview = plan_release(config, {"owner": owner, "repo": repo, **project}, remote)
    installers = [a for a in preview["assets"] if a["platform"] != "metadata"]
    state = (
        "no_installers_selected"
        if not installers
        else "needs_review"
        if preview["unresolved"]
        else "selected"
    )
    if state == "selected" and root is not None:
        priors = {a["id"]: a for a in manifest["assets"]}
        state = (
            "complete"
            if all(file_problem(root, priors[a["id"]]) is None for a in preview["assets"])
            else "incomplete"
        )
    return {
        "scope": "current preferences applied to archived assets only; no remote query",
        "state": state,
        "selected_bytes": preview["selected_bytes"],
        "decisions": preview["asset_decisions"],
    }
