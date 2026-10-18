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
4. Prefer configuring `ALLOWED_PLEX_USER_IDS` with the numeric IDs of every account
   permitted to use the instance. A non-empty list is authoritative for new logins
   and existing sessions; removing an ID and recreating the container revokes it.
   On a truly new database only, an empty list lets the first Plex-verified account
   become the sole owner. After that, an empty list accepts only that same stored
   Plex account and rejects every other account. A denial includes the verified
   Plex account ID so an administrator can add it to the configured list.
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

## Durable jobs (0.4.0)

Run exactly one application process/container per catalog. The supplied Docker
command starts one Uvicorn worker. Do not add `--workers`, set `WEB_CONCURRENCY`
above one, or scale replicas against the same database. A lifetime SQLite file
lock or PostgreSQL session advisory lock rejects a second worker before job
recovery runs. The SQLite `.worker.lock` sidecar is intentionally retained;
closing/stopping the worker releases its OS lock. Do not delete it while running.

Scan/start and file/title rescan/edit requests return HTTP **202**, not a finished
media response. Scan/start retains its scan-status response plus `job_id`;
the media actions return a job. Poll `/api/jobs/{id}` or open **Jobs** for the
outcome. `/api/scan/status` reads the latest persisted library-scan status.
`POST /api/jobs/{id}/cancel` cancels queued work immediately, or requests a safe
stop for a running scan/rescan. A running media edit cannot be cancelled; its
native command and verification finish before another job starts. Closing the
browser does not cancel anything. A title rescan commits each successful file
independently and reports failures without discarding the other files.

The worker runs FIFO across accounts. Each account may have 100 queued/running
jobs; a repeated job for the same file/title or a second library scan is rejected.
The latest 200 terminal outcomes per account are retained. This is operational
job history, not the per-file/new/resolved issue history planned in #78.
Payloads contain catalog IDs and reviewed options, never saved Plex credentials.
Plex credentials and current preferences are loaded when work executes; write
gates, file snapshots, ownership, and reviewed removal policies are checked again.
Queued selections that have become stale fail for fresh review.

Graceful shutdown stops read-only work cooperatively and waits for a running
native write. MediaInfo has a 60-second execution deadline and is killed/reaped
on cancellation. MKV probes/default edits/remuxes retain 30/60/3600-second native
command deadlines. Filesystem discovery checks cancellation between directories;
an OS-level blocked network filesystem call cannot be forcibly interrupted.
Allow adequate container stop time for intentional large remuxes, or wait for the
Jobs page to become idle before upgrading. A forced stop may interrupt a write.

