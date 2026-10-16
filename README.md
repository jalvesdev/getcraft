# GetCraft

**GetCraft** is a Python command-line tool for archiving official software releases from GitHub, across **Windows, macOS, and Linux**.

> Status: M0/M1 implemented: registry and release discovery. Downloads and pruning are not implemented.

## Goals

- Track any number of explicitly registered GitHub repositories.
- Detect new stable releases and download relevant official binary assets for selected operating systems and architectures.
- Keep the **three newest verified, complete stable releases** of each application by default.
- Save checksums, release metadata, asset URLs, and human-readable installation guidance.
- Resume safely after interruptions; never delete verified archives before a replacement is complete.
- Support manual runs and optional `systemd --user` scheduling on Fedora.

## Setup and CLI

Requires Python 3.12+. From the checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
getcraft --help
getcraft repo add https://github.com/storytold/photocraft
getcraft repo list
getcraft repo disable storytold/photocraft
getcraft repo enable storytold/photocraft
getcraft repo remove storytold/photocraft --dry-run
getcraft check
getcraft check --repo storytold/photocraft --prereleases
getcraft status
```

Configuration defaults to `~/.config/getcraft/config.toml`. Supply a global
`--config PATH` before the command to use another TOML file. Registration validates
repository existence through the official API. All registry mutations support
`--dry-run`; removing a project never deletes archived data. Example without writes:

```bash
getcraft --config config/config.example.toml check
```

Set `GITHUB_TOKEN` in the environment for authenticated API access; never save tokens
in configuration. Discovery follows pagination, reports API/rate-limit failures,
and uses ETags for repeated requests within one client session (no persistent cache).
Failures exit with code 1; successful checks exit 0 even when releases are missing.
Disabled projects are skipped. Drafts are always excluded in this stage, even if a
legacy config contains `include_drafts = true`. Prereleases require explicit opt-in.
Valid version tags use `packaging.Version` ordering; if any eligible tag is irregular,
all eligible releases use publication time and release ID, with a visible warning.

Asset classifications are advisory: unknown architectures/platforms and uninspected
binary archives require review. Checksums/signatures and source archives are identified;
`flatpakref` is explicitly labeled as a pointer. Platform/architecture overrides are
preserved in TOML but download filtering and retention enforcement belong to M2/M3.

`status` reads local inventory only, without verifying files. Missing inventory means
an empty archive. The read-only M1 contract is `<archive.path>/inventory.json`:

```json
{"schema_version": 1, "releases": [
  {"repository": "storytold/photocraft", "release_id": 123, "status": "partial"}
]}
```

States are `partial`, `complete`, or `verified`; discovery matches stable repository
and release IDs, displaying `missing` for absent entries. Recorded verification is
not a fresh integrity check. Malformed inventories fail visibly. No inventory is
created by M1. Archive paths inside this checkout are rejected.

Run local checks with `ruff check .`, `ruff format --check .`, and `pytest -q`.
CI runs them on Python 3.12, 3.13, and 3.14. A static type checker is not configured.

## Archive vs. repository

The Git repository stores source code, documentation, and sample configuration. Downloaded installers, local inventory, credentials, and logs live **outside Git** in a user-configurable archive directory (for example `~/SoftwareArchive` or a mounted NAS).

Preserving installers does **not** guarantee fully offline installation: Flatpak runtimes, RPM/DEB dependencies, Windows prerequisites, and macOS compatibility may require separate preservation. See [PRD](docs/PRD.md).

## Development

Read [AGENTS.md](AGENTS.md), [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md), [implementation plan](docs/IMPLEMENTATION_PLAN.md), and [Codex kickoff](docs/CODEX_TASK.md).

## Legal and security

Archive only software you are entitled to download and retain. Respect upstream licenses. Do not execute downloaded binaries, and do not commit tokens or installers to this repository.

## License

MIT license for GetCraft's own source code. Upstream application licenses remain independent.
