# TrackHound implementation checkpoint

Review baseline: `0ce4fa81fd8adc264fbf5b78457ad097939a91e2` on `master`.
The implementation is split into dependent review branches. Nothing has been
merged or deployed, and no production database or media has been changed.

TrackHound scans mounted media with MediaInfo, stores per-user titles, seasons,
audio tracks and preference violations in SQLite or PostgreSQL, and uses Plex
for sign-in and optional metadata. A React interface supports browsing, exports,
rescans, default-audio changes, and MKV track removal. FastAPI serves the built UI.

## Review and merge order

1. [PR #42](https://github.com/TheSoloGreen/TrackHound/pull/42),
   `fix/secure-media-editing`: authorized access, explicit media-write capability,
   recoverable MKV edits, language removal plans, and deployment checks.
2. [PR #43](https://github.com/TheSoloGreen/TrackHound/pull/43),
   `fix/database-integrity`: transactional historical upgrades, database-enforced
   ownership and cascades, per-file savepoints, and verified backup/recovery.
3. [PR #44](https://github.com/TheSoloGreen/TrackHound/pull/44),
   `fix/scan-correctness`: scan settings/full rescans, Plex fallback, reconciliation,
   classification consistency, and bounded completion status.
4. `fix/ui-consistency`: draft preference saves, production deep links, shared
   cache refresh, persistent scan summaries, and frontend regression tests.

Each follow-up targets the preceding branch to keep its diff focused. After its
parent merges, retarget the next PR to `master` and check CI before merging.
Preserve the parent commit ancestry when merging this stack; squash/rebase merges
require updating dependent branches before proceeding. Historical branches outside
this sequence have not been combined or removed.

## Existing issue coverage

| Issue | Implemented behavior | Review branch |
| --- | --- | --- |
| #26 | Valid Compose environment mappings; missing-key and render checks | secure-media-editing + database-integrity |
| #27 | Transactional, versioned upgrades from actual historical schemas on SQLite/PostgreSQL | database-integrity |
| #28 | Native MKV tools, opt-in writes, capability responses, backup/restore protection | secure-media-editing |
| #29 | Full scans reanalyze unchanged files; dashboard exposes a Full scan option | scan-correctness + ui-consistency |
| #30 | Saved extension and anime detection settings applied with documented precedence | scan-correctness |
| #31 | Missing-record cleanup only after a complete uncancelled scan; user/root isolation | scan-correctness |
| #32 | Plex timeout/auth/no-server failures fall back to local analysis with one warning | scan-correctness |
| #33 | Per-user path uniqueness; a failed file does not poison the scan session | database-integrity |
| #34 | Immediate local drafts, explicit serialized saves, response cache updates, retained later edits/errors | ui-consistency |
| #35 | Saved keep-language plans, explicit overrides, exact confirmation and stale-revision rejection | secure-media-editing + ui-consistency tests |
| #36 | SPA fallback for client routes; API and missing-asset behavior retained | ui-consistency |
| #37 | Canonical anime category with manual precedence, restored movie/TV origin, refreshed issues/badges/stats | scan-correctness + ui-consistency |
| #38 | Completion refreshes all library caches; persistent outcomes and bounded expandable messages | scan-correctness + ui-consistency |
| #39 | Foreign keys on every SQLite connection, orphan cleanup, tested database cascades | database-integrity |
| #40 | Plex account allowlist enforced on login and authenticated APIs; exposure guidance | secure-media-editing + database-integrity docs |
| #41 | Consistent SQLite and PostgreSQL backups, rollback instructions, recovery integration tests | database-integrity |

Issues remain open until the corresponding implementation is merged into the
repository's default branch. Consult PR checks for the latest remote results.

## Validation

- PR #42 CI: 81 backend tests, real generated MKV editing, frontend build, both
  Compose files, production startup/health and native-tool checks passed.
- PR #43 CI: 98 backend tests passed, including historical PostgreSQL upgrades and
  backup/upgrade/restore. Frontend and container checks also passed.
- PR #44 local: 118 passed; 11 PostgreSQL/native-tool cases require CI.
- Final UI branch local: 136 backend tests passed, 11 integration cases require
  CI; 12 frontend regression tests and the TypeScript/production build passed.
- CI installs the native tools and PostgreSQL service, runs frontend tests, builds
  and smoke-tests the production container. Draft PRs do not publish images.

Commands: `cd backend && python -m pytest -q`;
`cd frontend && npm ci && npm test && npm run build`.

## Before upgrading

Follow [OPERATIONS.md](OPERATIONS.md): back up the database with its matching
`ENCRYPTION_KEY`; retain valid keys; configure `ALLOWED_PLEX_USER_IDS`. Blank
allowlists deny access. Editing stays disabled until explicitly enabled with
writable media permissions. Schema rollback requires a matching backup and app
version, rather than an unsafe destructive downgrade.

See [SCANNING.md](SCANNING.md) for exact detection, overlap, missing-file and
cancellation rules. In Settings, edit preferences locally and choose **Save
preferences**. Inputs remain editable during a save; newer changes need another
save after the first finishes. Run a **Full scan** to apply new scan preferences
to unchanged files. Location actions save individually.

Continue to use one worker/container per media library. Restart-resumable jobs,
shared multi-worker edit locks, and controlled encryption-key rotation remain
future improvements; they are outside the acceptance criteria of issues #26–41.
The latest scan summary survives navigation and completion, but resets on the
next scan or application restart.
