# M2 validation

Validated on 2026-10-16 using Python 3.14.7 on Linux. The configured CI matrix also
runs Python 3.12 and 3.13; those jobs are not claimed as locally executed. No static
type checker is configured. Windows/macOS host execution was not locally exercised;
platform-independent selection and preservation have mocked fixtures for all three OSes.

## Automated checks

- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `pytest -q`: 77 passed, including the original M0/M1 tests.
- `git diff --check`: passed.

Tests cover streamed success, interruptions and restart, retries, integrity failures,
published GNU/BSD SHA256, missing assets, idempotency, corruption repair, corrupt/lost
inventory recovery, atomic write failures, low disk space, traversal/symlink refusal,
multiple platforms, explicit ambiguity policies, offline CLI verification, lock exclusion,
API failure preserving backups, remote identity conflicts, and older-release repair.

## Real PhotoCraft demonstration

The official API dry-run selected stable releases `v0.9.0`, `v0.8.2`, and `v0.7.0`:
36 assets, **2,379,299,926 bytes** total selected. No assets were downloaded by that
plan. Ambiguous assets were surfaced for explicit policy decisions.

After the user approved the reduced demonstration, a separate TOML configuration
selected Linux arm64, Flatpak format and one release. The archive was isolated at
`/tmp/getcraft-m2-demo`, outside the checkout. No installers were executed.

| Asset in v0.9.0 (release ID 412944200) | Bytes |
| --- | ---: |
| photocraft-0.9.0-linux-aarch64.flatpak | 56,541,728 |
| SHA256SUMS.txt | 2,589 |
| Total | 56,544,317 |

The installer SHA-256 was
`df11591dbc49b946886e0d0abc873f491df2e6c3f23bade9e98395dd8507a69a`.
It matched both the GitHub API digest and the developer's published SHA256SUMS entry.
This confirms integrity against those references, not independent publisher authenticity.

Commands executed with the isolated configuration:

```text
getcraft --config /tmp/getcraft-m2-demo.toml sync
  complete; downloaded=2, reused=0
getcraft --config /tmp/getcraft-m2-demo.toml verify --all
  v0.9.0 complete; exit 0 (offline)
getcraft --config /tmp/getcraft-m2-demo.toml status
  v0.9.0 complete; exit 0 (offline)
getcraft --config /tmp/getcraft-m2-demo.toml sync
  complete; downloaded=0, reused=2
```

Only source code, tests and human-written documentation are committed. The demo
configuration, installers, runtime index, manifests and command output remain outside Git.
The limited policy marks the release complete for its selected Flatpak asset and metadata;
it does not claim all upstream distributions were preserved or installation is fully offline.

## Remaining work

M3: safe explicit prune planning, conservative verified-version retention, installation
READMEs and Markdown/JSON reports. No deletion, scheduling, installer execution or
external dependency preservation was added in M2. Private authenticated asset downloads,
cryptographic signature verification, persistent ETag caching and validated Range resume
remain limitations. Filesystems used for archives must honor locking and atomic rename.
