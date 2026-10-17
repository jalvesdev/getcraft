"""Conservative release ordering and advisory asset classification."""

import re

from packaging.version import InvalidVersion, Version

from getcraft.preferences import PLATFORM_FORMATS, policy


def version(release: dict) -> Version | None:
    try:
        return Version(release["tag_name"].removeprefix("v"))
    except InvalidVersion:
        return None


def ordered(releases: list[dict], prereleases: bool = False) -> tuple[list[dict], list[str]]:
    eligible = [
        r
        for r in releases
        if not r.get("draft")
        and (prereleases or not (r.get("prerelease") or (version(r) and version(r).is_prerelease)))
    ]
    warnings = []
    if any(version(r) is None for r in eligible):
        warnings.append("Irregular tags: all releases ordered by publication time, then ID")
        eligible.sort(key=lambda r: (r.get("published_at") or "", r["id"]), reverse=True)
    else:
        eligible.sort(
            key=lambda r: (version(r), r.get("published_at") or "", r["id"]), reverse=True
        )
    return eligible, warnings


def classify(filename: str) -> tuple[str, str, str]:
    name = filename.lower()
    if "/" in name or "\\" in name or name in {".", ".."}:
        return "unknown", "unknown", "Unsafe filename; review required"
    if name.endswith((".zsync", ".wixpdb", ".blockmap")):
        return "metadata", "unknown", "Auxiliary update/debug metadata; not an installer"
    if name.endswith((".sig", ".asc", ".minisig", ".sign", ".signature")) or (
        re.search(r"(?:^|[-_.])(?:sha(?:1|224|256|384|512)(?:sums?)?|checksums?)(?:$|[-_.])", name)
        and not name.endswith(
            (
                ".exe",
                ".msi",
                ".msix",
                ".msixbundle",
                ".dmg",
                ".pkg",
                ".deb",
                ".rpm",
                ".appimage",
                ".flatpak",
            )
        )
    ):
        return "metadata", "unknown", "Checksum/signature; preserve with binaries in M2"
    if "source" in name or "src" in re.split(r"[-_.]", name):
        return "source", "unknown", "Source archive; excluded"
    platforms = set()
    for token, os_name in [
        ("windows", "windows"),
        ("win32", "windows"),
        ("win64", "windows"),
        ("win", "windows"),
        ("macos", "macos"),
        ("darwin", "macos"),
        ("osx", "macos"),
        ("linux", "linux"),
        ("freebsd", "freebsd"),
        ("android", "android"),
    ]:
        if re.search(r"(?:^|[-_.])" + token + r"(?=$|[-_.])", name):
            platforms.add(os_name)
    if name.endswith((".exe", ".msi", ".msix", ".msixbundle")):
        platforms.add("windows")
    if name.endswith((".dmg", ".pkg", ".app.zip")):
        platforms.add("macos")
    if name.endswith((".deb", ".rpm", ".appimage", ".flatpak", ".flatpakref")):
        platforms.add("linux")
    archs = set()
    for pattern, arch in [
        (r"(?:^|[-_.])(?:x86[_-]64|amd64|x64)(?=$|[-_.])", "x86_64"),
        (r"(?:^|[-_.])(?:arm64|aarch64)(?=$|[-_.])", "arm64"),
        (r"(?:^|[-_.])universal(?:2)?(?=$|[-_.])", "universal"),
        (r"(?:^|[-_.])(?:x86|i386|i686)(?=$|[-.]|_(?!64))", "x86"),
        (r"(?:^|[-_.])riscv64(?=$|[-_.])", "riscv64"),
    ]:
        if re.search(pattern, name):
            archs.add(arch)
    platform = next(iter(platforms)) if len(platforms) == 1 else "unknown"
    arch = next(iter(archs)) if len(archs) == 1 else "unknown"
    warnings = []
    if len(platforms) > 1:
        warnings.append("Conflicting platform markers")
    if platform == "unknown" or arch == "unknown":
        warnings.append("Ambiguous platform/architecture; review required")
    if name.endswith(".flatpakref"):
        warnings.append("Flatpak reference is a pointer, not a self-contained installer")
    if name.endswith((".zip", ".tar.gz", ".tar.xz", ".tgz")):
        warnings.append("Archive contents not inspected; binary distribution unconfirmed")
    return platform, arch, "; ".join(warnings)


