"""Validated configuration and atomic TOML persistence."""

import json
import os
import tempfile
import tomllib
from pathlib import Path


def default_path() -> Path:
    return Path("~/.config/getcraft/config.toml").expanduser()


def load(path: Path) -> dict:
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    archive = data.setdefault("archive", {})
    root = Path(archive.setdefault("path", "~/SoftwareArchive")).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if root == checkout or checkout in root.parents:
        raise ValueError("Archive path must be outside the GetCraft checkout")
    archive.setdefault("keep_versions", 3)
    archive.setdefault("include_prereleases", False)
    if not isinstance(archive["include_prereleases"], bool):
        raise ValueError("include_prereleases must be boolean")
    if type(archive["keep_versions"]) is not int or archive["keep_versions"] < 1:
        raise ValueError("keep_versions must be a positive integer")
    data.setdefault("repositories", [])
    if not isinstance(data["repositories"], list):
        raise ValueError("repositories must be an array of tables")
    seen = set()
    for repo in data["repositories"]:
        from getcraft.github import repository_name

        key = repository_name(f"{repo['owner']}/{repo['repo']}").lower()
        if key in seen:
            raise ValueError(f"Duplicate repository: {key}")
        seen.add(key)
        if not isinstance(repo.get("enabled", True), bool):
            raise ValueError("enabled must be boolean")
    return data


def _value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise ValueError(f"Unsupported TOML value: {type(value).__name__}")


def save(path: Path, data: dict) -> None:
    lines = []
    for section, values in data.items():
        if section == "repositories":
            continue
        lines.append(f"[{json.dumps(section)}]")
        lines.extend(f"{json.dumps(key)} = {_value(value)}" for key, value in values.items())
        lines.append("")
    for repo in data["repositories"]:
        lines.append("[[repositories]]")
        lines.extend(f"{json.dumps(key)} = {_value(value)}" for key, value in repo.items())
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".getcraft-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
