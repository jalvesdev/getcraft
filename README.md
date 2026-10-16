# GetCraft

**GetCraft** is a Python command-line tool for archiving official software releases from GitHub, across **Windows, macOS, and Linux**.

> Status: M0–M2 implemented: registry, discovery, safe downloads and offline integrity verification. No pruning or installer execution.

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

## Back up releases (M2)

```bash
getcraft sync --dry-run
getcraft sync                  # all enabled registered repositories
getcraft sync --all
getcraft sync --repo storytold/photocraft
getcraft verify                # all local manifests, including disabled/removed projects
getcraft verify --all
getcraft verify --repo storytold/photocraft
getcraft status                 # real file size/hash inspection, offline
getcraft verify --rebuild-inventory
getcraft verify --rebuild-inventory --dry-run
```

Always inspect a dry-run before a large first backup. It lists selected paths,
asset sizes and a total upper bound; intact files will be reused. Dry-run fetches
API metadata but creates no archive files or lock. An actual sync requires write
access to the configured archive root, outside the checkout. No administrator
privileges are needed. `--repo` and `--all` are mutually exclusive.

The latest `keep_versions` eligible releases are selected (default three).
Source-only releases do not consume the selection count. Subsequent syncs also
revisit older archived release IDs still published upstream, checking every selected
file before reuse. Valid files are not downloaded again. Nothing is pruned, even
when `prune_after_sync = true` or the selection changes. Upstream tag/asset identity
changes at an existing path require manual review and preserve the old archive.

Example storage, independent of the host operating system:

```text
SoftwareArchive/
  inventory.json
  storytold/photocraft/v0.9.0/
    manifest.json
    linux/arm64/photocraft-0.9.0-linux-aarch64.flatpak
    windows/x86_64/photocraft-0.9.0-windows-x64.msi
    macos/universal/photocraft-0.9.0-macos-universal.dmg
    metadata/SHA256SUMS.txt
```

### Selection policies

All three platforms and known `x86_64`, `arm64`, `universal` architectures are
selected by default. The existing `[platforms]` boolean flags remain supported.
Global policy fields belong in `[selection]`; repository fields override the
corresponding global lists. Empty `formats` means all recognized installer formats.
Names and globs are case sensitive and never interpreted by a shell.

```toml
[selection]
architectures = ["x86_64", "arm64", "universal"]
formats = []
include_assets = []
exclude_assets = []

[[repositories]]
owner = "storytold"
repo = "photocraft"
enabled = true
keep_versions = 3
platforms = ["windows", "macos", "linux"]
# A narrow example policy after reviewing upstream distributions:
formats = ["msi", "dmg", "flatpak"]
exclude_assets = ["*-freebsd-*", "*-riscv64-*", "*-windows-x86.*"]
```

Unknown platforms/architectures, unknown formats and ZIP/tar distributions require
explicit `include_assets` filename globs before downloading. Use `exclude_assets`
to resolve intentional omissions. Exclusions take priority; includes do not bypass
platform, architecture or format filters, path security, or source-code exclusion.
For example, `include_assets = ["photocraft-*-windows-x64-portable.zip"]` permits
reviewed portable ZIPs. Unknown architectures can be explicitly included by filename.
No archive is unpacked or inspected, and no source tarball is automatically downloaded.
Auxiliary `.zsync`/`.wixpdb`/`.blockmap` files are skipped with a warning.
Checksum and signature files are required metadata whenever a release is selected,
unless explicitly excluded. Signatures are preserved, not cryptographically verified.
`flatpakref` is a pointer and receives a warning; it is not a self-contained installer.

All selected required assets must pass validation for `complete`. Unresolved
classification makes the release `partial`; entirely unsuccessful downloads produce
`failed`. Platforms not published by the developer are recorded separately in
`missing_platforms`; their absence is not a network failure. Explicit policy exclusions
are not treated as missing downloads. When a policy changes, existing asset records
and files are retained, with deselected records marked `required = false`.

### Integrity and recovery

Downloads use bounded streaming, timeouts, three attempts on transport/5xx errors
and exponential backoff. HTTP 403/429 stops downloads rather than hammering the server.
Only HTTPS GitHub release/CDN URLs are accepted, including every redirect; asset
requests carry no API token. Public release assets are supported; authenticated
private asset downloads are not yet supported. Untrusted paths and symlinks are
rejected. OS file locking prevents overlapping operations on the same archive.
Use a filesystem with reliable advisory locks and atomic renames (NAS behavior may
vary). Windows uses byte-range locking; Linux/macOS use `flock`.

Each transfer starts in `.part`, verifies size, computes SHA-256 and validates an
API SHA-256 digest and/or recognized published checksum before atomic publication.
Recognized checksum lines are GNU SHA256 (`hash  filename` or `hash *filename`) and
BSD (`SHA256 (filename) = hash`). Only exact basenames are matched, without shell
expansion or traversal. Checksum documents are parsed as UTF-8 with an 8 MiB limit;
unsupported formats get warnings. Conflicts or corrupt checksum metadata block binary
downloads. Other digest algorithms are retained but not validated. A local SHA-256
supports future corruption detection; it is not proof of publisher authenticity.

Transfers restart from zero after interruption. Range resumption is deliberately not
used because remote identity has not been validated. A pending manifest journals
release/asset identity before initial transfers. Pre-existing untracked files without
an official digest require manual review; intact managed files are reused. Failure
never deletes a valid backup. Disk space is checked before each transfer, and write
errors are reported. Failed temporary transfers are cleaned up; a process kill may
leave `.part`, which is safely restarted on the next sync.

Manifests use schema version 2, recording repository/release ID and URL, tag/version,
publication/archive dates, selected asset IDs, names, URLs, size, platform, format,
architecture, SHA-256, official digest, published checksum, file/release states,
warnings and unavailable platforms. The index retains the M1 `schema_version = 1`,
`releases` array contract and adds manifest locations and inspection problems.

`verify` and `status` hash files using local manifests and make no HTTP requests.
They detect missing files/manifests, invalid metadata, wrong sizes/hashes and partial
releases. Exit code 0 means inspected releases are complete (or the archive is empty);
1 means incomplete/invalid data or an operational failure; CLI usage errors use 2.
`sync` returns 1 for selected partial/failed releases. Warnings are visible in the plan
and manifests. A release with no eligible installers is reported and skipped.

The inventory is an index, not the authority. Sync rebuilds it from all local
manifests. For a lost/corrupt index, `verify --rebuild-inventory` reconstructs it offline,
under the archive lock. Invalid manifests block index replacement and are reported;
never silently replace them with an empty inventory. Normal verify/status do not
rewrite manifests or inventory (they create/acquire the lock file). `check` retains
M1 inventory-based discovery; rebuild a malformed inventory before using it.

M2 preserves published installers, **not a guarantee of fully offline installation**.
Flatpak runtimes, distribution dependencies and platform prerequisites may need
separate preservation. Installation guides, structured reports and conservative
retention/prune remain planned for M3.

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