After restart, queued jobs resume; formerly running jobs are marked
**interrupted** and are **not** retried automatically. An interrupted scan keeps
already committed files but does not finish missing-file reconciliation. Rescan
affected files after an interrupted edit and inspect any `.bak` or temporary
files before reviewing another edit. Job status does not replace a full edit
journal or automatic recovery control (#66). Never delete recovery copies to
clear an error without verifying the original first.

Resetting the catalog or adding/updating/deleting locations returns 409 while
that account has queued/running jobs. Finish/cancel those jobs first. A reset
does not erase retained job outcomes or media backups. Back up the catalog and
keys before upgrading from 0.3.0; migration `0009_durable_jobs` only adds a queue
table. For rollback, restore the old image and its matching pre-upgrade catalog
backup rather than starting 0.3.0 against a newer schema.

## Cached policy reevaluation (0.5.0)

Saving changed audio-evaluation rules creates a durable `reevaluate` job in the
same transaction as the preference save. Queue-full errors roll back the save,
so a successful response cannot lose the requested work. Rapid saves replace the
pending job's policy; a running older revision stops as **superseded** at a batch
boundary. Cancellation/interruption preserves earlier committed batches and can
be retried from Settings. Changing only automatic-edit/keep-language options or
file extensions does not unnecessarily reevaluate issue flags.

Settings → Cached audio policy reports current, pending, and missing-analysis
counts for the active account. **Reevaluate cached audio** queues a manual retry
or applies the evaluator to upgraded legacy cached tracks. Jobs records policy
revision, counts, and outcomes. The HTTP endpoints are
`GET /api/settings/evaluation` and `POST /api/settings/reevaluate` (202).

The worker uses bounded batches of saved tracks and the existing title's anime
classification. It does not stat/open/probe media, contact Plex, reclassify titles,
or call editing tools—even when automatic fixing is enabled. Scan timestamps,
raw/normalized tags, track IDs, review notes, and media files remain unchanged.
Cached results describe the last successful analysis: a later external file
replacement still requires a scan to discover new evidence. Anime detection and
extension changes take effect on subsequent scans, not on cached evaluation.

Migration `0010_cached_evaluation` marks existing saved tracks as usable analysis
and leaves policy freshness pending until reevaluation. Historical empty results
cannot safely prove that a file had no audio, so they require a new physical
analysis; incremental scans now re-probe those records instead of skipping them.
New successful no-audio analyses are tracked explicitly and can be reevaluated
without another probe. A failed physical probe preserves previous analysis.

For future implementation changes, increment `EVALUATION_VERSION` when evaluator
semantics change, and `ANALYSIS_VERSION` when saved probe evidence needs refreshing.
Evaluation revisions include the evaluator version, so existing cached results
become visibly pending rather than silently appearing current under changed code.

Back up the catalog and both keys before upgrading. Migration only changes the
catalog, not media. Roll back with the matching pre-upgrade catalog and image;
do not start an older app against the newer schema.

## Versioned releases

Normal master builds continue to publish `latest` and `sha-<commit>` only after
all checks succeed. A reviewed release is a separate, explicit maintainer action:

1. Merge the candidate and wait for the master image-publishing workflow to pass.
2. Confirm backend `VERSION`, frontend package/lockfile, and the changelog agree.
3. Create and push an annotated `vX.Y.Z` tag at that exact merged commit. Do not
   tag an unmerged feature commit or move an already-published release tag.
4. The tag workflow rechecks versions, notes, master ancestry, tests and the exact
   already-published SHA container. It verifies the full embedded Git revision.
5. After all gates pass, it promotes that image by digest to `X.Y.Z`, then creates
   GitHub release notes with the image digest and revision. It does not rebuild
   the release image or move `latest`. If a version already points to another
   digest, publication fails; use a new patch version instead of overwriting it.

Docker documents that copying a single image index with `imagetools create`
preserves the index; the workflow checks the resulting digest as well.
See [Docker's promotion behavior](https://docs.docker.com/reference/cli/docker/buildx/imagetools/create/)
and [GitHub CLI release/tag checks](https://cli.github.com/manual/gh_release_create).
Immutability is enforced by this workflow, not a claim that registry administrators
cannot manually change tags. Restrict tag/package-write access appropriately.

If a release tag is pushed before its SHA image is published, the workflow fails
without creating a version image/release. After master publication succeeds, rerun
the failed tag workflow. A successful rerun is idempotent when the digest matches.
Older commits whose workflow predates this mechanism do not acquire version tags
retroactively. Verify the release workflow before changing an installation's tag.

For installation, select the published `X.Y.Z` image (or its full digest), preserve
the existing appdata/mounts/keys, and recreate the container. Keep media writes
disabled for initial verification. The footer and `/api/info` must show the expected
version **and** revision. A Docker restart alone keeps the old image; an `image:`
deployment and the repository's local `build:` Compose flow are different update
paths. Do not delete appdata or rotate keys to resolve an image-version mismatch.

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
system. Do not rely on empty-list bootstrap to add another account: configure a
non-empty list before inviting additional users. Restoring a database also restores
its bootstrap owner; an empty list does not transfer ownership to the next login.

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
