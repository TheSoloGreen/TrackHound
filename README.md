# TrackHound

Media audio track scanner with Plex integration. Scans your media library to identify files missing preferred audio languages and flags issues based on customizable rules.

## Features

- **Multi-Location Scanning**: Scan media files across multiple NAS drives/mount points
- **Audio Track Analysis**: Extract detailed audio track information (language, codec, channels, bitrate)
- **Plex Integration**: Sign in with Plex and sync metadata for shows
- **Anime Detection**: Automatically identify anime from Plex genres, folder names, or manual tagging
- **Preference Rules**:
  - Require English audio for non-anime content
  - Require Japanese audio for anime
  - Require dual audio (English + Japanese) for anime
  - Check default audio track settings
- **Issue Flagging**: Identify and flag files that don't meet your preferences
- **Export**: Export results to CSV or JSON
- **Optional MKV Editing**: Change default audio and remove selected tracks, with write access disabled until an administrator enables it

## Tech Stack

### Backend
- FastAPI (Python async web framework)
- SQLAlchemy with async support (SQLite or PostgreSQL)
- pymediainfo for audio analysis
- plexapi for Plex integration

### Frontend
- React 19 with TypeScript
- Tailwind CSS + shadcn/ui
- TanStack Query for state management

## Quick Start

### Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/TheSoloGreen/TrackHound.git
cd TrackHound

# Copy and configure environment
cp .env.example .env
# Edit .env with unique SECRET_KEY and ENCRYPTION_KEY values.
# Generate them separately: openssl rand -hex 32
# Configure CORS_ORIGINS and the media paths in docker-compose.yml.

# Build and run with Docker Compose
docker compose up -d --build

# Access at http://localhost:8383
```

Plex sign-in is restricted to the numeric account IDs in `ALLOWED_PLEX_USER_IDS`.
An empty list denies all accounts. For initial setup, sign in once: the access-denied
message shows your verified Plex account ID. Add that ID to `.env` (for example,
`ALLOWED_PLEX_USER_IDS=123456`), then run `docker compose up -d` to recreate the
container and sign in again. Separate multiple approved IDs with commas. Removing
an ID and restarting also blocks that account's existing sessions.

The production image refuses to start with default keys or keys shorter than 32
characters. Existing installations should read the [upgrade and recovery notes](docs/OPERATIONS.md)
before updating; preserve existing valid encryption keys.

### Development Setup

#### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Install MediaInfo and MKVToolNix with your operating system's package manager.
# The test suite also uses ffmpeg for its real MKV integration test.

# Copy environment file
cp ../.env.example .env
# Configure keys and ALLOWED_PLEX_USER_IDS as above.

# Run development server
uvicorn app.main:app --reload
```

#### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

### Tests and Build Checks

```bash
# Backend tests
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q

# Frontend production build
cd ../frontend
npm ci
npm run build
```

The GitHub Actions workflow runs both checks on pushes and pull requests to `master`.
It also exercises real MKV editing, validates both Compose configurations, and
checks production container startup and health before publishing an image. Local
test runs skip the real MKV test if ffmpeg or MKVToolNix is unavailable.

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `false` |
| `DATABASE_URL` | Database connection string | SQLite |
| `ENVIRONMENT` | `production`, `development`, or `test`; Docker uses `production` | `development` outside Docker |
| `SECRET_KEY` | Unique JWT signing key, at least 32 characters in production | Required in production |
| `ENCRYPTION_KEY` | Key for stored Plex tokens; retain it across upgrades and restores | Required in production |
| `ALLOWED_PLEX_USER_IDS` | Comma-separated numeric Plex account IDs allowed to use this instance | Empty: all accounts denied |
| `MEDIA_WRITES_ENABLED` | Permit MKV edits when the tools and filesystem also allow them | `false` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:3000,http://localhost:5173` |

### Database Options

**SQLite (Default)**
```
DATABASE_URL=sqlite+aiosqlite:///./data/trackhound.db
```

**PostgreSQL**
```
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

## Docker Deployment (Unraid)

1. Create a new container using the docker-compose file
2. Map your media volumes (read-only recommended):
   ```yaml
   volumes:
     - /mnt/user/Media/TV:/media/tv:ro
     - /mnt/user/Media/Anime:/media/anime:ro
   ```
3. Set secure `SECRET_KEY` and `ENCRYPTION_KEY` values and configure `ALLOWED_PLEX_USER_IDS` using the setup steps above. These are required when running the published image directly, too.
4. Access via `http://your-server:8383` for the default Compose file, or port `8080` for `docker-compose.postgres.yml`. Set `CORS_ORIGINS` to the address you use.

### Enable media editing

Keep the default read-only mounts for scanning. To enable edits, set
`MEDIA_WRITES_ENABLED=true` and change only the intended media mount from `:ro`
to `:rw`. Recreate the container. Its user (UID/GID `1000:1000`) needs file write
permission; removing tracks also needs directory write permission and enough free
space for another copy of the media file.

The UI reports why an edit is unavailable, and the API checks access again before
writing. Track removal starts with your saved keep-language preferences and asks
you to review the exact tracks. It preserves the original as `<filename>.mkv.bak`
and refuses to overwrite an existing backup. Default-audio changes edit the MKV
in place and do not create that backup. See [recovery and editing limits](docs/OPERATIONS.md).

## API Documentation

When running, visit `/docs` for interactive API documentation (Swagger UI).

API clients that remove tracks by index must send `expected_last_scanned` from
the file response or `GET /api/media/files/{id}/audio-tracks/plan`. A stale or
missing revision is rejected so indices from an older scan cannot be reused.

## Contributing Without Merge Conflicts

If your pull request frequently shows conflicts, keep your branch synced before you push:

```bash
# From your feature branch
git fetch origin
git rebase origin/master

# Resolve any conflicts, then continue
git add <resolved-files>
git rebase --continue

# Update your remote branch after rebase
git push --force-with-lease
```

Tips:
- Make smaller PRs to reduce overlap with other changes.
- Rebase right before opening a PR (and again before merge if the branch gets stale).
- Avoid committing generated files unless they are required by the project.

## License

MIT
