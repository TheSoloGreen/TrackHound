# Changelog

## 0.3.0 — release candidate

Audio review and individual editing correctness (issues #61, #62, #63, #65):

- Explicit anime detection defaults, configurable Plex genre mapping, and visible classification reasons.
- Missing/multiple default-track detection and title-based commentary/audio-description roles. Auxiliary tracks do not satisfy main-audio requirements or automatic default selection.
- Exact-track default selection with stale-selection checks and native flag verification.
- Removal suggestions preserve required languages and unknown-language tracks. Explicit overrides preview introduced policy issues and require acknowledgment of the reviewed policy.
- One structured evaluator stores stable issue codes, severity, and evidence for scans, rescans, classification changes, summaries, filters, and exports.
- Migration `0008_structured_issues` preserves historical descriptions and marks legacy findings. A full scan applies the new rules to unchanged files.

Before a live upgrade, back up the catalog and retain the existing keys. Initially keep media writes disabled and follow the [release verification checklist](docs/REVIEW_REGRESSIONS.md). For a rollback to 0.2.0, restore the matching pre-upgrade catalog backup and image together.

Durable jobs, edit journaling/recovery, queued batch actions, and automatic preference reevaluation remain separate roadmap work. This release does not introduce those workflows.
