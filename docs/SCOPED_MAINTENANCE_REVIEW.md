# Scoped maintenance review

Base: `8d59b3d` (`master`, 0.4.0). This maintenance pass deliberately excludes new features and the separate work in PRs #92 and #93.

## Plan and implemented changes

1. **Job lifecycle correctness**
   - Serialize cancellation acceptance with the final scan reconciliation commit. Before cutover, cancellation prevents catalog deletion reconciliation; after cutover, cancellation is rejected while the already-started commit finishes.
   - Keep execution visible and non-cancellable until its terminal outcome is persisted. Serialize cancellation and terminal persistence so a completed operation cannot acknowledge a stale cancellation.
   - Return a claimed but unstarted job to the queue if shutdown begins before execution, including media edit jobs. Never abandon a native write already in progress.
   - Apply the existing 200-terminal-job retention bound to users affected by startup recovery; preserve queued work and newest outcomes.
2. **Frontend correctness and failure handling**
   - Preserve actionable server conflict details for catalog reset and title/file rescans.
   - Distinguish title/season request failures from missing or unselected content, with retry for transient failures.
   - Disable scan actions when scan status is unknown or refreshing, expose load failures, and allow status retry.
   - Validate library pagination and boolean/media-type URL filters before API submission.
3. **Dependency security maintenance**
   - Refresh the frontend lockfile within existing dependency ranges, without major upgrades, new dependencies, overrides, package-version changes or script changes.
   - Audit findings include development tooling and runtime dependency graphs; they do not establish that every listed advisory was exploitable in the deployed browser application.

## Regression coverage and independently exercised checks

- Six new backend lifecycle regression cases, parameterized across SQLite/PostgreSQL where applicable.
- Eight new frontend regression tests for conflict details, retained cache, query failure/retry, status safety and malformed URL filters. The quality review identified a cached-success-to-404 transition; a failing regression was added before correcting stale title/action rendering.
- Host Python 3.11 suite with disposable PostgreSQL and server-matched backup tools: **299 passed, 4 skipped**. Skips cover native-tool cases unavailable on the host and an engine-specific test.
- Non-root Linux test container with read-only source and real FFmpeg, MediaInfo and MKVToolNix: **270 passed, 33 skipped**. PostgreSQL was not enabled for this second run; native editing/backup-preservation cases passed.
- Node 20 frontend: **50 passed**, TypeScript check and production build passed.
- `npm audit`: **0 findings**, down from 14 package records (10 high, 3 moderate, 1 low) at baseline.

The test runs use disposable synthetic media and isolated databases, not a live library. The initial Linux harness needed `PYTHONPATH` propagated to native probe subprocesses; the corrected harness passed without changing application code. Node 26's localStorage test-environment behavior was not treated as an application bug; validation used the project's Node 20 baseline.

## Review and rollout boundaries

Separate agents reviewed backend and frontend code, implemented bounded work packages, and reviewed the lockfile independently. The staged publication payload passed spec compliance, and the independent quality/integration gate approved the final implementation after the cached-404 correction. The worker execution metadata reported `gpt-5.6-sol`; the parent independently verified test and audit results. No merge, release, deployment, existing service restart, live database migration or real-media edit is part of this maintenance run.

PR #92 overlaps job/scanner and version/lockfile areas; PR #93 overlaps page files. Rebase/resolve against whichever is merged first, preserving their unrelated features and rerunning CI. Do not infer compatibility with their combined unmerged branches solely from tests on this maintenance branch.

Deferred: roadmap features, architecture rewrites, broad dependency major upgrades, licensing choices, API expansion, new integrations and speculative performance work. Those need separately justified scope.
