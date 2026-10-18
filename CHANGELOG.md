# Changelog

## 0.5.0

Cached policy reevaluation and versioned release markers (issues #81, #75):

- Saving changed audio-evaluation rules atomically queues a read-only cached reevaluation. Rapid saves coalesce; older running policy jobs stop as superseded.
- Settings shows current/pending/missing-analysis counts and a manual retry action. Jobs retains revision, progress, outcomes, and files requiring a physical scan.
- Reevaluation preserves tracks, review notes, title classifications, and scan timestamps. It never probes media, contacts Plex, or invokes edits—even with automatic default fixing enabled.
- Migration `0010_cached_evaluation` separates successful analysis from policy freshness. Existing cached tracks remain reusable; ambiguous historical empty analyses require a physical scan. Incremental scanning now re-probes records without current analysis.
- Release checks validate aligned backend/frontend/lockfile versions and changelog notes. A matching `vX.Y.Z` tag on a master-reachable commit gates a stable `X.Y.Z` container tag and GitHub release behind the full checks.
- Stable tags promote the already-published SHA image by digest, refuse to overwrite a different existing version, and leave `latest` unchanged. Normal master builds still publish `latest` and SHA tags.

Back up the catalog and retain both keys before upgrading. Initially keep media writes disabled. Cached audio reevaluation uses saved title classification; anime detection/extension changes still apply on subsequent scans. Roll back the image and matching pre-upgrade catalog together. See [release and upgrade operations](docs/OPERATIONS.md) and the [live test checklist](docs/REVIEW_REGRESSIONS.md).

## 0.4.0

Durable bounded execution (issue #64):

- Scans, single-file/title rescans, default-audio edits, and track removals run through one database-backed FIFO worker, outside HTTP requests.
- The Jobs page retains progress, results, errors, and reported backup paths across browser and application restarts (200 finished jobs per account; 100 active-job queue limit).
- Queued work survives restart. Running work becomes interrupted and is never automatically replayed, including media writes.
- MediaInfo runs in a disposable process with a 60-second deadline and cooperative cancellation. Native edits retain their existing deadlines and cannot be cancelled mid-write.
- Duplicate target jobs are rejected; catalog resets and location changes are blocked while that account has queued/running jobs. A lifetime database/file lock rejects a second app worker.
- Migration `0009_durable_jobs` adds the queue without changing catalog/media data. Mutating scan/media endpoints now acknowledge queued jobs with HTTP 202; clients must poll for outcomes.

Use one app process/container per catalog. Back up the catalog and keys before upgrading; roll back the image and matching pre-upgrade database together. Start with media writes disabled and follow the [0.4.0 live test](docs/REVIEW_REGRESSIONS.md#040-durable-jobs-live-test). Full per-file catalog-change history (#78), edit journaling/recovery (#66), scheduling, and batch actions remain separate work.

## 0.3.0

Audio review and individual editing correctness (issues #61, #62, #63, #65):

- Explicit anime detection defaults, configurable Plex genre mapping, and visible classification reasons.
- Missing/multiple default-track detection and title-based commentary/audio-description roles. Auxiliary tracks do not satisfy main-audio requirements or automatic default selection.
- Exact-track default selection with stale-selection checks and native flag verification.
- Removal suggestions preserve required languages and unknown-language tracks. Explicit overrides preview introduced policy issues and require acknowledgment of the reviewed policy.
- One structured evaluator stores stable issue codes, severity, and evidence for scans, rescans, classification changes, summaries, filters, and exports.
- Migration `0008_structured_issues` preserves historical descriptions and marks legacy findings. A full scan applies the new rules to unchanged files.

Before a live upgrade, back up the catalog and retain the existing keys. Initially keep media writes disabled and follow the [release verification checklist](docs/REVIEW_REGRESSIONS.md). For a rollback to 0.2.0, restore the matching pre-upgrade catalog backup and image together.

Durable jobs, edit journaling/recovery, queued batch actions, and automatic preference reevaluation remain separate roadmap work. This release does not introduce those workflows.
