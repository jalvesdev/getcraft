# GetCraft

**GetCraft** is a Python terminal application and command-line tool for archiving official software releases from GitHub, across **Windows, macOS, and Linux**.

> Status: M0–M3.6 implemented: keyboard-driven Textual interface, registry, safe downloads, offline verification, explicit retention, installation guidance and offline catalogs and reviewable target preferences. Installers are never executed.

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

## Interactive terminal (M3.6)

```bash
getcraft                            # open the Textual interface
getcraft --config /path/config.toml # open with a particular archive configuration
getcraft --help                     # CLI help; scripts/subcommands remain compatible
```

The dark interface has seven pages: dashboard, repositories, settings, synchronization,
library, offline verification and retention. Opening it only inspects local metadata/files;
it never automatically downloads, edits preferences or prunes anything. Missing history
is shown as unknown. Dashboard storage counts logical file bytes, including metadata.

Use `1`–`7` or the sidebar to navigate; arrows/Enter select, Tab/Shift+Tab switch controls,
Space toggles selections, `/` focuses project search, `?` opens help, Esc returns/cancels,
and `q` exits. Dialogs use Esc/Cancel. During a download Esc requests safe cancellation;
wait for the operation to settle before quitting. Network reads can delay cancellation.
Read-only queries and retention application finish safely before closing; retention cannot
be interrupted halfway from the UI. Panels/forms scroll on small terminals; 90×30 or larger
is more comfortable, and narrow terminals display a navigation hint.

- **Repositories:** add by URL/name, search, enable/disable, remove monitoring with a
  confirmation, inspect releases and edit per-project preferences. Existing backups survive
  removal; projects with pins must first be unpinned or simply disabled.
- **Settings:** edit archive directory, version count, platforms, architectures and formats.
  Detect proposes host targets inside the form; Save is still required. Cancel leaves TOML
  unchanged. Repository forms can restore global inheritance for review before Save.
  Invalid TOML can be explicitly repaired in a validated text editor without restarting.
  Changing the archive directory does not move existing backups.
- **Sync:** choose one project or all enabled projects, preview selected/ignored/ambiguous
  assets and transfer estimates, then explicitly confirm. Per-file byte progress, overall
  processed-file counts and downloaded/reused/failed outcomes are shown. Cancellation
  discards the current `.part`, retains validated files and records retriable partial state.
- **Library:** browse project → version → platform → architecture → file. Inspect hashes,
  integrity, archive dates, paths, generated installation guidance and pins; verify offline.
  Installers and documentation commands are never executed.
- **Retention:** simulate first; review exact paths, bytes and reasons, then confirm deletion.
  Existing source availability, inventory, full hash, pin, coverage, audit and concurrency
  safeguards apply again under the archive lock. Changed configuration invalidates approval.

The TUI uses the same TOML and backup layout as the CLI. Authentication remains an
external `GITHUB_TOKEN`; no credential form or installer execution is provided. Reports
and advanced unattended options remain available through the CLI. No scheduling is enabled.
See [validation and screenshots](docs/M3_6_VALIDATION.md).

## Target preferences and first-time setup (M3.5)

```bash
getcraft config detect                         # show host and suggestions only
getcraft config detect --apply --interactive   # review targets/formats, then confirm
getcraft config detect --apply --yes           # explicitly accept suggestions unattended
getcraft config detect --apply --dry-run       # preview without saving
getcraft config show
getcraft config show --repo storytold/photocraft
getcraft config platforms
getcraft config formats
getcraft config architectures
```

Detection uses the running host's OS/architecture and, on Linux, `/etc/os-release`
through Python's standard API. It does not change the system or constrain archive
targets to the current machine. Fedora x86_64 suggests Linux x86_64 AppImage, Flatpak
and RPM; Windows x86_64 suggests Windows installers; macOS ARM64 suggests DMG/PKG,
ARM64 and universal. Unknown hosts/architectures require explicit target choices.
No suggestions are applied automatically and existing configs are not eagerly migrated.

Choose any combination, globally or per repository:

```bash
getcraft config platforms --set linux,windows
getcraft config architectures --set x86_64,ARM64,universal
getcraft config formats --platform linux --set AppImage,flatpak,rpm
getcraft config formats --platform windows --set msi,exe
getcraft config platforms --repo storytold/photocraft --set linux
getcraft config formats --repo storytold/photocraft --platform linux --set flatpak
getcraft config architectures --repo storytold/photocraft --set x86_64
getcraft config architectures --repo storytold/photocraft --reset
```

