"""Export service for generating CSV and JSON reports."""

import csv
import json
import io
from typing import Any


class Exporter:
    """Service for exporting media data to various formats."""

    @staticmethod
    def to_csv(data: list[dict], columns: list[str] = None) -> str:
        """
        Export data to CSV format.
        
        Args:
            data: List of dictionaries to export
            columns: Optional list of column names to include (default: all keys)
        
        Returns:
            CSV string
        """
        if not data:
            return ""
        
        # Determine columns
        if columns is None:
            columns = list(data[0].keys())
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(data)
        
        return output.getvalue()

    @staticmethod
    def to_json(data: list[dict], pretty: bool = True) -> str:
        """
        Export data to JSON format.
        
        Args:
            data: List of dictionaries to export
            pretty: Whether to format with indentation
        
        Returns:
            JSON string
        """
        if pretty:
            return json.dumps(data, indent=2, default=str)
        return json.dumps(data, default=str)

    @staticmethod
    def media_files_to_export_format(media_files: list[Any]) -> list[dict]:
        """
        Convert media file objects to export-friendly dictionaries.
        
        Args:
            media_files: List of MediaFile ORM objects or response models
        
        Returns:
            List of flat dictionaries suitable for export
        """
        result = []
        
        for mf in media_files:
            # Handle both ORM objects and Pydantic models
            if hasattr(mf, '__dict__'):
                data = {
                    "id": getattr(mf, 'id', None),
                    "file_path": getattr(mf, 'file_path', None),
                    "filename": getattr(mf, 'filename', None),
                    "episode_number": getattr(mf, 'episode_number', None),
                    "episode_title": getattr(mf, 'episode_title', None),
                    "file_size_mb": round(getattr(mf, 'file_size', 0) / (1024 * 1024), 2),
                    "container": getattr(mf, 'container_format', None),
                    "has_issues": getattr(mf, 'has_issues', False),
                    "issue_details": getattr(mf, 'issue_details', None),
                }
                
                # Add audio track info
                audio_tracks = getattr(mf, 'audio_tracks', [])
                if audio_tracks:
                    languages = []
                    codecs = []
                    for track in audio_tracks:
                        lang = getattr(track, 'language', None) or getattr(track, 'language_raw', 'Unknown')
                        if lang:
                            languages.append(lang)
                        codec = getattr(track, 'codec', None)
                        if codec:
                            codecs.append(codec)
                    
                    data["audio_languages"] = ", ".join(languages)
                    data["audio_codecs"] = ", ".join(codecs)
                    data["audio_track_count"] = len(audio_tracks)
                else:
                    data["audio_languages"] = ""
                    data["audio_codecs"] = ""
                    data["audio_track_count"] = 0
                
                result.append(data)
            elif isinstance(mf, dict):
                result.append(mf)
        
        return result

    @staticmethod
    def shows_to_export_format(shows: list[Any]) -> list[dict]:
        """
        Convert show objects to export-friendly dictionaries.
        
        Args:
            shows: List of Show ORM objects or response models
        
        Returns:
            List of flat dictionaries suitable for export
        """
        result = []
        
        for show in shows:
            if hasattr(show, '__dict__'):
                data = {
                    "id": getattr(show, 'id', None),
                    "title": getattr(show, 'title', None),
                    "is_anime": getattr(show, 'is_anime', False),
                    "anime_source": getattr(show, 'anime_source', None),
                    "season_count": getattr(show, 'season_count', 0),
                    "episode_count": getattr(show, 'episode_count', 0),
                    "issues_count": getattr(show, 'issues_count', 0),
                }
                result.append(data)
            elif isinstance(show, dict):
                result.append(show)
        
        return result

    @classmethod
    def export_media_files_csv(cls, media_files: list[Any]) -> str:
        """Export media files to CSV."""
        data = cls.media_files_to_export_format(media_files)
        columns = [
            "id", "filename", "file_path", "episode_number", "episode_title",
            "file_size_mb", "container", "audio_track_count", "audio_languages",
            "audio_codecs", "has_issues", "issue_details"
        ]
        return cls.to_csv(data, columns)

    @classmethod
    def export_media_files_json(cls, media_files: list[Any]) -> str:
        """Export media files to JSON."""
        data = cls.media_files_to_export_format(media_files)
        return cls.to_json(data)

    @classmethod
    def export_shows_csv(cls, shows: list[Any]) -> str:
        """Export shows to CSV."""
        data = cls.shows_to_export_format(shows)
        columns = [
            "id", "title", "is_anime", "anime_source",
            "season_count", "episode_count", "issues_count"
        ]
        return cls.to_csv(data, columns)

    @classmethod
    def export_shows_json(cls, shows: list[Any]) -> str:
        """Export shows to JSON."""
        data = cls.shows_to_export_format(shows)
        return cls.to_json(data)
