# Architecture — GetCraft

## Modules
- `cli`: Typer commands and user feedback.
- `config`: TOML registry, global defaults, per-repository overrides, atomic config writes.
- `github`: GitHub REST client, pagination, auth, rate limits, release/asset DTOs.
- `selection`: stable-release ordering, binary asset classification, platform/architecture filters.
- `download`: streamed/resumable downloads, retries, temporary files, hash verification.
- `storage`: safe paths, manifests, local inventory, atomic updates, file locking.
- `retention`: conservative three-version policy, dry-run planning, explicit pruning.
- `reports`: JSON and Markdown summaries and per-release install instructions.
- `automation`: sample systemd user service/timer.

## Storage
Archive root is configured independently from the Git working tree. Suggested:

```text
~/SoftwareArchive/
  storytold/
    photocraft/
      v0.9.0/
        linux/x86_64/...
        windows/x86_64/...
        macos/arm64/...
        manifest.json
        README.md
  inventory.json
  reports/
  logs/
```

Use exact owner `storytold`. Preserve original asset filenames. Sanitize untrusted path segments. Use stable asset IDs to avoid collisions.

## Data model
Repository: owner, repo, enabled, platform/architecture policies, retention.
Release: release_id, tag, published_at, prerelease, draft, status.
Asset: asset_id, original filename/URL, platform, architecture, bytes, digest, local path, verification status.

## Sync transaction
1. Acquire lock and load validated config.
2. Query release metadata and select eligible releases.
3. Classify assets and produce a download plan.
4. Download to temporary files; verify size and checksums.
5. Atomically publish complete files and manifest.
6. Update inventory atomically; report incomplete versions.
7. Never prune during sync; retention is a separate explicit operation.

## Dependencies
Initial release archives official binary assets only. An optional future dependency-preservation subsystem may capture Flatpak runtimes and distribution package dependency sets. Do not label the MVP as fully offline-restorable.

## M2 implementation contract

`download` provides HTTPS allowlisted streaming, bounded retries, disk checks,
SHA-256 and GNU/BSD SHA256 parsing. No shell, installer execution, archive extraction,
or unchecked Range resumption is used. API tokens are confined to API discovery.

`selection.plan_release` applies global `[platforms]` and `[selection]` policies,
then repository list overrides (`platforms`, `architectures`, `formats`,
`include_assets`, `exclude_assets`). Metadata signatures/checksums are preserved;
ambiguous binary assets require explicit inclusion or exclusion. Unpublished platforms
are recorded separately from transfer failures. ZIP/tar binary contents remain unverified.

`archive` owns portable path validation, symlink refusal, atomic JSON writes,
OS advisory locking, manifest schema validation and offline file inspection.
`sync` orchestrates API discovery, three-release backfill, older managed-release repair,
metadata-first transfers and idempotent reuse. Changed remote IDs/digests at an existing
path fail safely for manual review. All archive mutations run under one root lock.
Manifests are authoritative; the legacy `storage.inventory` reader remains compatible
with M1 and the inventory schema 1 index. `archive.rebuild` reconstructs that index
from schema 2 release manifests only after a successful scan. A failed scan preserves
the previous index. CLI `verify --rebuild-inventory` supports offline recovery.

Pending manifests are published before first transfers to journal stable identities.
Asset records include original metadata, relative path, local SHA-256, API digest,
optional published SHA-256, archive timestamp and pending/verified/failed status.
Release states are complete/partial/failed. File verification means size/hash integrity,
not publisher authentication. Existing deselected records/files are retained. Index
rows reflect current disk inspection; per-release recorded states are retained in manifests.

Atomic metadata updates use file fsync, replace and directory fsync on POSIX.
Windows uses file fsync and replace; directory fsync is unavailable there. File locks
use flock on POSIX and msvcrt byte locking on Windows. These primitives require a
trusted archive directory and a filesystem honoring advisory locks and atomic rename;
protection against hostile concurrent local filesystem writers is outside this model.
No automatic retention deletion is implemented, irrespective of prune_after_sync.

## M3 implementation contract

`retention.prepare` creates an auditable plan using live Releases API data, the existing
inventory reader, offline inspection and full archive fingerprints. It rejects stale
indexes/invalid manifests and protects incomplete project backups. Release ordering
reuses `selection.ordered`; stable membership is confirmed by current upstream ID/tag.
The newest configured number of verified complete releases are retained, plus exact
TOML `pinned_versions`. Every replacement must cover candidate platform/architecture/
format combinations. Releases containing unlisted files/directories are never removed.

`retention.apply` obtains the existing root lock and prepares the plan again. It must
match the approved fingerprint, configuration and source state exactly. It persists
`.getcraft/prune/<uuid>.json` atomically, checks API availability and content again,
unlinks enumerated files only (manifest last), removes empty known directories and
rebuilds the inventory. There is no rmtree, automatic sync retention, implicit apply,
or reliance on a cached API response when the source cannot be contacted. An error
stops remaining deletion; an interrupted old candidate is visible to offline verify.
Kept replacement releases/pins are not mutated by pruning. The CLI requires --apply
and confirmation, or the separate explicit --yes flag for non-interactive use.

Fingerprints include filenames, device/inode, mode, size, mtime and SHA-256 of regular
files, including unknown files. `.getcraft/` runtime data and `.getcraft.lock` are
excluded because the apply audit is written after approval. Static symlinks and special
files fail validation. The trusted-directory/advisory-lock threat model from M2 remains:
this does not defend against a privileged hostile writer swapping filesystem entries
between syscalls, or a filesystem ignoring atomic rename/locking semantics.

`reports` renders per-release installation READMEs, JSON, Markdown and static HTML.
Sync writes guidance and records its SHA-256 in the existing schema-2 manifest;
--write-readmes migrates existing M2 releases. Edited/unmanaged files are preserved.
The existing atomic writer now shares a UTF-8 text implementation for JSON and guidance.
Catalogs link to relative local assets and READMEs; text is escaped and shell command
examples quote original filenames. CSP and a resource-free HTML document avoid script
execution and network dependencies. No generated installation command is executed.

`.getcraft/knowledge.json` records latest stable metadata observed during successful
API discovery and sync completion/results. Reports read it offline and mark absent
history unknown, while manifests remain the authority for current file integrity.
`.getcraft/reports.json` records generated output hashes to prevent clobbering user
files. Catalog outputs are confined to non-hidden filenames at the archive root;
per-release README files retain their established location. Logical size accounting
includes regular file bytes, not filesystem allocation/deduplication/compression.
