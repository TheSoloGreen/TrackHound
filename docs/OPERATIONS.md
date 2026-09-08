# Deployment, upgrades, and recovery

## Before upgrading an existing installation

1. Stop TrackHound so scans and media edits have finished, then record the current
   image tag or digest for a possible rollback.
2. Back up the database and deployment configuration, including both keys. For
   SQLite, copy the entire stopped container's persisted `/app/data` directory,
   including any SQLite journal files. For PostgreSQL, take a database backup
   with `pg_dump` and retain the database credentials. Store keys securely, with
   access limited to the administrator; do not commit `.env` or backups to Git.
3. Keep existing non-default `SECRET_KEY` and `ENCRYPTION_KEY` values if each is
   at least 32 characters. The production image now rejects weaker values.
4. Configure `ALLOWED_PLEX_USER_IDS`. If the ID is unknown, the Plex login denial
   shows the account ID after Plex verifies that account. Add the ID and recreate
   the container. An empty list deliberately grants no access, and removing an
   account also blocks its existing sessions after restart.
5. Keep `MEDIA_WRITES_ENABLED=false` while verifying startup, sign-in, and scans.
   Explicitly enable writes and writable media mounts only for libraries you
   intend TrackHound to edit.

This change adds no database columns. Existing migration behavior is unchanged;
versioned database migrations remain a separate follow-up.

## Keys and Plex reconnection

`SECRET_KEY` signs browser sessions. Changing it requires users to sign in again.
`ENCRYPTION_KEY` decrypts stored Plex tokens. Changing or losing it makes previously
encrypted tokens unreadable; this update does not rotate or re-encrypt those tokens.
Restore the matching key with a database backup. If an insecure key must be
replaced, preserve the old database and key securely first, generate a new key,
and have each approved user sign in again to replace their stored Plex token.
Verify their Plex connection before starting another scan.

The allowlist applies equally to development and production. All approved users
can use the instance's mounted media, subject to its filesystem permissions and
write policy. It is an instance access restriction, not a per-library permissions
system.

## Media edits and recovery

Track removal writes a unique temporary MKV next to the source. TrackHound checks
that the output is nonempty and has the expected audio-track count, checks whether
the source changed during remuxing, then replaces the source. The UI always asks
for a backup; the API's `keep_backup` also defaults to `true`. API callers that
explicitly disable it forgo that recovery copy.

The original is kept as `<filename>.mkv.bak`. An existing backup is never
intentionally overwritten. Move a prior backup to secure storage before a later
edit. Normal replacement errors trigger automatic restoration; if restoration
also fails, the error reports the backup's recovery path. A failed analysis after
an edit reports that the media changed while retaining the previous database
analysis. Rescan the file before another edit.

To restore a media backup:

1. Stop TrackHound and any other process writing the media file.
2. Verify the reported `.bak` file exists and contains the expected media. Preserve
   the current edited file under a different name before replacing anything.
3. Restore the backup to the original filename with the original permissions.
4. Restart TrackHound and rescan the file. Check playback, audio selection, and
   subtitles before discarding either copy.

Default-audio edits use `mkvpropedit` in place and do not create a `.bak` file.
Keep a separate library backup if those changes need to be reversible. A timeout
or process termination during an in-place edit can require inspection and rescan.

Use the default **one application worker and one container per media library**.
The edit lock serializes operations within one process; it does not coordinate
multiple containers, workers, or outside media tools. Do not modify a file with
other software during an edit. Remuxing has a one-hour timeout; file inspection
and default-audio editing have 30-second and 60-second subprocess timeouts.

The database and filesystem do not share an atomic transaction. A machine crash
between replacement steps may leave the original at its `.bak` path. Filesystem
errors, insufficient disk space, and interrupted in-place edits still require
operator recovery. Do not treat a `.bak` file as a substitute for a separate backup.

## Restoring the application

Stop TrackHound before restoring its data. Restore the SQLite data directory or
the PostgreSQL dump together with the matching deployment configuration and
encryption key. Restore ownership so the container's UID/GID `1000:1000` can read
and write its data. Start with media writes disabled, check `/api/health`, sign in
with an approved Plex account, and verify saved locations and a sample file scan.
Application database backups do not contain your media files; restore those
separately when needed.

If rolling back an image after future schema changes, use the backup associated
with that image rather than assuming an older version understands a newer schema.
