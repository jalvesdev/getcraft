# M3.5 validation — target preferences

Validated on 2026-10-16 with Python 3.14.7. The actual detection command reported
Fedora Linux 44 (Workstation Edition), Linux x86_64. No M4 scheduling was implemented.
The branch started clean and synchronized with origin/main. Retention code/policy
was not changed, and no real installers were downloaded or deleted.

## Automated checks

- `pytest -q`: **160 passed** (M3 baseline 124; 36 additional cases).
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `git diff --check`: passed.
- No static type checker is configured. Python 3.12/3.13 and native Windows/macOS
  integration were not locally executed; detection for those hosts uses mocked fixtures.

New coverage includes Fedora x86_64, Windows AMD64, macOS ARM64/universal, Debian ARM64,
unknown hosts, multiple targets, universal files, OS/format conflicts, bounded CPU-name
matching and aliases, repository overrides, old flat format lists/platform flags,
inline/nested TOML maps, explicit reviewed archives, metadata-only plans, invalid
preferences, interactive/noninteractive edits, canceled/dry-run setup, concurrent config
edits preserving pins, byte estimates and identity conflicts, named sidecar filtering,
check/sync agreement, ignored/missing/ambiguous/not-published distinctions, narrower
preferences preserving existing files, removed repositories and offline verification.
All pre-existing M0–M3 tests, including destructive tests confined to pytest temporary
archives, continue to pass.

## Available configuration commands

```bash
getcraft config show
getcraft config show --repo storytold/photocraft
getcraft config detect
getcraft config detect --apply --interactive
getcraft config detect --apply --yes
getcraft config platforms --set linux
getcraft config formats --platform linux --set AppImage,flatpak,rpm
getcraft config architectures --set x86_64
getcraft config formats --repo storytold/photocraft --platform linux --set flatpak
getcraft config architectures --repo storytold/photocraft --reset
```

The editing commands also accept `--interactive` and `--dry-run`. Detection is only a
suggestion until explicitly applied; unrelated retention settings, pins and other
platform format entries survive application. Config reads never rewrite the original
TOML. Explicit saves use atomic replacement and reject edits made during user review.

## PhotoCraft demonstration using official release metadata

Two read-only commands were executed with an isolated configuration under `/tmp`:

```bash
getcraft --config /tmp/getcraft-m3-5-demo.toml check --repo storytold/photocraft
getcraft --config /tmp/getcraft-m3-5-demo.toml sync --dry-run
```

The profile used:

```toml
[archive]
path = "/tmp/getcraft-m3-5-demo-archive"
keep_versions = 3
include_prereleases = false

[selection]
platforms = ["linux"]
architectures = ["x86_64"]
formats_by_platform = { linux = ["appimage", "flatpak", "rpm"] }

[[repositories]]
name = "PhotoCraft"
owner = "storytold"
repo = "photocraft"
enabled = true
```

The API selected stable releases `v0.9.0`, `v0.8.2` and `v0.7.0`. Each selected exactly
three Linux x86_64 installer assets plus the shared `SHA256SUMS.txt` document. No files
existed at the demo archive path, so selected bytes equaled estimated download bytes.
The archive directory was still absent after the commands; no transfer/lock was created.

| Release | Selected assets | Ignored assets | Ambiguous assets | Estimated bytes |
| --- | ---: | ---: | ---: | ---: |
| v0.9.0 | 4 | 22 | 0 | 220,828,829 |
| v0.8.2 | 4 | 22 | 0 | 215,929,848 |
| v0.7.0 | 4 | 20 | 0 | 206,864,806 |
| Total | 12 | 64 | 0 | **643,623,483** |

Selected v0.9.0 files:

| File | Bytes |
| --- | ---: |
| photocraft-0.9.0-linux-x86_64.AppImage | 77,478,392 |
| photocraft-0.9.0-linux-x86_64.flatpak | 61,114,608 |
| photocraft-0.9.0-linux-x86_64.rpm | 82,233,240 |
| SHA256SUMS.txt | 2,589 |

