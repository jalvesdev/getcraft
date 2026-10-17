"""Shared validated configuration edits, independent of terminal frameworks."""

import hashlib
from pathlib import Path

from getcraft.archive import lock
from getcraft.config import load, save
from getcraft.github import repository_name


def target(data: dict, repo: str | None) -> dict:
    if repo is None:
        return data.setdefault("selection", {})
    name = repository_name(repo)
    for project in data["repositories"]:
        if f"{project['owner']}/{project['repo']}".lower() == name.lower():
            return project
    raise ValueError("Repository not registered")


def parse_list(value: str, allowed: tuple | list, normalizer=lambda v: v.lower()) -> list[str]:
    values = list(dict.fromkeys(normalizer(v.strip()) for v in value.split(",") if v.strip()))
    if not values or not set(values) <= set(allowed):
        raise ValueError("Choose a nonempty comma-separated list from: " + ", ".join(allowed))
    return values


def config_fingerprint(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def edit_load(path: Path) -> tuple[dict, str | None]:
    before = config_fingerprint(path)
    data = load(path)
    if before != config_fingerprint(path):
        raise ValueError("Configuration changed while reading; retry")
    return data, before


def persist(path: Path, data: dict, dry_run: bool, baseline: str | None) -> None:
    if not dry_run:
        with lock(Path(data["archive"]["path"]).expanduser().absolute()):
            if config_fingerprint(path) != baseline:
                raise ValueError("Configuration changed during review; no preferences saved")
            save(path, data)
