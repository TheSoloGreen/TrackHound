"""Plex Media Server connector for metadata retrieval."""

from typing import Optional
from dataclasses import dataclass


@dataclass
class PlexShow:
    """Plex show information."""
    rating_key: str
    title: str
    year: Optional[int]
    genres: list[str]
    thumb_url: Optional[str]
    is_anime: bool


@dataclass
class PlexEpisode:
    """Plex episode information."""
    rating_key: str
    title: str
    season_number: int
    episode_number: int
    file_path: Optional[str]


class PlexConnector:
    """Connector for Plex Media Server API."""

    def __init__(self, token: Optional[str] = None, server_url: Optional[str] = None):
        """
        Initialize Plex connector.
        
        Args:
            token: Plex authentication token
            server_url: Plex server URL (if None, will auto-discover)
        """
        self.token = token
        self.server_url = server_url
        self._server = None
        self._shows_cache: dict[str, PlexShow] = {}

    def _get_server(self):
        """Get or create Plex server connection."""
        if self._server is not None:
            return self._server
        
        if not self.token:
            raise ValueError("Plex token is required")
        
        try:
            from plexapi.myplex import MyPlexAccount
            from plexapi.server import PlexServer
            
            if self.server_url:
                # Direct connection to server
                self._server = PlexServer(self.server_url, self.token)
            else:
                # Auto-discover from account
                account = MyPlexAccount(token=self.token)
                resources = account.resources()
                
                # Find first server
                for resource in resources:
                    if resource.provides == "server":
                        self._server = resource.connect()
                        break
                
                if not self._server:
                    raise ValueError("No Plex server found")
            
            return self._server
            
        except ImportError:
            raise ImportError("plexapi is required for Plex integration")

    def get_libraries(self) -> list[dict]:
        """Get list of Plex libraries."""
        server = self._get_server()
        libraries = []
        
        for section in server.library.sections():
            libraries.append({
                "key": section.key,
                "title": section.title,
                "type": section.type,
                "agent": section.agent,
            })
        
        return libraries

    def get_tv_shows(self, library_name: Optional[str] = None) -> list[PlexShow]:
        """
        Get all TV shows from Plex.
        
        Args:
            library_name: Optional library name to filter by
        """
        server = self._get_server()
        shows = []
        
        for section in server.library.sections():
            if section.type != "show":
                continue
            if library_name and section.title != library_name:
                continue
            
            for show in section.all():
                genres = [g.tag for g in getattr(show, 'genres', [])]
                is_anime = self._is_anime(genres)
                
                plex_show = PlexShow(
                    rating_key=show.ratingKey,
                    title=show.title,
                    year=getattr(show, 'year', None),
                    genres=genres,
                    thumb_url=show.thumbUrl if hasattr(show, 'thumbUrl') else None,
                    is_anime=is_anime,
                )
                shows.append(plex_show)
                self._shows_cache[show.title.lower()] = plex_show
        
        return shows

    def _is_anime(self, genres: list[str]) -> bool:
        """Check if genres indicate anime."""
        anime_genres = {"anime", "animation", "アニメ"}
        genre_lower = {g.lower() for g in genres}
        return bool(anime_genres & genre_lower)

    def find_show(self, title: str) -> Optional[PlexShow]:
        """
        Find a show by title.
        
        Uses fuzzy matching to handle slight title differences.
        """
        title_lower = title.lower().strip()
        
        # Check cache first
        if title_lower in self._shows_cache:
            return self._shows_cache[title_lower]
        
        # If cache empty, load shows
        if not self._shows_cache:
            self.get_tv_shows()
            if title_lower in self._shows_cache:
                return self._shows_cache[title_lower]
        
        # Fuzzy match
        best_match = None
        best_score = 0
        
        for cached_title, show in self._shows_cache.items():
            score = self._similarity(title_lower, cached_title)
            if score > best_score and score > 0.8:  # 80% threshold
                best_score = score
                best_match = show
        
        return best_match

    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate simple similarity between two strings."""
        if s1 == s2:
            return 1.0
        
        # Normalize strings
        s1 = s1.lower().strip()
        s2 = s2.lower().strip()
        
        if s1 == s2:
            return 1.0
        
        # Check if one contains the other
        if s1 in s2 or s2 in s1:
            return 0.9
        
        # Word overlap
        words1 = set(s1.split())
        words2 = set(s2.split())
        
        if not words1 or not words2:
            return 0.0
        
        overlap = len(words1 & words2)
        total = len(words1 | words2)
        
        return overlap / total

    def get_show_episodes(self, rating_key: str) -> list[PlexEpisode]:
        """Get all episodes for a show."""
        server = self._get_server()
        episodes = []
        
        try:
            show = server.fetchItem(rating_key)
            
            for episode in show.episodes():
                file_path = None
                if episode.media and episode.media[0].parts:
                    file_path = episode.media[0].parts[0].file
                
                episodes.append(PlexEpisode(
                    rating_key=episode.ratingKey,
                    title=episode.title,
                    season_number=episode.seasonNumber,
                    episode_number=episode.episodeNumber,
                    file_path=file_path,
                ))
        except Exception:
            pass
        
        return episodes

    def match_file_to_episode(
        self,
        file_path: str,
        show_title: str,
    ) -> Optional[PlexEpisode]:
        """
        Try to match a file path to a Plex episode.
        
        Returns the matching episode if found.
        """
        show = self.find_show(show_title)
        if not show:
            return None
        
        episodes = self.get_show_episodes(show.rating_key)
        
        # Try exact path match
        for ep in episodes:
            if ep.file_path and ep.file_path == file_path:
                return ep
        
        # Try filename match
        import os
        filename = os.path.basename(file_path).lower()
        
        for ep in episodes:
            if ep.file_path:
                ep_filename = os.path.basename(ep.file_path).lower()
                if ep_filename == filename:
                    return ep
        
        return None

    def sync_show_metadata(
        self,
        show_title: str,
    ) -> Optional[dict]:
        """
        Sync metadata for a show from Plex.
        
        Returns dict with show info and whether it's anime.
        """
        plex_show = self.find_show(show_title)
        
        if not plex_show:
            return None
        
        return {
            "plex_rating_key": plex_show.rating_key,
            "title": plex_show.title,
            "year": plex_show.year,
            "genres": plex_show.genres,
            "thumb_url": plex_show.thumb_url,
            "is_anime": plex_show.is_anime,
        }
