"""Media file scanner for discovering and processing media files."""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session_maker
from app.models.entities import MediaFile, Show, Season, ScanLocation
from app.core.analyzer import AudioAnalyzer
from app.core.plex_connector import PlexConnector
from app.core.preference_engine import PreferenceEngine
from app.core.scan_state import scan_state_manager

logger = logging.getLogger(__name__)

# Default supported extensions
DEFAULT_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv"}

# Regex patterns for parsing show/season/episode from file paths
SHOW_PATTERNS = [
    # Show Name/Season 01/E01 - Title.mkv
    re.compile(r"^(?P<show>.+?)[/\\]Season\s*(?P<season>\d+)[/\\].*?[Ee](?P<episode>\d+)", re.IGNORECASE),
    # Show Name/S01E01 - Title.mkv
    re.compile(r"^(?P<show>.+?)[/\\][Ss](?P<season>\d+)[Ee](?P<episode>\d+)", re.IGNORECASE),
    # Show Name - S01E01 - Title.mkv
    re.compile(r"^(?P<show>.+?)\s*-\s*[Ss](?P<season>\d+)[Ee](?P<episode>\d+)", re.IGNORECASE),
]


def parse_show_info(file_path: str, base_path: str) -> dict:
    """
    Parse show, season, and episode information from a file path.
    
    Returns a dict with keys: show, season, episode (all optional)
    """
    # Get relative path from base
    relative_path = os.path.relpath(file_path, base_path)
    
    for pattern in SHOW_PATTERNS:
        match = pattern.search(relative_path)
        if match:
            groups = match.groupdict()
            try:
                season_num = int(groups.get("season", 0))
            except (ValueError, TypeError):
                season_num = 0
            try:
                episode_num = int(groups.get("episode", 0))
            except (ValueError, TypeError):
                episode_num = 0
            return {
                "show": groups.get("show", "").strip().replace(".", " "),
                "season": season_num,
                "episode": episode_num,
            }
    
    # Fallback: use parent directory as show name
    parts = Path(relative_path).parts
    if len(parts) >= 2:
        return {
            "show": parts[0].strip().replace(".", " "),
            "season": 1,
            "episode": None,
        }
    
    return {"show": None, "season": None, "episode": None}


def parse_movie_title(file_path: str, base_path: str) -> str:
    """
    Parse movie title from a file path.
    
    For movies, the parent folder name is typically the movie title,
    or the filename itself if it's directly in the base path.
    """
    relative_path = os.path.relpath(file_path, base_path)
    parts = Path(relative_path).parts

    if len(parts) >= 2:
        # Use the top-level folder as the movie title
        return parts[0].strip().replace(".", " ")

    # File is directly in the base path — use filename without extension
    return Path(file_path).stem.strip().replace(".", " ")


