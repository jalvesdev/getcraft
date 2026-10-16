# Instructions for coding agents

## Mission
Implement GetCraft according to `docs/PRD.md`, `docs/ARCHITECTURE.md`, and `docs/IMPLEMENTATION_PLAN.md`. Keep the scope incremental and the archive safe.

## Workflow
1. Inspect the repository and read the documents before changing code.
2. Start with the first incomplete milestone in `docs/IMPLEMENTATION_PLAN.md`.
3. Make a short implementation plan, then implement in small reviewable increments.
4. Add tests for new behavior and regressions. Use mocked HTTP fixtures in unit tests.
5. Run formatting, linting, typing (if configured), and tests before each commit; document unavailable checks.
6. Commit each coherent increment with conventional-style messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). Do not combine unrelated work.
7. Push commits to the configured GitHub remote only when authenticated and authorized. Never rewrite remote history or force-push.
8. Summarize changes, test results, commit SHAs, and remaining limitations.

## Non-negotiable safety rules
- Never commit downloaded binaries, archives, local inventories, credentials, logs, or `.env` files.
- Do not run downloaded installers or arbitrary release scripts.
- Treat GitHub release titles, descriptions, filenames, and URLs as untrusted input. Prevent path traversal and command injection.
- Do not request sudo, alter system configuration, or enable a timer without explicit user approval.
- No automatic deletion until a replacement archive is verified complete; dry-run and explicit opt-in for prune.
- Never claim offline installability without verifying preserved dependencies in a compatible isolated environment.
- Do not invent repository names for the other twelve initial projects; only `storytold/photocraft` is confirmed.
- Use actual GitHub API release data, not HTML scraping, unless a documented fallback is approved.

## Architecture and quality
- Python >=3.12; `src/` layout; typed code where practical.
- Prefer `httpx`, `typer`, `rich`, `packaging`, `pytest`; justify other dependencies.
- Keep GitHub API, asset classification, downloader, archive store, retention, CLI, and reporting separate.
- Treat incomplete or ambiguous asset classification as a visible warning, not silent success.
- Persist manifests atomically; use checksums and stable identifiers to support idempotency.
- Support `--dry-run` for mutating operations.

## Git policy
- Default branch `main`; never commit directly to a protected branch if branch protection requires a PR.
- Use conventional commits, small scope, and clear messages.
- Do not amend or reset user commits without explicit permission.