FORMATS = (
    "msixbundle",
    "app.zip",
    "tar.gz",
    "tar.xz",
    "tar.bz2",
    "appimage",
    "flatpakref",
    "flatpak",
    "msix",
    "exe",
    "msi",
    "dmg",
    "pkg",
    "deb",
    "rpm",
    "zip",
    "tgz",
    "sig",
    "asc",
)


def asset_format(name: str) -> str:
    lower = name.lower()
    return next((suffix for suffix in FORMATS if lower.endswith("." + suffix)), "unknown")


# policy remains import-compatible with M2/M3 callers.


def decide_asset(rules: dict, remote: dict) -> dict:
    """Explain every decision, keeping filtering independent from disk integrity."""
    from fnmatch import fnmatchcase

    from getcraft.archive import segment
    from getcraft.download import valid_url

    name = remote["name"]
    platform, architecture, warning = classify(name)
    fmt = asset_format(name)
    result = {
        "id": remote.get("id"),
        "name": name,
        "size": remote.get("size", 0),
        "platform": platform,
        "architecture": architecture,
        "format": fmt,
        "decision": "ignored",
        "reason": "",
        "warning": warning,
    }

    def finish(decision, reason):
        return {**result, "decision": decision, "reason": reason}

    if any(fnmatchcase(name, p) for p in rules["exclude_assets"]):
        return finish("ignored", "explicit exclusion")
    if platform == "source":
        return finish("ignored", "source excluded")
    if name.lower().endswith((".zsync", ".wixpdb", ".blockmap")):
        return finish("ignored", "auxiliary metadata excluded")
    explicit = any(fnmatchcase(name, p) for p in rules["include_assets"])
    try:
        segment(name)
        if name.lower().endswith(".part"):
            raise ValueError("Reserved temporary-file suffix")
        if (
            type(remote.get("id")) is not int
            or type(remote.get("size")) is not int
            or remote["size"] < 0
        ):
            raise ValueError("Invalid asset ID/size")
        valid_url(remote["browser_download_url"])
    except ValueError as error:
        return finish("ambiguous", str(error))
    if platform == "metadata":
        return finish("selected", "verification metadata")
    if "Conflicting platform markers" in warning:
        return finish("ambiguous", "conflicting platform/format evidence; explicit review required")
    if platform != "unknown" and platform not in rules["platforms"]:
        return finish("ignored", "platform not selected")
    if architecture != "unknown" and architecture not in rules["architectures"]:
        return finish("ignored", "architecture not selected")
    if platform != "unknown" and fmt not in rules["formats_by_platform"][platform]:
        # Unknown extensions still need review unless a legacy flat format filter excludes them.
        if fmt != "unknown" or (rules["formats"] and fmt not in rules["formats"]):
            return finish("ignored", "format not selected for platform")
    if (
        platform == "unknown"
        and fmt != "unknown"
        and not any(fmt in rules["formats_by_platform"][p] for p in rules["platforms"])
    ):
        return finish("ignored", "format not selected for any target platform")
    if platform == "unknown" and rules["formats"] and fmt not in rules["formats"]:
        return finish("ignored", "format not selected")
    incompatible = (
        platform != "unknown" and fmt != "unknown" and fmt not in PLATFORM_FORMATS[platform]
    )
    if incompatible:
        return finish("ambiguous", "format conflicts with platform; manual review required")
    if not explicit and (
        platform == "unknown"
        or architecture == "unknown"
        or fmt in {"zip", "app.zip", "tar.gz", "tar.xz", "tar.bz2", "tgz", "unknown"}
    ):
        return finish("ambiguous", "explicit include_assets or exclude_assets rule required")
    if not rules["platforms"] or not rules["architectures"]:
        return finish("ignored", "no target platforms or architectures selected")
    return finish("selected", "explicit inclusion" if explicit else "matches effective preferences")


