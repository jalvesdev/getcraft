"""Repository registration shared by terminal interfaces."""

from getcraft.configuration import target
from getcraft.github import repository_name


def register(data: dict, repository: str, github) -> str:
    name = repository_name(repository)
    if any(f"{p['owner']}/{p['repo']}".lower() == name.lower() for p in data["repositories"]):
        raise ValueError("Repository already registered")
    name = repository_name(github.repository(name)["full_name"])
    if any(f"{p['owner']}/{p['repo']}".lower() == name.lower() for p in data["repositories"]):
        raise ValueError("Repository already registered")
    owner, repo = name.split("/")
    data["repositories"].append(dict(owner=owner, repo=repo, enabled=True))
    return name


def change(data: dict, repository: str, action: str) -> None:
    project = target(data, repository)
    if action == "remove":
        if project.get("pinned_versions"):
            raise ValueError("Repository has pinned versions; disable monitoring or unpin first")
        data["repositories"].remove(project)
    elif action in ("enable", "disable"):
        project["enabled"] = action == "enable"
    else:
        raise ValueError("Unknown registry action")
