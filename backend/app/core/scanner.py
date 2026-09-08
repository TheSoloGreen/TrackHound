"""Media file scanner for discovering and processing media files."""

import asyncio
import logging
import stat as stat_module
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session_maker
from app.models.entities import MediaFile, Show, Season, ScanLocation, AudioTrack
from app.core.analyzer import AudioAnalyzer, require_successful_analysis
from app.core.media_access import get_media_edit_capabilities
from app.core.plex_connector import PlexConnector
from app.core.preference_engine import PreferenceEngine, AudioPreferences
from app.core.audio_fixer import set_default_track_by_index
from app.models.schemas import AnimeDetectionSettings, normalize_file_extensions
from app.core.user_settings import load_user_settings
from app.core.classification import classify_show
from app.core.scan_state import scan_state_manager

logger = logging.getLogger(__name__)

# Default supported extensions
DEFAULT_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv"}

# Regex patterns for parsing show/season/episode from file paths
SHOW_PATTERNS = [
    # Show Name/Season 01/E01 - Title.mkv
    re.compile(
        r"^(?P<show>.+?)[/\\]Season\s*(?P<season>\d+)[/\\].*?[Ee](?P<episode>\d+)",
        re.IGNORECASE,
    ),
    # Show Name/S01E01 - Title.mkv
    re.compile(
        r"^(?P<show>.+?)[/\\][Ss](?P<season>\d+)[Ee](?P<episode>\d+)", re.IGNORECASE
    ),
    # Show Name - S01E01 - Title.mkv
    re.compile(
        r"^(?P<show>.+?)\s*-\s*[Ss](?P<season>\d+)[Ee](?P<episode>\d+)", re.IGNORECASE
    ),
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
    """Scan one user's library using a snapshot of their saved preferences."""

    def __init__(self, extensions=None, plex_token=None, audio_preferences=None, anime_detection=None):
        self.extensions = set(normalize_file_extensions(list(extensions))) if extensions is not None else DEFAULT_EXTENSIONS
        self.analyzer = AudioAnalyzer()
        self.plex_connector = PlexConnector(plex_token) if plex_token else None
        self.plex_failed = False
        self.preference_engine = PreferenceEngine(audio_preferences)
        self.anime_detection = anime_detection or AnimeDetectionSettings()

    def _get_english_default_fix_index(self, audio_tracks: list[dict]) -> Optional[int]:
        """Return the English track index to promote as default, if needed."""
        default_track = None
        english_indices: list[int] = []

        for track in audio_tracks:
            language = (track.get("language") or "").lower()
            track_index = track.get("index")
            if language == "en" and isinstance(track_index, int):
                english_indices.append(track_index)
            if track.get("is_default"):
                default_track = track

        if not english_indices:
            return None

        default_language = (default_track.get("language") or "").lower() if default_track else None
        if default_language == "en":
            return None

        return english_indices[0]

    def _auto_fix_default_track(self, file_path: str, audio_info: dict, is_anime: bool) -> dict:
        """Try to set the English track as default for non-anime files when enabled."""
        if not self.preference_engine.preferences.auto_fix_english_default_non_anime:
            return audio_info

        audio_tracks = audio_info.get("audio_tracks", [])
        if is_anime or not audio_tracks:
            return audio_info

        if not get_media_edit_capabilities(file_path).set_default_audio:
            return audio_info

        english_index = self._get_english_default_fix_index(audio_tracks)
        if english_index is None:
            return audio_info

        if set_default_track_by_index(file_path, audio_tracks, english_index):
            logger.info("Auto-fixed default audio track to English: %s", file_path)
            return self.analyzer.analyze(file_path)

        logger.warning("Auto-fix skipped or failed for file: %s", file_path)
        return audio_info

    def discover_files(self, location: str) -> list[str]:
        """Fail the location on unreadable directories instead of returning a partial list."""
        root_path = Path(location).resolve(strict=True)
        if not root_path.is_dir():
            raise ValueError(f"Location is not a directory: {location}")
        files = []

        def fail(error):
            raise error

        for root, _, names in os.walk(root_path, onerror=fail):
            for name in names:
                if name.startswith(".trackhound-") or Path(name).suffix.lower() not in self.extensions:
                    continue
                path = Path(root) / name
                resolved = path.resolve(strict=True)
                if resolved.is_relative_to(root_path) and resolved.is_file():
                    files.append(str(path))
        return sorted(files)

    async def process_file(self, file_path, base_path, media_type, user_id, db, *, incremental=True):
        """Roll back only the current file when a probe or database write fails."""
        try:
            async with db.begin_nested():
                return await self._process_file(file_path, base_path, media_type, user_id, db, incremental)
        except Exception as error:
            logger.error("Error processing file %s: %s", file_path, error)
            await scan_state_manager.append_error(user_id, f"{file_path}: {error}")
            return None

    async def _process_file(self, file_path, base_path, media_type, user_id, db, incremental):
        existing = await db.scalar(select(MediaFile).where(MediaFile.file_path == file_path, MediaFile.user_id == user_id))
        before = await asyncio.to_thread(os.stat, file_path)
        modified = datetime.fromtimestamp(before.st_mtime)
        if incremental and existing and existing.last_modified == modified and existing.file_size == before.st_size:
            return existing

        audio = require_successful_analysis(await asyncio.to_thread(self.analyzer.analyze, file_path))
        after = await asyncio.to_thread(os.stat, file_path)
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("File changed during analysis; retry the scan when external writes finish.")

        base_type = "movie" if media_type == "movie" else "tv"
        info = ({"show": parse_movie_title(file_path, base_path), "season": None, "episode": None}
                if base_type == "movie" else parse_show_info(file_path, base_path))
        metadata = None
        if self.plex_connector:
            try:
                metadata = await asyncio.to_thread(self.plex_connector.sync_show_metadata, file_path=file_path, title_from_path=info["show"])
            except Exception as error:
                logger.warning("Plex enrichment disabled for this scan (%s)", type(error).__name__)
                self.plex_connector = None
                self.plex_failed = True
                await scan_state_manager.append_warning(user_id, "Plex metadata is unavailable. Local scanning continues; check Plex server access or sign in again before the next scan.")

        title = metadata.get("title") if metadata else info["show"]
        rating_key = metadata.get("plex_rating_key") if metadata else None
        show = await db.scalar(select(Show).where(Show.id == existing.show_id, Show.user_id == user_id)) if existing and existing.show_id else None
        if not show and rating_key:
            show = await db.scalar(select(Show).where(Show.plex_rating_key == rating_key, Show.user_id == user_id).order_by(Show.id).limit(1))
        if not show and title:
            show = await db.scalar(select(Show).where(Show.user_id == user_id, Show.title.in_([title, info["show"]]),
                                                     Show.base_media_type == base_type).order_by(Show.id).limit(1))

        # An anime location forces anime; other locations allow automatic hints.
        # Manual positive and negative overrides win, including before auto-fix.
        folder_hint = any(keyword in str(Path(file_path).parent).lower() for keyword in self.anime_detection.anime_folder_keywords)
        plex_hint = bool(self.anime_detection.use_plex_genres and metadata and metadata.get("is_anime"))
        is_anime = media_type == "anime" or folder_hint or plex_hint
        source = "location" if media_type == "anime" else "folder" if folder_hint else "plex_genre" if plex_hint else None
        if show and show.anime_source == "manual":
            is_anime, source, base_type = show.is_anime, "manual", show.base_media_type
        elif show and self.plex_failed and self.anime_detection.use_plex_genres and show.anime_source == "plex_genre" and not is_anime:
            is_anime, source = show.is_anime, "plex_genre"

        if title and not show:
            show = Show(user_id=user_id, title=title)
            db.add(show)
        if show:
            classify_show(show, is_anime, source, base_type)
            if metadata:
                show.title = title
                show.plex_rating_key = rating_key
                show.thumb_url = metadata.get("thumb_url")
            await db.flush()

        audio = require_successful_analysis(await asyncio.to_thread(self._auto_fix_default_track, file_path, audio, is_anime))
        after = await asyncio.to_thread(os.stat, file_path)
        season = None
        if show and base_type != "movie" and info.get("season") is not None:
            season = await db.scalar(select(Season).where(Season.show_id == show.id, Season.season_number == info["season"]).order_by(Season.id).limit(1))
            if not season:
                season = Season(show_id=show.id, season_number=info["season"])
                db.add(season)
                await db.flush()

        media_file = existing or MediaFile(user_id=user_id, file_path=file_path)
        if existing:
            await db.execute(delete(AudioTrack).where(AudioTrack.media_file_id == existing.id))
        else:
            db.add(media_file)
        media_file.filename = Path(file_path).name
        media_file.show_id = show.id if show else None
        media_file.season_id = season.id if season else None
        media_file.episode_number = info.get("episode") if base_type != "movie" else None
        media_file.file_size = after.st_size
        media_file.container_format = audio.get("container")
        media_file.duration_ms = audio.get("duration_ms")
        media_file.last_scanned = datetime.now(timezone.utc).replace(tzinfo=None)
        media_file.last_modified = datetime.fromtimestamp(after.st_mtime)
        issues = self.preference_engine.evaluate(audio.get("audio_tracks", []), is_anime=is_anime)
        media_file.has_issues = bool(issues)
        media_file.issue_details = "; ".join(issues) if issues else None
        await db.flush()
        for track in audio.get("audio_tracks", []):
            db.add(AudioTrack(
                media_file_id=media_file.id, track_index=track.get("index", 0),
                is_default=track.get("is_default", False), is_forced=track.get("is_forced", False),
                **{key: track.get(key) for key in ("language", "language_raw", "codec", "channels", "channel_layout", "bitrate", "title")},
            ))
        await db.flush()
        return media_file


def _root_identity(root):
    value = os.stat(root)
    if not stat_module.S_ISDIR(value.st_mode):
        raise ValueError(f"Scan location is not a directory: {root}")
    return value.st_dev, value.st_ino


def _missing_paths(rows, roots):
    """Only remove genuinely missing paths; ignored extensions remain indexed."""
    for root, identity in roots.items():
        if _root_identity(root) != identity:
            raise ValueError(f"Location changed or was unmounted during scanning: {root}")
    missing = []
    for row in rows:
        try:
            os.stat(row.file_path)
        except FileNotFoundError:
            missing.append(row.id)
        # Permission and other I/O errors abort cleanup, rather than implying deletion.
    return missing


async def _reconcile_missing_files(db, user_id, discovered, roots):
    if not roots:
        return 0
    scope = or_(*(MediaFile.file_path.startswith(root.rstrip("/") + "/", autoescape=True) for root in roots))
    rows = (await db.execute(select(MediaFile.id, MediaFile.file_path).where(MediaFile.user_id == user_id, scope))).all()
    missing = await asyncio.to_thread(_missing_paths, [row for row in rows if row.file_path not in discovered], roots)
    for start in range(0, len(missing), 500):
        await db.execute(delete(MediaFile).where(MediaFile.user_id == user_id, MediaFile.id.in_(missing[start:start + 500])))
    await db.execute(delete(Season).where(Season.show_id.in_(select(Show.id).where(Show.user_id == user_id)),
                                         ~select(MediaFile.id).where(MediaFile.season_id == Season.id).exists()))
    await db.execute(delete(Show).where(Show.user_id == user_id,
                                       ~select(MediaFile.id).where(MediaFile.show_id == Show.id).exists(),
                                       ~select(Season.id).where(Season.show_id == Show.id).exists()))
    return len(missing)


async def run_scan(locations, location_media_types, user_id, incremental=True, user_plex_token=None, plex_warning=None):
    """Persist valid files, but reconcile only a complete, uncancelled local scan."""
    await scan_state_manager.update_status(user_id, is_running=True, outcome="running", files_scanned=0,
        files_total=0, files_removed=0, current_file=None, started_at=datetime.now(timezone.utc), finished_at=None,
        errors=[], warnings=[], error_count=0, warning_count=0)
    failed = False
    try:
        if plex_warning:
            await scan_state_manager.append_warning(user_id, plex_warning)
        async with async_session_maker() as db:
            settings = await load_user_settings(db, user_id)
            preferences = AudioPreferences(**settings.audio_preferences.model_dump(exclude={"audio_track_keep_languages"}))
            scanner = MediaScanner(settings.file_extensions, user_plex_token, preferences, settings.anime_detection)
            scanner.plex_failed = bool(plex_warning)
            configured = (await db.scalars(select(ScanLocation).where(ScanLocation.user_id == user_id, ScanLocation.enabled == True))).all()
            types = {location.path: location.media_type for location in configured}
            types.update(location_media_types)
            all_files, roots, complete = set(), {}, True
            for location in locations:
                if await scan_state_manager.is_cancel_requested(user_id):
                    break
                await scan_state_manager.update_status(user_id, current_location=location)
                try:
                    identity = await asyncio.to_thread(_root_identity, location)
                    found = await asyncio.to_thread(scanner.discover_files, location)
                    all_files.update(found)
                    roots[location] = identity
                except Exception as error:
                    complete = False
                    await scan_state_manager.append_error(user_id, f"Cannot fully read {location}: {error}")
            await scan_state_manager.update_status(user_id, files_total=len(all_files))
            if not roots and not await scan_state_manager.is_cancel_requested(user_id):
                raise ValueError("No scan location could be read completely.")
            for index, file_path in enumerate(sorted(all_files)):
                if await scan_state_manager.is_cancel_requested(user_id):
                    break
                # The deepest configured enabled root determines classification,
                # even when the user starts a scan from an overlapping parent.
                candidates = [root for root in types if Path(file_path).is_relative_to(root)]
                base_path = max(candidates, key=lambda root: len(Path(root).parts))
                await scan_state_manager.update_status(user_id, current_location=base_path, current_file=Path(file_path).name)
                result = await scanner.process_file(file_path, base_path, types[base_path], user_id, db, incremental=incremental)
                complete = complete and result is not None
                await db.commit()
                await scan_state_manager.update_status(user_id, files_scanned=index + 1)
            reconciled = complete and len(roots) == len(locations) and not await scan_state_manager.is_cancel_requested(user_id)
            removed = await _reconcile_missing_files(db, user_id, all_files, roots) if reconciled else 0
            # Counts reflect the rows that were actually saved, even after a partial scan.
            current_locations = (await db.scalars(select(ScanLocation).where(ScanLocation.user_id == user_id))).all()
            for location in current_locations:
                location.file_count = await db.scalar(select(func.count(MediaFile.id)).where(MediaFile.user_id == user_id,
                    MediaFile.file_path.startswith(location.path.rstrip("/") + "/", autoescape=True))) or 0
                if reconciled and location.path in roots:
                    location.last_scanned = datetime.now(timezone.utc).replace(tzinfo=None)
            if reconciled and await scan_state_manager.is_cancel_requested(user_id):
                await db.rollback()
            else:
                await db.commit()
                await scan_state_manager.update_status(user_id, files_removed=removed)
    except asyncio.CancelledError:
        failed = True
        raise
    except Exception as error:
        failed = True
        logger.error("Scan failed for user %s: %s", user_id, error)
        await scan_state_manager.append_error(user_id, f"Scan failed: {error}")
    finally:
        await scan_state_manager.finish_scan(user_id, failed=failed)
