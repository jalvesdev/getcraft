# GetCraft

**GetCraft** is a Python command-line tool for archiving official software releases from GitHub, across **Windows, macOS, and Linux**.

> Status: M0–M3 implemented: registry, safe downloads, offline verification, explicit retention, installation guidance and offline catalogs. Installers are never executed.

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
file before reuse. Valid files are not downloaded again. Sync never prunes, even
when `prune_after_sync = true` or the selection changes. M3 pruning is a separate explicit command. Upstream tag/asset identity
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
separate preservation. Installation guides, offline catalogs and explicit
retention/prune are available in M3, described below.

## Safe retention and protected releases (M3)

```bash
getcraft prune                                 # simulation by default
getcraft prune --dry-run
getcraft prune --repo storytold/photocraft --dry-run
getcraft prune --all --dry-run
getcraft prune --json-plan                      # pure JSON plan, no archive writes
getcraft pin storytold/photocraft v0.9.0
getcraft pins
getcraft unpin storytold/photocraft v0.9.0
getcraft prune --repo storytold/photocraft --apply       # interactive confirmation
getcraft prune --repo storytold/photocraft --apply --yes # explicit unattended deletion
```

`--dry-run` and `--apply` are mutually exclusive. `--yes` requires `--apply`.
`--json-plan` is a simulation output and cannot be combined with `--apply`.
Pin/unpin also accept `--dry-run`. The exact tag string is protected, including tags
not yet archived. Pins are saved as `pinned_versions = ["v0.9.0"]` in the repository's
TOML table. Per-project `keep_versions` overrides the global archive value.
Pinned releases are **additional** to the newest `keep_versions` verified stable
releases, rather than consuming slots. Removing a registry entry with pins is refused;
disable monitoring or explicitly unpin first. Disabled/unregistered projects are not pruned.

Prune uses live GitHub release data and verifies local files; a cached availability
record is insufficient. It fails closed if the API is unreachable/rate-limited,
index/manifests disagree, an inventory is missing/corrupt, metadata is invalid, or
symlinks/special files are encountered. Repair a derived index using
`getcraft verify --rebuild-inventory`, then inspect the next plan.
An incomplete/corrupt release blocks deletion for its entire project. Prereleases,
drafts and releases no longer published as stable are preserved and cannot replace
stable backups. No API/network/index failure authorizes deletion.

Counting is by release, regardless of the number of installers. Only locally complete,
rehashed stable releases form the replacement window. Each retained replacement must
preserve every platform/architecture/format combination of a candidate; a narrower
new selection policy cannot silently erase the only archived coverage of another OS.
Versions requiring manual review or containing unknown files/directories are preserved.
An edited generated README also prevents deletion. These conservative rules can leave
more than `keep_versions` releases on disk.

The plan lists each candidate's exact paths, sizes, SHA-256 and reason, with a plan ID.
Application obtains the archive lock, queries the API again and recomputes the plan.
Any difference in configuration, source or archive fingerprint aborts it. Source
availability and file identity are checked again before removal. An audit containing
the entire approved plan is atomically persisted under `.getcraft/prune/<id>.json`
**before** any unlink. Only listed assets, manifests and unchanged managed READMEs are
removed, followed by their empty directories; no recursive tree deletion is used.
Manifests are removed last. The inventory is rebuilt after successful pruning.

State fingerprints cover archive names, file identities, sizes, mtimes and hashes;
`.getcraft/` runtime/audit data and the lock file are excluded. Repeated full hashing
can be expensive for large archives. Application holds the OS lock; use a trusted
archive directory and a filesystem with reliable advisory locks and atomic renames.
A failure/power loss midway through pruning can leave a partially removed old candidate;
retained replacements and pins remain untouched. Inspect the audit and run offline
verify/rebuild before retrying. Do not edit the archive concurrently outside GetCraft.

## Installation guidance and offline catalogs (M3)

Sync generates a `README.md` beside each release manifest. Existing M2 archives can
receive guidance explicitly, together with a catalog:

```bash
getcraft report
getcraft report --format json
getcraft report --format markdown
getcraft report --format html
getcraft report --format html --output catalog.html --write-readmes
getcraft report --format markdown --output catalog.md
getcraft report --format json --output catalog.json
getcraft report --format html --output catalog.html --write-readmes --dry-run
```

Without `--output`, the selected report is printed to stdout without terminal wrapping.
`--output` is a filename at the archive root, with relative installer/README links;
open `catalog.html` directly in a browser. There are no scripts, CDNs, remote fonts,
external resource requirements or server. The catalog remains navigable when moved
with the archive. Do not place redirected HTML/Markdown elsewhere without adjusting
relative links. JSON includes relative paths and file-level integrity results.

Reports are offline: latest-known stable version and last-sync time are recorded by
M3 sync, not refreshed by report or the stateless M1 check command. For older M2
archives, absent information is shown as unknown; an archive timestamp is exposed
separately and never invented as a sync time. Reports include monitored/enabled
projects, archived releases and coverage, pins, file integrity, missing platforms,
sync failures and incomplete backups. A corrupt index is reported, while the catalog
still uses manifests to inspect actual files. Sizes are logical file bytes, including
metadata/unmanaged files; total size also includes root-level reports/audits and is
a snapshot before writing the newly generated report, not allocated filesystem space.

Generated READMEs list archived files, hashes, Windows/macOS guidance and applicable
Flatpak/AppImage/DNF/APT command examples. Commands are safely quoted documentation;
nothing is executed. They distinguish local payloads, potentially online installers
whose behavior is unknown, and `.flatpakref` references. They document external runtime/
package dependencies without inventing application-specific requirements. Archived
installers do not guarantee fully offline installation or future OS compatibility.
Optional links to official format documentation are informational, not required resources.

GetCraft records generated README hashes in schema-2 manifests and report hashes in
`.getcraft/reports.json`. It only replaces an unchanged generated file; user-written
or edited files are preserved. `verify` also detects a missing/modified managed README.
`--dry-run` renders output but writes no reports, READMEs or lock files. Normal report
uses the archive lock; `--write-readmes` is the explicit migration for existing backups.
Report generation exits 0 when a catalog is produced, even if it lists incomplete
backups; use verify's exit status for integrity automation. Operational/usage errors
retain the existing exit-code conventions.

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
