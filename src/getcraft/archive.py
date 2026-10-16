"""Safe archive paths, atomic manifests, locking, and offline inspection."""

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from getcraft.download import official_sha256, sha256
from getcraft.github import repository_name


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def segment(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or any(c in value for c in '/\\:<>"|?*')
        or value.endswith((" ", "."))
        or value.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("Unsafe archive path segment")
    return value


def safe(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute():
        raise ValueError("Absolute archive path rejected")
    parts = relative.split("/")
    for part in parts:
        segment(part)
    target = root
    # Reject symlinks in root and all ancestors as well as relative paths.
    for parent in [*reversed(root.parents), root]:
        if parent.is_symlink():
            raise ValueError("Symlink archive root rejected")
    for part in parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Symlink archive path rejected")
    return target


def atomic_json(path: Path, data: dict) -> None:
    if path.is_symlink():
        raise ValueError("Symlink metadata rejected")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".getcraft-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def lock(root: Path):
    path = safe(root, ".getcraft.lock")
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Archive is locked by another GetCraft process") from None
        yield
    finally:
        os.close(descriptor)


def read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        if data["schema_version"] != 2 or type(data["release_id"]) is not int:
            raise ValueError("Unsupported manifest schema")
        repository_name(data["repository"])
        segment(data["tag"])
        if data["status"] not in {"complete", "partial", "failed"}:
            raise ValueError("Invalid release status")
        if not isinstance(data["assets"], list) or not isinstance(data["unresolved"], list):
            raise ValueError("Invalid manifest assets")
        seen = set()
        for asset in data["assets"]:
            segment(asset["name"])
            if (
                type(asset["id"]) is not int
                or type(asset["size"]) is not int
                or asset["size"] < 0
                or not isinstance(asset["path"], str)
                or asset["status"] not in {"verified", "failed", "pending"}
                or asset["path"] in seen
            ):
                raise ValueError("Invalid manifest asset")
            seen.add(asset["path"])
            if asset.get("sha256") is not None and not re.fullmatch(
                "[a-f0-9]{64}", asset["sha256"]
            ):
                raise ValueError("Invalid manifest SHA-256")
            official_sha256(asset.get("official_digest"))
        return data
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid manifest") from error


def file_problem(root: Path, asset: dict) -> str | None:
    path = safe(root, asset["path"])
    if not path.is_file():
        return "missing"
    if path.stat().st_size != asset["size"]:
        return "size mismatch"
    if not asset.get("sha256"):
        return "missing recorded SHA-256"
    actual = sha256(path)
    if actual != asset["sha256"]:
        return "SHA-256 mismatch"
    official = official_sha256(asset.get("official_digest"))
    if official and actual != official:
        return "official SHA-256 mismatch"
    if asset.get("published_sha256") and actual != asset["published_sha256"]:
        return "published SHA-256 mismatch"
    if asset["status"] != "verified":
        return "file not verified"
    return None


def inspect(root: Path, repository: str | None = None) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    if not root.exists():
        return rows, errors
    safe(root, ".getcraft.lock")
    for path in sorted(root.glob("*/*/*/manifest.json")):
        relative = path.relative_to(root).as_posix()
        try:
            safe(root, relative)
            data = read_manifest(path)
            expected_dir = f"{data['repository']}/{data['tag']}"
            if path.parent.relative_to(root).as_posix() != expected_dir:
                raise ValueError("Manifest location differs from repository/tag")
            if repository and data["repository"].lower() != repository.lower():
                continue
            problems = []
            for asset in data["assets"]:
                if not asset["path"].startswith(expected_dir + "/"):
                    raise ValueError("Asset outside release directory")
                problem = file_problem(root, asset)
                if problem:
                    problems.append(f"{asset['name']}: {problem}")
            if data["unresolved"]:
                problems.append("Unresolved asset classifications")
            if not data["assets"] or data["status"] != "complete":
                problems.append(f"Incomplete release (recorded={data['status']})")
            row = {
                "repository": data["repository"],
                "release_id": data["release_id"],
                "tag": data["tag"],
                "status": "partial" if problems else "complete",
                "manifest": relative,
                "problems": problems,
            }
            rows.append(row)
        except (ValueError, OSError) as error:
            errors.append(f"{relative}: {error}")
    return rows, errors


def rebuild(root: Path) -> tuple[list[dict], list[str]]:
    rows, errors = inspect(root)
    # Never replace the index with an incomplete scan when a manifest is unreadable.
    if not errors:
        atomic_json(safe(root, "inventory.json"), {"schema_version": 1, "releases": rows})
    return rows, errors
