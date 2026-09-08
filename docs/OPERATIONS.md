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

Startup now upgrades through a versioned Alembic chain before serving requests.
All pending schema changes commit together; an error rolls the entire upgrade back
and prevents startup. SQLite table rebuilds run under one write transaction, with
foreign keys checked before commit and re-enabled afterward. PostgreSQL upgrades
use a transaction and an advisory lock.

The baseline covers the initial, pre-ownership, and previously unversioned schemas.
As in the earlier ownership migration, unowned legacy rows go to the oldest stored
user, or an inactive bootstrap owner if no user exists. Rows whose parents were
already deleted are cleaned up before foreign keys are enforced. Back up first;
inspect legacy ownership before exposing a restored instance to additional users.
Future schema changes require new revisions; do not edit applied revisions.

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

## SQLite backup and restore commands

The backup command uses SQLite's online backup API, so committed WAL changes are
included without copying a live database file. It verifies integrity and refuses
to overwrite a previous backup. Run these from the Docker host; adjust the
container name if yours differs:

```bash
TRACKHOUND_BACKUP="trackhound-$(date -u +%Y%m%dT%H%M%SZ).db"
docker exec trackhound python -m app.backup /app/data/trackhound.db "/tmp/$TRACKHOUND_BACKUP"
docker cp "trackhound:/tmp/$TRACKHOUND_BACKUP" "./$TRACKHOUND_BACKUP"
```

Back up `.env` and the exact deployed image digest separately. A pre-upgrade
backup should be taken after stopping scans and edits. Verify the copied snapshot:

```bash
python - "$TRACKHOUND_BACKUP" <<'PY'
import sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + '?mode=ro', uri=True) as db:
    print(db.execute('PRAGMA integrity_check').fetchone()[0])
    print('Media rows:', db.execute('SELECT COUNT(*) FROM media_files').fetchone()[0])
PY
```

To restore, stop the container and preserve the complete current data directory.
Restore into a new directory so old `-wal`/`-shm` files cannot be replayed onto the
snapshot. For the example Unraid mapping:

```bash
docker stop trackhound
TRACKHOUND_RESTORE_DIR="/mnt/user/appdata/trackhound-restore-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$TRACKHOUND_RESTORE_DIR"
cp -- "$TRACKHOUND_BACKUP" "$TRACKHOUND_RESTORE_DIR/trackhound.db"
chown -R 1000:1000 "$TRACKHOUND_RESTORE_DIR"
```

Change the container's `/app/data` mapping to that new directory, restore the
matching encryption key/configuration, and start the intended image version with
media writes disabled. The previous directory remains available for recovery.
Check health, sign-in, saved locations, row counts, and a sample rescan. Reverting
the volume mapping alone is insufficient if you also changed the encryption key.

## PostgreSQL dump, restore, and volume replacement

Use the database container's own client binaries so dump/restore versions match.
The examples use the committed PostgreSQL Compose file and its default database
name and user. Run while no scan or edit is active:

```bash
TRACKHOUND_PG_BACKUP="trackhound-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose -f docker-compose.postgres.yml exec -T db pg_dump -U trackhound -d trackhound --format=custom > "$TRACKHOUND_PG_BACKUP"
docker compose -f docker-compose.postgres.yml exec -T db pg_restore --list < "$TRACKHOUND_PG_BACKUP"
```

Check both commands' exit status before relying on the dump. Store the matching
`.env`, image digest, and migration version with it. A full dump includes the
migration-version table. To restore without deleting the existing volume, stop the
application and create a new named volume:

```bash
docker compose -f docker-compose.postgres.yml stop trackhound
TRACKHOUND_RESTORE_VOLUME="trackhound-postgres-restore-$(date -u +%Y%m%dT%H%M%SZ)"
docker volume create "$TRACKHOUND_RESTORE_VOLUME"
cat > restore.override.yml <<YAML
volumes:
  postgres_data:
    name: $TRACKHOUND_RESTORE_VOLUME
    external: true
YAML
docker compose -f docker-compose.postgres.yml -f restore.override.yml up -d db
```

Wait until `docker compose -f docker-compose.postgres.yml -f restore.override.yml
ps` reports the database healthy, then restore into its empty database:

```bash
docker compose -f docker-compose.postgres.yml -f restore.override.yml exec -T db pg_restore -U trackhound --dbname=trackhound --exit-on-error --single-transaction --no-owner < "$TRACKHOUND_PG_BACKUP"
docker compose -f docker-compose.postgres.yml -f restore.override.yml exec -T db psql -U trackhound -d trackhound -c 'SELECT COUNT(*) FROM media_files;'
docker compose -f docker-compose.postgres.yml -f restore.override.yml up -d trackhound
```

Keep the override file in use while this restored volume is active. Omitting it
selects the original volume again. Never run `down -v` as part of this procedure.
To roll back the application and schema, select the pre-upgrade image digest and
restore its matching pre-upgrade database backup and keys. Alembic downgrades are
intentionally blocked for the legacy adoption and per-user uniqueness changes;
collapsing shared paths back into a global constraint could discard data.

CI rehearses backup → upgrade → restore → upgrade on both SQLite and PostgreSQL
with users, settings, locations, shows, seasons, files, and audio tracks. It also
injects a late migration failure and checks that schema, data, token encryption,
and migration version all roll back.

## Reverse proxy and instance trust

Use HTTPS at the reverse proxy, restrict direct access to the backend port, and
set `CORS_ORIGINS` to the exact browser origin. Avoid exposing the Unraid management
interface alongside the application. Keep the account allowlist small: approved
users are trusted instance operators and share the configured mounted filesystem.
The allowlist is enforced on every authenticated API request; proxy identity
headers do not grant access. Keep writable media mounts limited to intended paths.