The three editing commands support `--interactive`, `--dry-run` and `--reset`.
Without `--set`, `--reset` or `--interactive`, they only show effective values.
`--reset` removes the named override to restore inheritance. Global reset falls back
to legacy `[platforms]` flags/defaults, if present. Format reset is per platform.
`--set` accepts a nonempty comma-separated list. For a completely disabled platform,
remove it from `platforms`; an empty per-platform format array in TOML also disables
all its formats. `amd64`/`x64`/`x86-64` normalize to `x86_64`, and `aarch64` to `arm64`.
Format names are case insensitive at configuration time. Config changes are written
atomically; changes made while a review prompt is open cause an abort rather than
silently overwriting pins or other edits.

Example Fedora-oriented configuration, with an independent Windows repository override:

```toml
[archive]
path = "~/SoftwareArchive"
keep_versions = 3

[selection]
platforms = ["linux"]
architectures = ["x86_64"]

[selection.formats_by_platform]
linux = ["appimage", "flatpak", "rpm"]
windows = ["msi", "exe"]
macos = ["dmg", "pkg"]

[[repositories]]
owner = "storytold"
repo = "photocraft"
enabled = true
# Uncomment to override global targets for this repository:
# platforms = ["windows"]
# architectures = ["x86_64"]
# formats_by_platform = { windows = ["msi"] }
```

Canonical global `selection.platforms` overrides legacy `[platforms]` booleans;
a repository's platform/architecture list replaces the global list. Per-platform
format overrides merge by platform, with repository entries taking precedence.
Legacy flat `formats = [...]` remains supported: it is intersected with each platform's
formats. A repository's flat list overrides the global format map; its own explicit
per-platform entries can then override that list. An empty legacy flat list means
all supported formats, while an empty entry such as `linux = []` in the map means none.
Detection updates only suggested platform-format entries, preserving other OS entries
and repository overrides. Saving may normalize TOML formatting/aliases; loading alone
never rewrites the original file. Pins, registry entries and retention values are retained.

The same planner drives `check` and `sync`. Every asset is `SELECTED`, `IGNORED` or
`AMBIGUOUS`, with an explanation. Unknown platform/architecture needs an explicit
`include_assets` rule, unless a known format is already excluded for all chosen targets.
Conflicting OS/format markers require review even with an include rule. Intrinsically
platform-specific extensions are checked alongside filename evidence; a Linux-marked
EXE or Windows-marked AppImage is not automatically accepted. Generic ZIP/tar containers
are allowed only with explicit reviewed inclusion and usable target evidence; contents
are not unpacked or inspected. Known unrequested x86/RISC-V/FreeBSD assets are ignored
by policy rather than mistaken for absent x86_64 Linux installers.

Shared checksum/signature documents remain selected with relevant installers. A
sidecar that names a known ignored installer is ignored for future downloads; generic
verification documents are conservatively retained when their scope is unknown.
Metadata alone cannot make an installer release complete. No relevant installer means
no backup selection, not success based solely on a checksum file.

`check` reports exact requested platform/format/architecture tuples as published,
not published or ambiguous; filtered files have separate ignore reasons. Selected
files show whether the local copy is present, missing, corrupt, untracked or needs
identity review. Estimates include verification metadata and subtract reusable local
files after identity/size/hash checks. They are not a disk-space reservation, and
changed remote identity still blocks actual sync for manual review.

`status` and all report formats show current preferences separately from historical
integrity. Offline selection applies to archived files only, without claiming knowledge
of new upstream assets. `no_installers_selected` is explicit. A previous valid Windows
backup stays valid after choosing Linux; existing files are not deleted. Configuration
edits, check, status, ordinary report and offline verify do not rewrite manifests.
An explicit sync retains deselected file records/data and records its new selection;
existing required-file verification and the conservative M3 prune policy remain intact.
No automatic retention, dependency installation or M4 scheduling is enabled.

See [M3.5 validation](docs/M3_5_VALIDATION.md) for the real PhotoCraft dry-run and
estimated 72.95% transfer/storage reduction compared with the broad default plan.

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
corresponding global lists. Prefer `formats_by_platform` for platform-specific choices;
the legacy empty `formats` list means all supported formats.
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
