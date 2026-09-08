# TrackHound implementation checkpoint

Branch: `fix/secure-media-editing`  
Review baseline: `0ce4fa81fd8adc264fbf5b78457ad097939a91e2` on `master`

## Project overview

TrackHound scans mounted media files with MediaInfo, stores per-user shows,
seasons, audio tracks, and preference violations in SQLite or PostgreSQL, and
uses Plex for sign-in and metadata enrichment. Its React/TypeScript interface
supports filtering, exports, rescans, default-audio changes, and MKV track removal.
The application is packaged as a single FastAPI container serving the frontend.

## First implementation batch

- Restrict Plex login and existing sessions to an administrator-configured account
  allowlist. Blank configuration denies access. Reject known default and short
  production keys, including direct use of the published image. Addresses #40.
- Ship MKVToolNix and make all media writes an explicit instance opt-in. Report
  live per-file tool, mount, and permission capabilities in the API and UI.
  Apply the same policy to scan-time automatic edits. Addresses #28.
- Fix PostgreSQL Compose environment strings and validate both deployment files
  in CI. Addresses #26.
- Use the saved keep-language policy for the UI's initial pruning selection.
  Require the scan revision for explicit track indices and reject changed files.
  Show the kept and removed tracks in confirmation. Addresses #35.
- Preserve existing audio metadata on failed or unavailable analysis. Show scan
  errors and refresh related cached file/show/stat data after file actions.
  These are partial improvements for #38.
- Serialize in-process edits, bound native subprocess durations, verify remux
  output and source stability, protect prior backups, and restore the original
  after replacement failures. Keep scan discovery away from temporary remux files.
- Run manual editing and analysis off the request event loop. Broader scan worker
  changes remain outstanding.
- Add deployment, key, database-backup, and media-recovery notes in
  [OPERATIONS.md](OPERATIONS.md), contributing to #41. Automated restore rehearsal
  and key-rotation tooling remain future work.

No database migration, image deployment, or merge to `master` is part of this batch.

## Validation

- Original baseline: 38 backend tests passed; frontend production build passed.
- Updated local suite: 80 passed, 1 skipped. The skipped test needs native
  MKVToolNix executables, which are unavailable in the editing environment.
- Frontend: `npm run build` passed (TypeScript and Vite).
- CI now installs ffmpeg, MediaInfo, and MKVToolNix for a real generated MKV test
  that verifies language selection, default flags, video/subtitle retention, and
  byte-for-byte preservation of the original backup.
- CI also validates both Compose files, builds the production image, rejects
  insecure direct image configuration, checks editing tools and read-only defaults,
  and smoke-tests startup and health. Image publishing depends on these checks.
- Local regression tests cover unauthorized Plex accounts and revoked sessions,
  stale track choices, read-only paths, symlink escapes, saved language policies,
  failed probes, successful API metadata refresh, concurrent edits, remux timeout,
  existing backups, failed replacement, and failed automatic restoration.

Run from `backend`: `python -m pytest -q`. Run from `frontend`: `npm ci && npm run build`.
Consult the PR checks for native-tool and container results; those cannot run in
the local editing environment.

## Remaining work, in suggested order

| Area | Work and existing issue |
| --- | --- |
| Database correctness | Introduce versioned migrations and upgrade tests (#27); scope file-path uniqueness per user and recover failed scan transactions (#33); enable and verify SQLite foreign keys (#39). |
| Scan correctness | Honor full vs incremental scans (#29), saved extension/anime settings (#30), and reconcile deleted files only after successful discovery (#31). |
| Scan resilience | Make Plex failures degrade to local metadata (#32); move synchronous scan probes, Plex calls, and filesystem work out of the async request loop; use durable job state and shared edit coordination before adding workers. |
| Settings | Replace saves on every keystroke with a draft and explicit save or serialized partial updates (#34). |
| Classification | Apply manual anime overrides consistently, including before scan-time auto-fixes (#37). |
| Frontend consistency | Finish scan-completion cache invalidation and durable error reporting (#38); add SPA fallback for direct navigation to nested routes (#36). |
| Operations | Rehearse database restore and build controlled key rotation (#41); document tested upgrade paths and pin release dependencies. |

Existing issues are at `https://github.com/TheSoloGreen/TrackHound/issues/<number>`.
When resuming, inspect the branch and PR checks first, preserve completed work,
then select the next bounded batch from this table.
