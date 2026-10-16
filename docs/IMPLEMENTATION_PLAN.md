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
- [ ] Implement platform/architecture asset classification and overrides.
- [ ] Implement safe downloads, hashes, manifests, and local inventory.
- [ ] Implement `sync`, `status`, and `verify`.
- [ ] Tests and commit: `feat: archive and verify release assets`.

## M3 — Retention and reporting
- [ ] Implement safe retention with `prune --dry-run` and explicit confirmation.
- [ ] Generate installation READMEs and Markdown/JSON reports.
- [ ] Tests and commit: `feat: add safe retention and reports`.

## M4 — Scheduling and hardening
- [ ] Provide optional systemd user service/timer (not auto-enabled).
- [ ] Test interruption recovery, no duplicate downloads, low disk, checksum failures.
- [ ] Documentation and commit: `feat: add optional scheduled sync`.

## Acceptance gate
After each milestone run the available lint/test checks, review `git diff`, commit and push to the configured remote if permitted. Never push secrets or installer archives.

## M0/M1 scope clarification

The current task advances advisory asset classification, read-only inventory comparison,
and `status` from M2. Downloads, inventory writes, manifests, verification and deletion
remain unimplemented. Classification reports uncertainty and does not approve downloads.
