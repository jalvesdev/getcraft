# Codex kickoff — GetCraft

You are implementing **GetCraft**, a Python CLI to preserve official GitHub release installers for Windows, macOS and Linux.

Read `AGENTS.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, and `docs/IMPLEMENTATION_PLAN.md` before coding.

**Task:** Implement milestone M0 and then M1. Build a working, tested CLI that can add/list/disable/enable/remove GitHub repositories and check releases without downloading installers yet. Use `storytold/photocraft` as the real example; do not invent the other 12 repositories.

Constraints:
- Python >=3.12, `src/` package layout, Typer, httpx, Rich, pytest, and packaging as appropriate.
- GitHub Releases API, not website scraping.
- Archive root outside the Git checkout; never commit binaries, secrets, or runtime data.
- Handle pagination, drafts/prereleases, non-SemVer tags, rate limits, invalid repos and duplicate registry entries.
- Add automated tests using mocked responses, and document setup and CLI usage.
- Keep changes modular, typed where practical, and auditable.

Git workflow:
1. Check current branch, working tree and remote.
2. Implement M0; run tests/lint; commit `chore: scaffold getcraft project`.
3. Implement M1; run tests/lint; commit `feat: add repository registry and release discovery`.
4. Push to the configured GitHub remote if authorized and authenticated. Never force-push.
5. Report changed files, checks run, commit SHAs, and next steps for M2.

If prerequisites are missing or important design decisions are ambiguous, explain and request clarification instead of guessing. Do not claim download or offline restoration works before it is implemented and tested.

## Completion note

The kickoff above records the original M0/M1 task. M0, M1 and M2 are now implemented.
See IMPLEMENTATION_PLAN.md and README.md for the current scope; M3 is next.
