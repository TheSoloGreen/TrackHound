# Library review regression checks

## 0.3.0 release-candidate verification

Back up the catalog and retain both deployment keys. Migration
`0008_structured_issues` adds code-based issue records while preserving legacy
messages. Legacy findings keep their evidence and are marked as legacy until a
scan or classification update evaluates them using the new rules. A full scan is
required to apply the new default/main-audio checks to unchanged files.

The default-audio issue category now includes absent and multiple flags, auxiliary
defaults, and wrong-language defaults. Commentary/audio-description roles use
explicit track titles; they are hints, not a claim about the spoken content.
The exact-track selector retains access to every track for a deliberate manual
choice. Default changes require MKVToolNix inspection as well as editing and are
verified after the native edit.

Removal suggestions include the languages required by the title's current
rules, in addition to saved keep languages. Manual overrides use a server-side
preview, show any newly introduced issues, and bind acknowledgment to the policy
revision. Refresh a plan after a scan, classification change, or preference
change. Existing backups are never overwritten.

On a disposable catalog or a copy of the live catalog, first test with media
writes disabled:

1. Confirm version 0.3.0, startup migration, authentication mode, and artwork.
2. Scan Western animation and anime fixtures and verify classification reasons.
3. Review files with no defaults, multiple defaults, commentary-only English,
   unknown languages, and a nonpreferred codec. Follow the matching dashboard
   links and compare Files and exported issue codes/counts.
4. Preview a dual-audio anime removal: Japanese should be kept by default.
   Uncheck it and verify the warning, cancel once, then review again.
5. On expendable MKVs only, enable writes and set an exact main track default.
   Rescan and verify exactly one flagged track. Test stale selections and changed
   preferences before confirming a remux. Verify the original `.bak` remains.
6. Restart the container and verify issue records and review notes persist.

Focused safety coverage: `test_audio_policy.py`, `test_audio_fixer.py`, the real
native-tool tests in `test_mkv_integration.py`, migration upgrades on both engines,
and frontend `MediaActions.test.tsx`. Preference changes still require a full scan
for unchanged files; durable jobs and edit recovery are later milestones.

## Anime classification

Plex genre detection now requires an exact match against the configured anime
genre labels. The defaults are `Anime` and `アニメ`; `Animation` and
`Japanese Animation` do not classify a title as anime unless explicitly added in
Settings. An empty genre list disables genre hints. TV and movie enrichment use
the same mapping.

The default folder keyword is now `anime`. Folder detection matches whole terms,
including space, hyphen, and underscore separators, so `NotAnime` and a filename
containing `anime` do not trigger it. Saved custom keywords are preserved. If an
older installation still has `animation` in its saved keywords, remove it in
Settings to stop treating those folders as anime.

Run a **Full scan** after adjusting detection settings to refresh unchanged
titles and their audio issues. Explicit anime locations and manual positive or
negative overrides retain precedence. The title detail page explains whether
classification came from a manual choice, scan location, folder keyword, or
Plex genre. This classification change does not itself edit media.

Focused coverage: `test_anime_classification.py`, saved genre mapping scans and
manual override cases in `test_scanner_run_scan.py`, and frontend
`PreferencesForm.test.tsx` and `MediaActions.test.tsx`.

## Catalog correctness and artwork credentials

Migration `0007_artwork_security` replaces stored Plex poster URLs with thumbnail
paths and removes Plex-token query parameters from public avatar URLs. Invalid
poster references are cleared; another Plex-enriched scan can refresh them.
Browser-visible poster URLs point to TrackHound, whose artwork endpoint verifies
the active account's catalog ownership. The frontend fetches posters with its
current session and displays a fallback if Plex is unavailable. Artwork requests
are size-limited, accept raster images only, and do not follow upstream redirects.

Distinct Plex identities are no longer merged by title. Run a **Full scan** with
Plex connected to separate historically merged movies and refresh stored language
results. Incremental scans continue to skip unchanged files. Existing review
notes stay with their file records; this upgrade does not modify media files.

Regional language tags normalize to their primary language. Title-based hints
must contain explicit language names, bounded three-letter codes, or bracketed
two-letter labels. Conflicting hints remain unknown; original tags and titles
remain available for review.

Focused coverage: `test_artwork_security.py`, `test_movie_identity.py`,
`test_language_analysis.py`, the artwork upgrade test in
`test_database_migrations.py`, and frontend `ShowArtwork.test.tsx`.

## Upgrade and scan behavior

The normal database upgrade adds the nullable `language_review_note` column in
migration `0004_language_review`. Back up the catalog before upgrading; follow
the recovery procedure in [OPERATIONS.md](OPERATIONS.md).

Run a full scan after upgrading to refresh Plex movie metadata, normalized
language tags, and stored issue descriptions for unchanged files. Incremental
scans deliberately skip unchanged files. Unknown tags mean the language needs
review; they do not prove that an English or Japanese audio track is absent.

Review notes belong to the catalog file record and survive rescans. They do not
change embedded media tags or dismiss issue flags. Recheck a note if the media
is replaced. Removing/resetting that catalog record also removes its note.

## Automated coverage

- `backend/tests/test_scan_lock_recovery.py`: independent SQLite writer conflict,
  retry exhaustion/cancellation, and no repeated probes or physical edits.
- `backend/tests/test_movie_metadata.py`: movie sections, exact paths, remakes,
  year disambiguation, and unavailable matches.
- `backend/tests/test_issue_drilldowns.py`: dashboard/list/export agreement,
  ownership boundaries, unknown tags, and review-note persistence.
- `frontend/src/test/ReviewIssues.test.tsx`: URL navigation, accessible controls,
  axe checks, API error feedback/retry, and review notes.
- `backend/tests/test_database_migrations.py`: fresh/legacy upgrades and
  backup/restore on SQLite and PostgreSQL (set `TEST_POSTGRES_URL`).

## Browser regression checklist

Use a disposable catalog containing a long filename and at least four audio
tracks, including an unknown tag and descriptive track titles.

1. At 320px, 390px, and 768px widths, open Files and expand the filename using
   Enter, then Space. Verify filters wrap, the document does not scroll sideways,
   and the table itself scrolls horizontally when needed. Scroll to the final
   column and inspect all expanded track details and controls.
2. Save a language review note, reload, and confirm the note and expanded row
   remain. Clear the note and save to remove it.
3. Open a file from a title's selected season. Use the return link and browser
   Back/Forward; confirm the season and Files filters/page/expansion survive.
4. Follow dashboard issue counts for every media type. Confirm the matching
   Files count and exported rows; categories overlap and should not be summed.
5. In Settings, test an invalid/duplicate location and unavailable directory.
   Verify a useful error, preserved draft, and retry. Check failed toggle/delete
   requests retain their current state. Use test data, not a production location.

The 2026-09-20 local browser check used a synthetic catalog and the production
frontend build. At 320/390px the 600px table was contained in its own scroll area;
at 768px it fit its container. Keyboard expansion and note save/reload worked.
