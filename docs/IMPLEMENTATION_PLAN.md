# Implementation plan

## M0 — Scaffold
- [x] Initialize Python package with `pyproject.toml`, lint, tests, and CLI entry point.
- [x] Add TOML configuration loader, sample config, and `.gitignore`.
- [x] Configure GitHub Actions test workflow.
- [x] Commit: `chore: scaffold getcraft project`.

## M1 — Registry and discovery
- [x] Implement `repo add/list/enable/disable/remove` with validation.
- [x] Implement GitHub Releases API client with pagination and rate-limit handling.
- [x] Implement `check` and release ordering, including irregular tags.
- [x] Tests and commit: `feat: discover repositories and releases`.

## M2 — Archive and verification
- [x] Implement platform/architecture asset classification and overrides.
- [x] Implement safe downloads, hashes, manifests, and local inventory.
- [x] Implement `sync`, `status`, and `verify`.
- [x] Tests and commit: `feat: archive and verify release assets`.

## M3 — Retention and reporting
- [x] Implement safe retention with `prune --dry-run` and explicit confirmation.
- [x] Generate installation READMEs and Markdown/JSON reports.
- [x] Tests and commit: `feat: add safe retention and reports`.

## M3.5 — Platform, format and architecture preferences
- [x] Add host detection and reviewable global/repository configuration commands.
- [x] Explain selected, ignored and ambiguous assets through shared selection rules.
- [x] Integrate check/sync estimates and offline status/report policy views.
- [x] Preserve historical integrity, verification metadata and legacy TOML compatibility.
- [x] Demonstrate Fedora x86_64 PhotoCraft selection without asset downloads; validate and document.

## M4 — Scheduling and hardening
- [ ] Provide optional systemd user service/timer (not auto-enabled).
- [ ] Test interruption recovery, no duplicate downloads, low disk, checksum failures.
- [ ] Documentation and commit: `feat: add optional scheduled sync`.

## Acceptance gate
After each milestone run the available lint/test checks, review `git diff`, commit and push to the configured remote if permitted. Never push secrets or installer archives.

## M0/M1 scope clarification

M1 advanced advisory asset classification, read-only inventory comparison and status.
M2 now adds filtered archive downloads, manifests, inventory writes and offline verification.
M3 now provides separate explicit prune; sync still never deletes.

## M2 execution plan

1. Add bounded streaming downloads, path validation, locking and atomic metadata primitives.
2. Apply selection policies and orchestrate idempotent sync with published SHA-256 checksums.
3. Expose offline verify, live status and inventory reconstruction; test failure recovery.
4. Document the contract, run all checks, demonstrate PhotoCraft dry-run and report size
   before requesting approval for large real downloads. No retention deletion in M2.

## M3 execution plan

1. Fail-closed retention plans: fresh source availability, index/manifest agreement,
   full local hash verification, stable-release counting, per-project limits and pins.
2. Require --apply plus confirmation/--yes, re-plan under lock, persist audit before
   unlinking only enumerated managed files. Any changed state aborts; never rmtree.
3. Generate managed installation READMEs and offline JSON/Markdown/HTML reports,
   including preserved coverage, storage, pins and last-known discovery/sync state.
4. Validate with temporary archives only; demonstrate dry-run without touching real assets.

## M3.5 execution plan

1. Keep M0–M3 contracts and conservative pruning unchanged; use explicit configuration edits.
2. Add canonical format maps per platform, aliases, safe host suggestions and atomic TOML writes.
3. Reuse a single explainable selection engine for discovery, sync and offline policy previews.
4. Estimate transfer bytes by checking local managed identities/hashes; do not rewrite historical
   manifests merely to show new preferences. Validate with mocks and a real API dry-run.
