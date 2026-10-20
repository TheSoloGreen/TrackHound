# TrackHound implementation checkpoint

This is a source/review checkpoint, not a declaration that a container has updated.
The running `/api/info` and footer are authoritative for deployed version/revision.
The [roadmap #88](https://github.com/TheSoloGreen/TrackHound/issues/88), linked PR
checks, and [changelog](../CHANGELOG.md) track implementation and release scope.

## Delivered and candidate work

- The earlier foundations shipped through PRs
  [#42](https://github.com/TheSoloGreen/TrackHound/pull/42),
  [#43](https://github.com/TheSoloGreen/TrackHound/pull/43),
  [#44](https://github.com/TheSoloGreen/TrackHound/pull/44), and subsequent UI/auth
  fixes. Their old branch-stack instructions are no longer merge instructions.
- [PR #89](https://github.com/TheSoloGreen/TrackHound/pull/89): account-owned artwork
  proxy without Plex credentials in browser-visible URLs, distinct movie identity,
  conservative language normalization/inference (#58–60).
- [0.3.0 / PR #90](https://github.com/TheSoloGreen/TrackHound/pull/90): explicit anime
  classification, main/auxiliary roles, default-count checks, exact-track selection,
  required-language removal protection, and structured issues (#61–63, #65).
- [0.4.0 / PR #91](https://github.com/TheSoloGreen/TrackHound/pull/91): durable bounded
  jobs, saved progress/outcomes, probe cancellation/deadlines, restart reporting,
  and a single-worker catalog lock (#64).
- [0.5.0 candidate / PR #92](https://github.com/TheSoloGreen/TrackHound/pull/92):
  cached-only audio policy reevaluation and freshness reporting (#81), plus checked
  version-tag/digest-preserving release tooling (#75). A prepared workflow is not
  evidence that an actual immutable version tag has been published.
- The `fix/plex-tv-identity` follow-up builds on that candidate: unambiguous Plex TV
  matching and visible review warnings (#67), UTC display/rapid-search regressions,
  and refreshed implementation/trust/operations documentation (#73). It does not
  merge, publish, deploy, or start production work on its own.

## Runtime architecture

FastAPI serves the API and production React UI. SQLAlchemy/async sessions store
per-account locations, titles, seasons, files, measured audio tracks, structured
issues, notes, preferences, and jobs in SQLite or PostgreSQL. Versioned migrations
upgrade historical schemas; rollback requires the matching pre-upgrade backup.

MediaInfo extracts measured track metadata in an isolated child process. A shared
evaluator applies the effective audio preferences to saved measurements. Plex is
optional enrichment/sign-in, not a requirement for local scanning. Safe poster
requests go through the account-owned artwork endpoint. The frontend uses React,
React Router, TanStack Query, Tailwind CSS, and Lucide icons; components are owned
by this repository, not shadcn/ui.

One database-backed FIFO worker executes scans, rescans, cached reevaluations, and
individual edits. Queued work resumes; running work is interrupted after restart
and never automatically replayed. A catalog-wide lifetime lock rejects a second
worker. Browser cache invalidation refreshes affected library views after jobs
finish. See [scan behavior](SCANNING.md) for exact matching, reconciliation,
retention, cancellation, and deadline limits.

## Trust and media safety

Authentication defaults to None, which grants shared-account catalog/settings
access to anyone able to reach the instance. Restrict network exposure or enable
Require login before exposing it to untrusted clients. Required-login APIs enforce
account ownership, credential-version changes, and configured Plex admission
rules. Browser logout is not yet scoped server-side revocation (#72).

Production requires strong signing/encryption keys. Retain the encryption key
with catalog backups; do not rotate it as an upgrade workaround. Native edits also
require the explicit server write gate, tools, and writable in-scope MKV paths.
Removal plans protect required/unknown languages; reviewed overrides and stale
selection/policy checks must not be bypassed.

MediaInfo does not identify spoken language. Unknown tags and title-based roles
are review hints. Remux backups are never overwritten, but full edit journaling,
capacity preflight, and verification of every non-audio stream remain #66. Test
physical edits and restart recovery only on disposable copies, not production
originals. [Operations](OPERATIONS.md) covers backup/upgrade/rollback and release
approval; [regression checks](REVIEW_REGRESSIONS.md) distinguish automated tests
from approval-gated live writes.

## Next dependencies

- [#66](https://github.com/TheSoloGreen/TrackHound/issues/66): edit journal/recovery
  before batch writes (#79) or embedded tag correction (#83).
- [#68](https://github.com/TheSoloGreen/TrackHound/issues/68) and
  [#82](https://github.com/TheSoloGreen/TrackHound/issues/82): episode ranges and
  explicit Plex server/library/path mappings; not delivered by #67's ambiguity fix.
- [#76](https://github.com/TheSoloGreen/TrackHound/issues/76) and
  [#77](https://github.com/TheSoloGreen/TrackHound/issues/77): per-title/location
  profiles and subtitle inventory/evaluation, not part of cached audio refresh.
- [#78](https://github.com/TheSoloGreen/TrackHound/issues/78),
  [#80](https://github.com/TheSoloGreen/TrackHound/issues/80), and
  [#85](https://github.com/TheSoloGreen/TrackHound/issues/85): per-file history,
  scheduling/notifications, and managed diagnostics/backups beyond durable jobs.

## Validation workflow

Run `python -m pytest -q` from `backend`, then `npm test` and `npm run build` from
`frontend`. Linux CI additionally supplies PostgreSQL, ffmpeg, MediaInfo, and
MKVToolNix, exercises historical migrations and real disposable MKV edits, checks
version/changelog alignment, and smoke-tests production container/Compose startup.
Use the latest PR checks rather than historical test counts as release evidence.

Keep dependent changes separately reviewable. Merge/publish/deploy only after
review and successful checks; a source change or completed test does not itself
authorize changing a live library, enabling media writes, or promoting a release.
