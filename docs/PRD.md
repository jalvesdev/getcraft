# Product Requirements Document — GetCraft

## Problem
Software installers can disappear or be replaced. Users need a curated, verifiable local archive of official releases for Windows, macOS, and Linux without archiving entire source repositories.

## Users and environment
Initial operator: Fedora Linux desktop, with eventual NAS storage. Initial scope: 13 GitHub repositories by one developer; only `storytold/photocraft` is currently specified. Future repositories may belong to any developer or organization.

## Functional requirements

### Repository registry
- Add using a GitHub HTTPS URL or `owner/repo`; validate existence; prevent duplicates.
- List, enable, disable, and remove repositories. Removing monitoring does not delete archived data.
- Support global defaults and per-repository overrides for platforms, architectures, asset filters, and retention.
- Initial sync can backfill the latest three eligible releases.

### Release discovery
- Use GitHub REST Releases API with pagination, ETag/rate-limit awareness, and optional token via environment variable.
- Exclude drafts and prereleases by default. Do not rely only on `/releases/latest`.
- Rank SemVer tags appropriately; document fallback for irregular tags and ambiguous ordering.
- Compare remote releases to the local archive inventory, **not** installed desktop application versions.

### Asset selection
- Windows: exe, msi, msix, msixbundle, binary zip.
- macOS: dmg, pkg, app.zip, binary zip.
- Linux: flatpak, flatpakref, AppImage, deb, rpm, binary tar archives.
- Identify x86_64/amd64, arm64/aarch64, universal and unknown architectures; unknown assets require review or explicit policy.
- Preserve published checksum/signature files. Do not confuse source archives with binary distributions.
- `flatpakref` alone is a pointer, not a self-contained installer; flag it accordingly.

### Download, integrity and storage
- Stream to temporary files; retries, backoff, timeouts, disk-space checks, and atomic finalization.
- Store release ID, tag, published timestamp, asset ID, filename, original URL, size, SHA-256, official digest/signature if available, platform and architecture.
- Validate official digests where provided; locally calculated SHA-256 alone does not establish authenticity.
- Keep source code and archive files in separate paths. Never add downloaded installers to Git.
- Generate per-release `manifest.json` and `README.md` with format-specific installation instructions and compatibility warnings.
- Expose partial/incomplete/verified states accurately; idempotent reruns must not redownload valid assets.

### Retention
- Keep three most recent **complete verified stable releases** per project by default, configurable per repository.
- Never prune until a replacement is fully downloaded and validated.
- Support exact protected/pinned release tags, additional to the ordinary retention window.
- Prune simulates by default. Physical deletion requires --apply and confirmation or explicit --yes. Sync never deletes.

### CLI
- `getcraft repo add|list|enable|disable|remove`
- `getcraft check`, `getcraft sync`, `getcraft status`, `getcraft verify`, `getcraft report`, `getcraft prune`
- Support `--repo`, `--all`, and `--dry-run` where relevant; report failures and meaningful exit codes.

### Automation
- Optional Fedora systemd user service/timer, installed and enabled only on user request.
- Avoid overlapping runs; tolerate offline conditions; log clearly.

## Nonfunctional requirements
- Python >=3.12; safe filesystem operations; no privileged commands by default.
- Unit tests with fake GitHub responses; integration tests behind opt-in flags.
- No token leakage; sanitize API-provided paths; no installer execution.
- Predictable storage layout and portable JSON/TOML metadata.

## Non-goals for MVP
- Rebuilding applications from source.
- Automatically downloading every repository by a developer.
- Fully offline dependency preservation for all three operating systems.
- Executing or installing downloaded programs.
- Hosting a web service or database.

## Acceptance criteria — MVP
1. Add `storytold/photocraft` by URL and inspect its release assets.
2. Backfill up to three eligible stable releases, with Windows/macOS/Linux binaries when published.
3. A second sync performs no duplicate downloads for valid assets.
4. An interrupted download cannot be mistaken for a verified file.
5. Invalid checksums cause a visible failure and no pruning.
6. The manifest and installation README accurately describe archived files and limitations.
7. Prune dry-run identifies candidates without deleting; actual prune requires explicit opt-in.
8. Tests cover releases without binaries, irregular tags, partial downloads, and ambiguous assets.