def plan_release(config: dict, project: dict, release: dict) -> dict:
    from getcraft.archive import segment

    rules = policy(config, project)
    repository = f"{project['owner']}/{project['repo']}"
    segment(release["tag_name"])
    base = f"{repository}/{release['tag_name']}"
    assets, unresolved, warnings, decisions = [], [], [], []
    names, ids = set(), set()
    published = set()
    for remote in release.get("assets", []):
        decision = decide_asset(rules, remote)
        decisions.append(decision)
        name = remote["name"]
        platform, architecture, fmt = (
            decision["platform"],
            decision["architecture"],
            decision["format"],
        )
        if platform in PLATFORM_FORMATS:
            published.add(platform)
        if decision["decision"] == "ambiguous":
            unresolved.append(f"{name!r}: {decision['reason']}")
            continue
        if decision["decision"] == "ignored":
            if decision["reason"] in {"source excluded", "auxiliary metadata excluded"}:
                warnings.append(f"{name}: {decision['reason']}")
            continue
        if name.casefold() in names or remote["id"] in ids:
            raise ValueError("Duplicate asset name or ID; refusing release path collision")
        names.add(name.casefold())
        ids.add(remote["id"])
        path = (
            f"{base}/metadata/{name}"
            if platform == "metadata"
            else f"{base}/{platform}/{architecture}/{name}"
        )
        assets.append(
            {
                "id": remote["id"],
                "name": name,
                "size": remote["size"],
                "url": remote["browser_download_url"],
                "official_digest": remote.get("digest"),
                "platform": platform,
                "architecture": architecture,
                "format": fmt,
                "path": path,
                "sha256": None,
                "status": "pending",
                "required": True,
                "archived_at": None,
            }
        )
        if decision["warning"]:
            warnings.append(f"{name}: {decision['warning']}")
        if remote.get("digest") and not remote["digest"].startswith("sha256:"):
            warnings.append(f"{name}: unsupported official digest; preserved without validation")
    installer_names = {d["name"] for d in decisions if d["platform"] not in {"metadata", "source"}}
    selected_names = {a["name"] for a in assets if a["platform"] != "metadata"}
    unrelated_metadata = {
        a["id"]
        for a in assets
        if a["platform"] == "metadata"
        and any(
            a["name"].startswith(name + ".") and name not in selected_names
            for name in installer_names
        )
    }
    for decision in decisions:
        if decision["id"] in unrelated_metadata:
            decision.update(
                decision="ignored", reason="verification metadata for an ignored installer"
            )
    assets = [a for a in assets if a["id"] not in unrelated_metadata]
    installers = [a for a in assets if a["platform"] != "metadata"]
    # No metadata-only backup can become a complete installer release.
    if not installers:
        for decision in decisions:
            if decision["decision"] == "selected":
                decision.update(decision="ignored", reason="no relevant installer selected")
        assets = []
    return {
        "schema_version": 2,
        "name": project.get("name", repository),
        "prerelease": release.get("prerelease", False),
        "draft": release.get("draft", False),
        "repository": repository,
        "release_id": release["id"],
        "release_url": release.get("html_url"),
        "tag": release["tag_name"],
        "version": str(version(release)) if version(release) else release["tag_name"],
        "published_at": release.get("published_at"),
        "assets": assets,
        "unresolved": unresolved,
        "warnings": warnings,
        "missing_platforms": sorted(set(rules["platforms"]) - published),
        "selection_policy": rules,
        "asset_decisions": decisions,
        "selected_bytes": sum(a["size"] for a in assets),
        "availability": availability(rules, decisions),
        "status": "partial",
        "archived_at": None,
    }


def availability(rules: dict, decisions: list[dict]) -> list[dict]:
    result = []
    binaries = [d for d in decisions if d["platform"] not in {"metadata", "source"}]
    for os_name in rules["platforms"]:
        for fmt in rules["formats_by_platform"][os_name]:
            for arch in rules["architectures"]:
                exact = any(
                    d["platform"] == os_name and d["format"] == fmt and d["architecture"] == arch
                    for d in binaries
                )
                uncertain = any(
                    d["platform"] in {os_name, "unknown"}
                    and d["format"] in {fmt, "unknown"}
                    and d["architecture"] in {arch, "unknown"}
                    for d in binaries
                )
                result.append(
                    {
                        "platform": os_name,
                        "format": fmt,
                        "architecture": arch,
                        "state": "published"
                        if exact
                        else "ambiguous"
                        if uncertain
                        else "not_published",
                    }
                )
    return result
