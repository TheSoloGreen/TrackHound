# Library review regression checks

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