## Open decisions
- Confirm whether GitHub repo should be public or private before remote creation.
- Obtain the other twelve repository URLs; do not invent them.
- Choose archive directory and storage capacity.
- Choose default architecture policy (all published architectures vs. selected architectures).

## M2 scope decisions

- `keep_versions` controls the newest eligible releases selected for backfill; it never
  authorizes removal. Older managed releases still published by the API are rechecked.
- Default architecture policy selects known x86_64, arm64 and universal assets on all
  enabled platforms, regardless of host OS. Other/ambiguous architectures need explicit rules.
- All selected formats are required; unavailable upstream platforms are recorded separately,
  while unresolved asset classifications prevent a complete release state.
- Initial offline verification checks integrity, not signature authenticity or offline
  installability. Signatures are preserved; supported published checksums are SHA-256
  in GNU/BSD basename formats. Unsupported checksums generate warnings.
- Range resume is deferred; incomplete transfers restart. No code is executed.
- Installation README generation remains in M3; M2 writes detailed JSON manifests.
- Public release asset downloads are supported. Private authenticated downloads and
  persistent API ETag caching remain limitations; tokens are used for API discovery only.

## M3 acceptance and safety decisions

- Retention counts complete verified stable releases, never installers. Pinned tags
  are stored per registered project in TOML and do not consume normal retention slots.
- A candidate requires `keep_versions` newer complete local replacements, each covering
  its platform/architecture/format combinations. Partial/corrupt project backups block
  pruning. Drafts/prereleases and unavailable upstream releases are preserved.
- Every prune plan requires a live official API response and a valid inventory agreeing
  with authoritative manifests and current hashes. Missing/corrupt indexes must be
  explicitly reconstructed; they never authorize deletion. Unavailable origins block apply.
- Only enumerated managed files can be unlinked. Unknown files/directories, symlinks,
  special files and modified generated guidance are preserved or cause a fail-closed abort.
- Revalidation under lock must reproduce the exact plan. Audit records precede deletion;
  source availability and file hashes are checked immediately before removal. Failed
  operations stop rather than rolling forward. Sync never triggers retention.
- Schema-2 manifests remain compatible with M2 and add an optional generated README hash.
  M3 sync generates format-specific guidance without executing commands or inventing
  application dependencies. Human-modified files are not overwritten.
- Reports support JSON/Markdown/HTML, inspect actual files offline, and record pins,
  monitored projects, release coverage, problems and logical byte usage. HTML uses
  escaped text, relative local links and no required external resources.
- Latest-known stable release and last-sync timestamps are saved by M3 sync. Unknown
  historical values stay unknown. Reports do not claim current upstream availability.

M4 remains optional scheduling and further hardening. Private authenticated asset
fetches, independent signature authentication, dependency preservation, cross-host
integration testing and safe validated Range resume remain known limitations.

## M3.5 — Reviewed target selection

- Detect the host OS and architecture without privileging it as the only archive target.
  On Linux, use os-release to suggest Fedora RPM or Debian DEB alongside AppImage/Flatpak.
  Suggestions require explicit application/confirmation, with interactive and unattended modes.
- Offer `config show/detect/platforms/formats/architectures`, global policy and repository
  overrides, atomic TOML persistence, aliases and dry-run. Preserve existing settings and pins.
- Keep legacy `[platforms]`, flat format lists and schema-2 manifests compatible. No eager
  file migration or default narrowing of existing installations.
- Use explicit per-platform format maps, with compatible native installers and generic
  containers requiring manual inclusion. Unknown/conflicting evidence never silently approves
  a download. Record selected/ignored/ambiguous decisions and exact target availability.
- Preserve shared verification metadata; skip known sidecars for ignored binaries. A release
  cannot be complete when no relevant installer is selected.
- Check/sync share policy and disk-aware transfer estimates. Status/report expose effective
  preferences and archived-file selection independently of historical integrity. Offline verify
  continues to validate manifests/files without consulting current target preferences.
- A preference edit never deletes archives or rewrites historical manifests by itself. Explicit
  sync can record a revised selection while preserving previously archived records/files.
  Prune policy is unchanged; only its existing explicit path can delete verified candidates.
- M4 scheduling is deliberately not part of M3.5.