The other two releases selected the equivalent three versioned Linux x86_64 filenames
and their respective checksum documents. The output marked selected local files as
`missing`; this was not confused with upstream publication or deliberate filtering.

The v0.9.0 ignored files were:

```text
photocraft-0.9.0-freebsd-x86_64.tar.gz
photocraft-0.9.0-linux-aarch64.AppImage
photocraft-0.9.0-linux-aarch64.AppImage.zsync
photocraft-0.9.0-linux-aarch64.deb
photocraft-0.9.0-linux-aarch64.flatpak
photocraft-0.9.0-linux-aarch64.rpm
photocraft-0.9.0-linux-aarch64.tar.gz
photocraft-0.9.0-linux-riscv64.deb
photocraft-0.9.0-linux-riscv64.rpm
photocraft-0.9.0-linux-riscv64.tar.gz
photocraft-0.9.0-linux-x86_64.AppImage.zsync
photocraft-0.9.0-linux-x86_64.deb
photocraft-0.9.0-linux-x86_64.tar.gz
photocraft-0.9.0-macos-universal.dmg
photocraft-0.9.0-windows-arm64-portable.zip
photocraft-0.9.0-windows-arm64.msi
photocraft-0.9.0-windows-x64-portable.zip
photocraft-0.9.0-windows-x64.msi
photocraft-0.9.0-windows-x86-portable.zip
photocraft-0.9.0-windows-x86.msi
photocraft-cli-0.9.0-macos-universal.zip
photocraft-web-0.9.0.zip
```

Each had an explicit reason: platform, architecture or format not selected, or auxiliary
update metadata excluded. Generic ZIP assets were outside all selected target formats;
they were not silently approved from their extension. Truly unknown architecture RPM
fixtures instead produced `AMBIGUOUS`, with no automatic download until explicit review.
Conflicting Linux/EXE or Windows/AppImage evidence is never auto-approved by an include glob.

## Estimated savings

The broad sample-config plan was queried again through the official API with
`getcraft --config config/config.example.toml sync --dry-run` and selected the same
three releases, all three OSes and known default architectures:

| Policy | Selected bytes |
| --- | ---: |
| Broad default plan | 2,379,299,926 |
| Fedora x86_64 AppImage/Flatpak/RPM | 643,623,483 |
| Avoided transfer/payload storage | **1,735,676,443 (72.95%)** |

These are estimates for initial asset preservation, including checksum documents and
excluding generated README/manifest overhead, filesystem allocation and external runtime
dependencies. No space was actually reclaimed, because nothing was deleted. Existing
intact managed assets reduce future transfer estimates; unit tests check zero-byte
repeat downloads and repair estimates for corrupted assets.

## Compatibility and limits

- Existing all-platform defaults stay broad until explicitly edited; host detection
  never silently narrows an existing installation. Legacy booleans and flat lists remain valid.
- Config changes and read-only commands leave historical manifests byte-identical.
  An explicit sync can record revised selection requirements while retaining old records/files.
- Offline status/catalogs distinguish historical integrity from current archived-file
  selection; no matching installer is labeled `no_installers_selected`, not complete.
  Offline verify continues to check recorded hashes independent of preferences.
- Generic checksum/signature documents are conservatively kept. A named sidecar for a
  known excluded binary is omitted from future downloads; previously archived metadata
  is never deleted. `.zsync` remains auxiliary update data, not required integrity metadata.
- Classification relies on bounded filename markers and intrinsic formats, not content
  execution or archive extraction. Ambiguous distributions need explicit review. New
  containers/architectures may need classifier support; unknown formats are never auto-approved.
- Estimates require reading/hashing local files and are not disk reservations. Changed
  identities or unmanaged files can still require review before actual transfer.
- Retention/prune safeguards, independent signature authentication limitations, offline
  installation caveats and the trusted-filesystem model from M3 remain unchanged.
