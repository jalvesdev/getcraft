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
7. Never prune implicitly unless explicitly configured and safe.

## Dependencies
Initial release archives official binary assets only. An optional future dependency-preservation subsystem may capture Flatpak runtimes and distribution package dependency sets. Do not label the MVP as fully offline-restorable.
