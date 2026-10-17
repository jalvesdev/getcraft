# M3 validation

Validated on 2026-10-16 with Python 3.14.7 on Linux. M0–M2 behavior remains covered.
No production archives or real installers were deleted. Only pytest temporary
archives with synthetic text assets were used for destructive tests. The real
PhotoCraft M2 demonstration archive was not modified by M3 validation.

## Checks

- `pytest -q`: **124 passed** (M2 baseline: 77; 47 additional tests).
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `git diff --check`: passed.
- Static typing: no checker configured.
- Python 3.12/3.13 CI jobs and Windows/macOS hosts were not locally executed.

Mocked HTTP fixtures exercise the official API client without network access.
Coverage includes release-count retention with multiple installers, per-project
limits, pinned versions, incomplete/corrupt/missing files, missing/corrupt/stale
inventory, unavailable API, unavailable source just before deletion, unknown files
and directories, symlinks/traversal, changed source/config/archive state, tampered
plans, repeated prune, read-only simulation, confirmation and explicit unattended
apply, audit write failures, generated guidance, readme preservation, quoted commands,
offline catalogs, HTML escaping, local links and malformed last-known metadata.

## Repeatable dry-run demonstration

```bash
pytest tests/test_m3_demo.py -q -s
```

This test creates five synthetic complete PhotoCraft releases, each with Windows,
macOS and Linux assets. It protects `v1.0`, creates installation READMEs and a static
HTML catalog, then invokes the actual CLI with mocked API responses:

```text
getcraft --config <temporary-demo.toml> prune --repo storytold/photocraft --dry-run

Would remove storytold/photocraft v2.0: 5708 bytes
  README.md, three installer fixtures and manifest.json, with individual sizes/hashes
  reason: outside newest 3 complete stable releases; equivalent coverage verified
Keep storytold/photocraft v5.0: verified retention window
Keep storytold/photocraft v4.0: verified retention window
Keep storytold/photocraft v3.0: verified retention window
Keep storytold/photocraft v1.0: pinned
Candidates: 1 releases; 5708 bytes
Simulation only; no archive changes.
```

An exact before/after archive fingerprint is asserted. The test prints the temporary
catalog location; open its `catalog.html` directly with the rest of that archive.
No server, scripts, CDN or network access is required. Other tests exercise `--apply`
only on their own temporary archives, and confirm that a repeat plan has no candidates.

The CLI was also checked through `prune --help`, `report --help` and the existing
sync/verify integration fixtures. Generated output and inventories remain outside Git.

## Policy and known limits

- Simulation is the default. Real deletion requires `--apply` plus interactive
  confirmation or the separate explicit `--yes`. No automatic pruning in sync.
- Inventory must agree with manifest/file verification. Missing/corrupt indexes block
  prune; offline `verify --rebuild-inventory` is the explicit recovery operation.
- Any partial/corrupt project release blocks pruning for that project. Pinned versions
  are extra to the retention window. Replacement coverage must include each candidate's
  platform/architecture/format combinations, so more versions can be retained.
- Source data is fetched again under the archive lock and before each candidate.
  Changed remote metadata can conservatively invalidate a plan. Every listed file
  is hashed before deletion. Only managed assets/manifests/unchanged generated READMEs
  and their empty directories are removed, with an audit published first.
- Full fingerprinting is expensive for large archives. Runtime/audit files under
  `.getcraft/` and the lock are excluded from state equality, but symlink paths are
  still rejected. Advisory locking assumes a trusted directory and compatible filesystem;
  it does not defeat privileged hostile local writers racing between system calls.
- Interrupted physical pruning is not an all-or-nothing filesystem transaction.
  It can leave a partially removed old candidate. Retained replacements/pins remain
  intact; inspect the audit and offline verify/rebuild before retrying.
- Reports use actual local file hashes and logical byte counts. They do not query the
  network. Available-version/last-sync history is recorded by M3 sync; absent M2 history
  remains unknown. An archived timestamp is never invented as a synchronization date.
- Generated READMEs/catalogs are not overwritten after user edits. Signatures are
  preserved without independent cryptographic verification. Installers still do not
  guarantee fully offline installation or future operating-system compatibility.

## Guidance references

Generic installation examples were checked against primary format documentation:
[Flatpak](https://docs.flatpak.org/en/latest/flatpak-command-reference.html),
[AppImage](https://docs.appimage.org/introduction/quickstart.html),
[DNF](https://dnf.readthedocs.io/en/latest/command_ref.html), and
[Ubuntu package management](https://ubuntu.com/server/docs/how-to/software/package-management/).
These are optional reading links, not runtime/catalog dependencies; no installation
commands were executed and no application-specific dependencies were inferred.

## Next milestone

M4: optional user scheduling (only on explicit request), interruption hardening,
filesystem/platform integration coverage and operational recovery improvements.
Private asset authentication, signature verification, persistent ETag caching,
validated Range resume and external dependency preservation remain limitations.