class MediaScanner:
    """Scanner for discovering media files in configured locations."""

    def __init__(
        self,
        extensions: set[str] = None,
        plex_token: Optional[str] = None,
    ):
        self.extensions = extensions or DEFAULT_EXTENSIONS
        self.analyzer = AudioAnalyzer()
        self.plex_connector = PlexConnector(plex_token) if plex_token else None
        self.preference_engine = PreferenceEngine()

    def discover_files(self, location: str) -> list[str]:
        """Discover all media files in a location."""
        files = []
        location_path = Path(location)
        
        if not location_path.exists():
            raise ValueError(f"Location does not exist: {location}")
        
        for root, _, filenames in os.walk(location_path):
            for filename in filenames:
                ext = Path(filename).suffix.lower()
                if ext in self.extensions:
                    files.append(os.path.join(root, filename))
        
        return sorted(files)

    async def process_file(
        self,
        file_path: str,
        base_path: str,
        media_type: str,
        user_id: int,
        db: AsyncSession,
    ) -> Optional[MediaFile]:
        """Process a single media file."""
        try:
            is_movie = media_type == "movie"
            is_anime = media_type == "anime"

            # Check if file already exists in database
            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.file_path == file_path,
                    MediaFile.user_id == user_id,
                )
            )
            existing = result.scalar_one_or_none()
            
            # Get file stats
            stat = os.stat(file_path)
            file_mtime = datetime.fromtimestamp(stat.st_mtime)
            
            # Skip if file hasn't changed (incremental scan)
            if existing and existing.last_modified >= file_mtime:
                return existing
            
            # Analyze audio tracks
            audio_info = self.analyzer.analyze(file_path)
            
            # Determine title and metadata based on media type
            if is_movie:
                show_title = parse_movie_title(file_path, base_path)
                show_info = {"show": show_title, "season": None, "episode": None}
            else:
                show_info = parse_show_info(file_path, base_path)
                show_title = show_info.get("show")
            
            # Try to get metadata from Plex first
            plex_metadata = None
            if self.plex_connector:
                plex_metadata = self.plex_connector.sync_show_metadata(
                    file_path=file_path,
                    title_from_path=show_title,
                )
            
            # Determine final title and anime status
            if plex_metadata:
                show_title = plex_metadata["title"]
                plex_is_anime = plex_metadata["is_anime"]
                anime_source = "plex_genre" if plex_is_anime else None
                plex_rating_key = plex_metadata.get("plex_rating_key")
                thumb_url = plex_metadata.get("thumb_url")
                # If Plex says it's anime and we're in a TV folder, upgrade to anime
                if plex_is_anime and media_type == "tv":
                    is_anime = True
            else:
                anime_source = "folder" if is_anime else None
                plex_rating_key = None
                thumb_url = None
            
            # Find or create show
            show = None
            season = None
            
            if show_title:
                # First try to find by Plex rating key
                if plex_rating_key:
                    result = await db.execute(
                        select(Show).where(
                            Show.plex_rating_key == plex_rating_key,
                            Show.user_id == user_id,
                        )
                    )
                    show = result.scalar_one_or_none()
                
                # Then try by title
                if not show:
                    result = await db.execute(
                        select(Show).where(Show.title == show_title, Show.user_id == user_id)
                    )
                    show = result.scalar_one_or_none()
                
                # Check path-based title (handles English folder names)
                if not show and show_info.get("show") and show_info["show"] != show_title:
                    result = await db.execute(
                        select(Show).where(Show.title == show_info["show"], Show.user_id == user_id)
                    )
                    existing_show = result.scalar_one_or_none()
                    if existing_show:
                        show = existing_show
                        if plex_metadata:
                            show.title = show_title
                            show.plex_rating_key = plex_rating_key
                            show.is_anime = is_anime
                            show.anime_source = anime_source
                            show.thumb_url = thumb_url
                
                if not show:
                    show = Show(
                        user_id=user_id,
                        title=show_title,
                        media_type=media_type,
                        plex_rating_key=plex_rating_key,
                        is_anime=is_anime,
                        anime_source=anime_source,
                        thumb_url=thumb_url,
                    )
                    db.add(show)
                    await db.flush()
                elif plex_metadata and not show.plex_rating_key:
                    show.plex_rating_key = plex_rating_key
                    show.is_anime = is_anime
                    show.anime_source = anime_source
                    if thumb_url:
                        show.thumb_url = thumb_url
                
                # Find or create season (TV/anime only)
                if not is_movie and show_info.get("season"):
                    result = await db.execute(
                        select(Season).where(
                            Season.show_id == show.id,
                            Season.season_number == show_info["season"],
                        )
                    )
                    season = result.scalar_one_or_none()
                    
                    if not season:
                        season = Season(
                            show_id=show.id,
                            season_number=show_info["season"],
                        )
                        db.add(season)
                        await db.flush()
            
            # Create or update media file
            if existing:
                media_file = existing
                from app.models.entities import AudioTrack
                from sqlalchemy import delete
                await db.execute(
                    delete(AudioTrack).where(AudioTrack.media_file_id == media_file.id)
                )
            else:
                media_file = MediaFile(user_id=user_id, file_path=file_path)
                db.add(media_file)
            
            # Update media file info
            media_file.filename = os.path.basename(file_path)
            media_file.show_id = show.id if show else None
            media_file.season_id = season.id if season else None
            media_file.episode_number = show_info.get("episode") if not is_movie else None
            media_file.file_size = stat.st_size
            media_file.container_format = audio_info.get("container")
            media_file.duration_ms = audio_info.get("duration_ms")
            media_file.last_scanned = datetime.now(timezone.utc)
            media_file.last_modified = file_mtime
            
            await db.flush()
            
            # Add audio tracks
            from app.models.entities import AudioTrack
            for track_info in audio_info.get("audio_tracks", []):
                track = AudioTrack(
                    media_file_id=media_file.id,
                    track_index=track_info.get("index", 0),
                    language=track_info.get("language"),
                    language_raw=track_info.get("language_raw"),
                    codec=track_info.get("codec"),
                    channels=track_info.get("channels"),
                    channel_layout=track_info.get("channel_layout"),
                    bitrate=track_info.get("bitrate"),
                    is_default=track_info.get("is_default", False),
                    is_forced=track_info.get("is_forced", False),
                    title=track_info.get("title"),
                )
                db.add(track)
            
            await db.flush()
            
            # Evaluate preferences and set issues
            final_is_anime = show.is_anime if show else is_anime
            issues = self.preference_engine.evaluate(
                audio_info.get("audio_tracks", []),
                is_anime=final_is_anime,
            )
            
            media_file.has_issues = len(issues) > 0
            media_file.issue_details = "; ".join(issues) if issues else None
            
            return media_file
            
        except Exception as e:
            logger.error("Error processing file %s: %s", file_path, e)
            await scan_state_manager.append_error(f"{file_path}: {str(e)}")
            return None


