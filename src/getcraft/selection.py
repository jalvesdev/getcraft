"""Conservative release ordering and advisory asset classification."""

import re

from packaging.version import InvalidVersion, Version


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
    if re.search(r"(sha\d*|checksums?|\.sig$|\.asc$|\.minisig$|\.sign$|\.signature$)", name):
        return "metadata", "unknown", "Checksum/signature; preserve with binaries in M2"
    if "source" in name or "src" in re.split(r"[-_.]", name):
        return "source", "unknown", "Source archive; excluded"
    platforms = set()
    if name.endswith((".exe", ".msi", ".msix", ".msixbundle")) or re.search(
        r"windows|win32|win64", name
    ):
        platforms.add("windows")
    if name.endswith((".dmg", ".pkg", ".app.zip")) or re.search(r"macos|darwin|osx", name):
        platforms.add("macos")
    if name.endswith((".deb", ".rpm", ".appimage", ".flatpak", ".flatpakref")) or "linux" in name:
        platforms.add("linux")
    archs = set()
    for pattern, arch in [
        (r"x86[_-]64|amd64|x64", "x86_64"),
        (r"arm64|aarch64", "arm64"),
        (r"universal", "universal"),
    ]:
        if re.search(pattern, name):
            archs.add(arch)
    platform = next(iter(platforms)) if len(platforms) == 1 else "unknown"
    arch = next(iter(archs)) if len(archs) == 1 else "unknown"
    warnings = []
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


def policy(config: dict, project: dict) -> dict:
    defaults = config.get("selection", {})
    platforms = project.get(
        "platforms",
        [p for p in ("windows", "macos", "linux") if config.get("platforms", {}).get(p, True)],
    )
    return {
        "platforms": platforms,
        **{
            key: project.get(key, defaults.get(key, default))
            for key, default in [
                ("architectures", ["x86_64", "arm64", "universal"]),
                ("formats", []),
                ("include_assets", []),
                ("exclude_assets", []),
            ]
        },
    }


def plan_release(config: dict, project: dict, release: dict) -> dict:
    """Unknown/source assets never become installers through filename guessing."""
    from fnmatch import fnmatchcase

    from getcraft.archive import segment
    from getcraft.download import valid_url

    rules = policy(config, project)
    repository = f"{project['owner']}/{project['repo']}"
    segment(release["tag_name"])
    base = f"{repository}/{release['tag_name']}"
    assets, unresolved, warnings = [], [], []
    published = set()
    names = set()
    ids = set()
    for remote in release.get("assets", []):
        name = remote["name"]
        platform, architecture, warning = classify(name)
        if platform in {"windows", "macos", "linux"}:
            published.add(platform)
        if any(fnmatchcase(name, pattern) for pattern in rules["exclude_assets"]):
            continue
        if platform == "source":
            warnings.append(f"{name}: source excluded")
            continue
        if name.lower().endswith((".zsync", ".wixpdb", ".blockmap")):
            warnings.append(f"{name}: auxiliary metadata excluded")
            continue
        explicit = any(fnmatchcase(name, pattern) for pattern in rules["include_assets"])
        fmt = asset_format(name)
        if platform != "metadata":
            if platform != "unknown" and platform not in rules["platforms"]:
                continue
            if architecture != "unknown" and architecture not in rules["architectures"]:
                continue
            if rules["formats"] and fmt not in rules["formats"]:
                continue
        try:
            segment(name)
            if name.lower().endswith(".part"):
                raise ValueError("Reserved temporary-file suffix")
            if (
                type(remote["id"]) is not int
                or type(remote["size"]) is not int
                or remote["size"] < 0
            ):
                raise ValueError("Invalid asset ID/size")
            valid_url(remote["browser_download_url"])
        except ValueError as error:
            unresolved.append(f"{name!r}: {error}")
            continue
        if (
            platform != "metadata"
            and not explicit
            and (
                platform == "unknown"
                or architecture == "unknown"
                or fmt in {"zip", "app.zip", "tar.gz", "tar.xz", "tar.bz2", "tgz", "unknown"}
            )
        ):
            unresolved.append(f"{name}: explicit include_assets or exclude_assets rule required")
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
        if warning:
            warnings.append(f"{name}: {warning}")
        if remote.get("digest") and not remote["digest"].startswith("sha256:"):
            warnings.append(f"{name}: unsupported official digest; preserved without validation")
    return {
        "schema_version": 2,
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
        "status": "partial",
        "archived_at": None,
    }
