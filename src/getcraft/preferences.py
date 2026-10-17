"""Host suggestions and backward-compatible selection preferences; never auto-apply."""

import platform

PLATFORMS = ("windows", "macos", "linux")
ARCHITECTURES = ("x86_64", "arm64", "universal")
ARCHIVE_FORMATS = ("zip", "tar.gz", "tar.xz", "tar.bz2", "tgz")
PLATFORM_FORMATS = {
    "windows": ("exe", "msi", "msix", "msixbundle", *ARCHIVE_FORMATS),
    "macos": ("dmg", "pkg", "app.zip", *ARCHIVE_FORMATS),
    "linux": ("appimage", "flatpak", "flatpakref", "rpm", "deb", *ARCHIVE_FORMATS),
}


def normalize_architecture(value: str) -> str:
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "universal2": "universal",
    }.get(value.lower(), value.lower())


def normalize_format(value: str) -> str:
    return value.lower().lstrip(".")


def detect() -> dict:
    system = platform.system()
    machine = platform.machine()
    os_name = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(system)
    architecture = normalize_architecture(machine)
    distro = {}
    if os_name == "linux":
        try:
            distro = platform.freedesktop_os_release()
        except OSError:
            pass
    suggested_formats = []
    if os_name == "windows":
        suggested_formats = ["exe", "msi", "msix", "msixbundle"]
    elif os_name == "macos":
        suggested_formats = ["dmg", "pkg"]
    elif os_name == "linux":
        suggested_formats = ["appimage", "flatpak"]
        family = (distro.get("ID", "") + " " + distro.get("ID_LIKE", "")).lower().split()
        if set(family) & {"fedora", "rhel", "centos", "rocky", "almalinux", "suse", "opensuse"}:
            suggested_formats.append("rpm")
        elif set(family) & {"debian", "ubuntu", "linuxmint"}:
            suggested_formats.append("deb")
    architectures = [architecture] if architecture in ARCHITECTURES else []
    if os_name == "macos" and architectures:
        architectures.append("universal")
    return {
        "system": system,
        "machine": machine,
        "platform": os_name,
        "architecture": architecture if architecture in ARCHITECTURES else "unknown",
        "distribution": distro.get("PRETTY_NAME") or distro.get("ID"),
        "suggested": {
            "platforms": [os_name] if os_name else [],
            "architectures": architectures,
            "formats_by_platform": {os_name: suggested_formats} if os_name else {},
        },
        "note": "Suggestion only; review before applying. Other machines can be archive targets.",
    }


def policy(config: dict, project: dict) -> dict:
    defaults = config.get("selection", {})
    platforms = project.get(
        "platforms",
        defaults.get(
            "platforms", [p for p in PLATFORMS if config.get("platforms", {}).get(p, True)]
        ),
    )
    legacy_formats = project.get("formats", defaults.get("formats", []))
    # A repository's legacy flat formats list overrides the global per-platform map.
    maps = {} if "formats" in project else dict(defaults.get("formats_by_platform", {}))
    maps.update(project.get("formats_by_platform", {}))
    return {
        "platforms": list(platforms),
        "architectures": list(
            project.get("architectures", defaults.get("architectures", ARCHITECTURES))
        ),
        "formats": list(legacy_formats),
        "formats_by_platform": {
            p: list(maps[p])
            if p in maps
            else [f for f in PLATFORM_FORMATS[p] if not legacy_formats or f in legacy_formats]
            for p in PLATFORMS
        },
        "include_assets": list(project.get("include_assets", defaults.get("include_assets", []))),
        "exclude_assets": list(project.get("exclude_assets", defaults.get("exclude_assets", []))),
    }


def validate_preferences(settings: dict) -> None:
    for key in ("architectures", "formats"):
        if key in settings:
            normalizer = normalize_architecture if key == "architectures" else normalize_format
            settings[key] = list(dict.fromkeys(normalizer(v) for v in settings[key]))
    if not set(settings.get("architectures", [])) <= set(ARCHITECTURES) | {"unknown"}:
        raise ValueError("Unsupported architecture; use x86_64, arm64 or universal")
    maps = settings.get("formats_by_platform", {})
    if not isinstance(maps, dict) or not set(maps) <= set(PLATFORMS):
        raise ValueError("formats_by_platform must map windows/macos/linux to format arrays")
    for os_name, formats in maps.items():
        if not isinstance(formats, list) or not all(isinstance(f, str) for f in formats):
            raise ValueError("Per-platform formats must be string arrays")
        normalized = list(dict.fromkeys(normalize_format(f) for f in formats))
        if not set(normalized) <= set(PLATFORM_FORMATS[os_name]):
            raise ValueError(f"Incompatible or unsupported format for {os_name}")
        maps[os_name] = normalized
