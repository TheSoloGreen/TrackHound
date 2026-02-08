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

## Tech Stack

### Backend
- FastAPI (Python async web framework)
- SQLAlchemy with async support (SQLite or PostgreSQL)
- pymediainfo for audio analysis
- plexapi for Plex integration

### Frontend
- React 18 with TypeScript
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
# Edit .env with your settings (especially SECRET_KEY)

# Build and run with Docker Compose
docker-compose up -d

# Access at http://localhost:8080
```

### Development Setup

#### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp ../.env.example .env

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

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `false` |
| `DATABASE_URL` | Database connection string | SQLite |
| `SECRET_KEY` | JWT signing key (change in production!) | - |
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
3. Set a secure `SECRET_KEY`
4. Access via `http://your-server:8080`

## API Documentation

When running, visit `/docs` for interactive API documentation (Swagger UI).

## Contributing Without Merge Conflicts

If your pull request frequently shows conflicts, keep your branch synced before you push:

```bash
# From your feature branch
git fetch origin
git rebase origin/main

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