async def run_scan(
    locations: list[str],
    location_media_types: dict[str, str],
    user_id: int,
    incremental: bool = True,
    user_plex_token: Optional[str] = None,
) -> None:
    """Run a scan on the specified locations."""
    await scan_state_manager.update_status(
        is_running=True,
        files_scanned=0,
        files_total=0,
        current_file=None,
        started_at=datetime.now(timezone.utc),
        errors=[],
    )

    scanner = MediaScanner(plex_token=user_plex_token)

    try:
        # Discover all files first
        all_files = []
        for location in locations:
            await scan_state_manager.update_status(current_location=location)
            try:
                files = scanner.discover_files(location)
                media_type = location_media_types.get(location, "tv")
                all_files.extend([(f, location, media_type) for f in files])
            except Exception as e:
                logger.error("Error discovering files in %s: %s", location, e)
                await scan_state_manager.append_error(f"Error scanning {location}: {str(e)}")

        await scan_state_manager.update_status(files_total=len(all_files))

        # Process files
        async with async_session_maker() as db:
            for i, (file_path, base_path, media_type) in enumerate(all_files):
                if await scan_state_manager.is_cancel_requested():
                    break

                await scan_state_manager.update_status(
                    files_scanned=i + 1,
                    current_file=os.path.basename(file_path),
                )

                await scanner.process_file(file_path, base_path, media_type, user_id, db)

                # Commit periodically
                if (i + 1) % 50 == 0:
                    await db.commit()

            await db.commit()

            # Update scan location stats
            for location in locations:
                result = await db.execute(
                    select(ScanLocation).where(
                        ScanLocation.path == location,
                        ScanLocation.user_id == user_id,
                    )
                )
                scan_loc = result.scalar_one_or_none()
                if scan_loc:
                    scan_loc.last_scanned = datetime.now(timezone.utc)
                    file_count = await db.scalar(
                        select(func.count(MediaFile.id)).where(
                            MediaFile.file_path.like(f"{location}%"),
                            MediaFile.user_id == user_id,
                        )
                    ) or 0
                    scan_loc.file_count = file_count

            await db.commit()

    finally:
        await scan_state_manager.finish_scan()
