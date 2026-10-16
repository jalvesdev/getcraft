# GetCraft

**GetCraft** is a Python command-line tool for archiving official software releases from GitHub, across **Windows, macOS, and Linux**.

> Status: specification and development scaffold. No working archiver is included yet.

## Goals

- Track any number of explicitly registered GitHub repositories.
- Detect new stable releases and download relevant official binary assets for selected operating systems and architectures.
- Keep the **three newest verified, complete stable releases** of each application by default.
- Save checksums, release metadata, asset URLs, and human-readable installation guidance.
- Resume safely after interruptions; never delete verified archives before a replacement is complete.
- Support manual runs and optional `systemd --user` scheduling on Fedora.

## Planned CLI

```text
getcraft repo add https://github.com/storytold/photocraft
getcraft repo list
getcraft repo disable storytold/photocraft
getcraft check
getcraft sync --all
getcraft status
getcraft verify --all
getcraft prune --dry-run
```

Commands above describe the planned interface; they are **not implemented** in this scaffold.

## Archive vs. repository

The Git repository stores source code, documentation, and sample configuration. Downloaded installers, local inventory, credentials, and logs live **outside Git** in a user-configurable archive directory (for example `~/SoftwareArchive` or a mounted NAS).

Preserving installers does **not** guarantee fully offline installation: Flatpak runtimes, RPM/DEB dependencies, Windows prerequisites, and macOS compatibility may require separate preservation. See [PRD](docs/PRD.md).

## Development

Read [AGENTS.md](AGENTS.md), [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md), [implementation plan](docs/IMPLEMENTATION_PLAN.md), and [Codex kickoff](docs/CODEX_TASK.md).

## Legal and security

Archive only software you are entitled to download and retain. Respect upstream licenses. Do not execute downloaded binaries, and do not commit tokens or installers to this repository.

## License

MIT license for GetCraft's own source code. Upstream application licenses remain independent.
