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
    if re.search(r"(sha\d*|checksums?|\.sig$|\.asc$)", name):
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
