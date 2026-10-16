"""Read-only inventory contract for discovery; M2 will write verified manifests."""

import json
from pathlib import Path


def inventory(root: Path) -> list[dict]:
    path = root.expanduser() / "inventory.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("releases"), list)
    ):
        raise ValueError("Unsupported inventory: expected schema_version=1 and releases array")
    for row in data["releases"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("repository"), str)
            or type(row.get("release_id")) is not int
            or row.get("status") not in {"partial", "complete", "verified", "failed"}
        ):
            raise ValueError("Invalid inventory release entry")
    return data["releases"]


def state(rows: list[dict], repository: str, release_id: int) -> str:
    matches = [
        r
        for r in rows
        if r["repository"].lower() == repository.lower() and r["release_id"] == release_id
    ]
    if len(matches) > 1:
        raise ValueError("Duplicate inventory release ID")
    return matches[0]["status"] if matches else "missing"
