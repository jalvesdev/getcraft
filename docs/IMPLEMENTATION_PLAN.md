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
