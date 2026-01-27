"""Plex Media Server connector for metadata retrieval."""

import os
import re
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class PlexShow:
    """Plex show information."""
    rating_key: str
    title: str  # Display title (often romanji for anime)
    original_title: Optional[str]  # Original title (often English for anime)
    year: Optional[int]
    genres: list[str]
    thumb_url: Optional[str]
    is_anime: bool
    # All file paths associated with this show
    file_paths: list[str] = field(default_factory=list)
    # All known title variants for matching
    title_variants: list[str] = field(default_factory=list)


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
        self._shows_cache: dict[str, PlexShow] = {}  # title variant -> show
        self._file_path_cache: dict[str, PlexShow] = {}  # normalized path -> show
        self._shows_by_key: dict[str, PlexShow] = {}  # rating_key -> show

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

    def _normalize_path(self, path: str) -> str:
        """Normalize file path for comparison."""
        # Convert to lowercase and normalize slashes
        return path.lower().replace('\\', '/')

    def _extract_show_folder(self, file_path: str) -> Optional[str]:
        """Extract the show folder name from a file path."""
        # Normalize path
        path = file_path.replace('\\', '/')
        parts = path.split('/')
        
        # Look for common patterns:
        # /media/anime/Show Name/Season 01/episode.mkv
        # /media/tv/Show Name/S01E01.mkv
        for i, part in enumerate(parts):
            if part.lower().startswith('season') or re.match(r's\d+e\d+', part.lower()):
                if i > 0:
                    return parts[i - 1]
        
        # Fallback: return parent of parent directory
        if len(parts) >= 3:
            return parts[-3]
        
        return None

    def _generate_title_variants(self, title: str, original_title: Optional[str] = None) -> list[str]:
        """Generate all possible title variants for matching."""
        variants = set()
        
        for t in [title, original_title]:
            if not t:
                continue
            
            t_lower = t.lower().strip()
            variants.add(t_lower)
            
            # Remove common suffixes/prefixes
            cleaned = re.sub(r'\s*\(\d{4}\)\s*$', '', t_lower)  # Remove (2020)
            cleaned = re.sub(r'\s*\[\d{4}\]\s*$', '', cleaned)  # Remove [2020]
            variants.add(cleaned.strip())
            
            # Remove "the" prefix
            if cleaned.startswith('the '):
                variants.add(cleaned[4:].strip())
            
            # Replace special characters
            normalized = re.sub(r'[^\w\s]', '', cleaned)
            variants.add(normalized.strip())
            
            # Handle common Japanese/English title patterns
            # "Title: Subtitle" -> "Title"
            if ':' in t_lower:
                variants.add(t_lower.split(':')[0].strip())
            
            # "Title - Subtitle" -> "Title"  
            if ' - ' in t_lower:
                variants.add(t_lower.split(' - ')[0].strip())
        
        return list(variants)

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
        Get all TV shows from Plex with all title variants and file paths.
        
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
                
                # Get both title and original title
                title = show.title
                original_title = getattr(show, 'originalTitle', None)
                
                # Generate all title variants
                title_variants = self._generate_title_variants(title, original_title)
                
                # Get all file paths for this show
                file_paths = []
                try:
                    for episode in show.episodes():
                        if episode.media:
                            for media in episode.media:
                                for part in media.parts:
                                    if part.file:
                                        file_paths.append(part.file)
                except Exception:
                    pass
                
                plex_show = PlexShow(
                    rating_key=str(show.ratingKey),
                    title=title,
                    original_title=original_title,
                    year=getattr(show, 'year', None),
                    genres=genres,
                    thumb_url=show.thumbUrl if hasattr(show, 'thumbUrl') else None,
                    is_anime=is_anime,
                    file_paths=file_paths,
                    title_variants=title_variants,
                )
                shows.append(plex_show)
                
                # Cache by rating key
                self._shows_by_key[plex_show.rating_key] = plex_show
                
                # Cache all title variants
                for variant in title_variants:
                    self._shows_cache[variant] = plex_show
                
                # Cache file paths for quick lookup
                for fp in file_paths:
                    normalized = self._normalize_path(fp)
                    self._file_path_cache[normalized] = plex_show
                    
                    # Also cache the show folder name
                    folder = self._extract_show_folder(fp)
                    if folder:
                        self._shows_cache[folder.lower()] = plex_show
        
        return shows

    def _is_anime(self, genres: list[str]) -> bool:
        """Check if genres indicate anime."""
        anime_genres = {"anime", "animation", "アニメ"}
        genre_lower = {g.lower() for g in genres}
        return bool(anime_genres & genre_lower)

    def find_show_by_file(self, file_path: str) -> Optional[PlexShow]:
        """
        Find a show by matching the file path.
        
        This is the most reliable matching method.
        """
        # Ensure cache is populated
        if not self._file_path_cache:
            self.get_tv_shows()
        
        normalized = self._normalize_path(file_path)
        
        # Try exact match first
        if normalized in self._file_path_cache:
            return self._file_path_cache[normalized]
        
        # Try matching by parent directories
        # This handles cases where container paths differ from Plex paths
        filename = os.path.basename(file_path).lower()
        
        for cached_path, show in self._file_path_cache.items():
            if os.path.basename(cached_path).lower() == filename:
                # Same filename - check if parent folder matches too
                cached_parent = os.path.basename(os.path.dirname(cached_path)).lower()
                file_parent = os.path.basename(os.path.dirname(file_path)).lower()
                if cached_parent == file_parent:
                    return show
        
        return None

    def find_show(self, title: str) -> Optional[PlexShow]:
        """
        Find a show by title, checking all title variants.
        
        Tries: exact match, original title match, fuzzy match.
        """
        # Ensure cache is populated
        if not self._shows_cache:
            self.get_tv_shows()
        
        title_lower = title.lower().strip()
        
        # Try exact match against all cached variants
        if title_lower in self._shows_cache:
            return self._shows_cache[title_lower]
        
        # Try normalized version
        normalized = re.sub(r'[^\w\s]', '', title_lower).strip()
        if normalized in self._shows_cache:
            return self._shows_cache[normalized]
        
        # Try fuzzy match
        best_match = None
        best_score = 0
        
        for cached_title, show in self._shows_cache.items():
            score = self._similarity(title_lower, cached_title)
            if score > best_score and score > 0.75:  # 75% threshold
                best_score = score
                best_match = show
        
        return best_match

    def find_show_by_path_or_title(
        self,
        file_path: str,
        title_from_path: Optional[str] = None,
    ) -> Optional[PlexShow]:
        """
        Find a show using multiple strategies in order of reliability:
        1. Direct file path match
        2. Folder name from file path
        3. Title extracted from path
        4. Fuzzy title match
        """
        # Strategy 1: Direct file path match (most reliable)
        show = self.find_show_by_file(file_path)
        if show:
            return show
        
        # Strategy 2: Match by folder name from file path
        folder_name = self._extract_show_folder(file_path)
        if folder_name:
            show = self.find_show(folder_name)
            if show:
                return show
        
        # Strategy 3: Use provided title from path parsing
        if title_from_path:
            show = self.find_show(title_from_path)
            if show:
                return show
        
        return None

    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings using multiple methods."""
        if s1 == s2:
            return 1.0
        
        # Normalize
        s1 = s1.lower().strip()
        s2 = s2.lower().strip()
        
        if s1 == s2:
            return 1.0
        
        # Check if one contains the other
        if s1 in s2:
            return 0.9 * (len(s1) / len(s2))
        if s2 in s1:
            return 0.9 * (len(s2) / len(s1))
        
        # Word overlap (Jaccard similarity)
        words1 = set(s1.split())
        words2 = set(s2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        jaccard = intersection / union
        
        # Also check character-level similarity (handles typos)
        chars1 = set(s1.replace(' ', ''))
        chars2 = set(s2.replace(' ', ''))
        char_intersection = len(chars1 & chars2)
        char_union = len(chars1 | chars2)
        char_sim = char_intersection / char_union if char_union > 0 else 0
        
        # Weighted combination
        return (jaccard * 0.7) + (char_sim * 0.3)

    def get_show_episodes(self, rating_key: str) -> list[PlexEpisode]:
        """Get all episodes for a show."""
        server = self._get_server()
        episodes = []
        
        try:
            show = server.fetchItem(int(rating_key))
            
            for episode in show.episodes():
                file_path = None
                if episode.media and episode.media[0].parts:
                    file_path = episode.media[0].parts[0].file
                
                episodes.append(PlexEpisode(
                    rating_key=str(episode.ratingKey),
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
        show_title: Optional[str] = None,
    ) -> Optional[PlexEpisode]:
        """
        Try to match a file path to a Plex episode.
        
        Returns the matching episode if found.
        """
        # First find the show
        show = self.find_show_by_path_or_title(file_path, show_title)
        if not show:
            return None
        
        episodes = self.get_show_episodes(show.rating_key)
        
        # Try exact path match
        normalized_path = self._normalize_path(file_path)
        for ep in episodes:
            if ep.file_path:
                if self._normalize_path(ep.file_path) == normalized_path:
                    return ep
        
        # Try filename match
        filename = os.path.basename(file_path).lower()
        
        for ep in episodes:
            if ep.file_path:
                ep_filename = os.path.basename(ep.file_path).lower()
                if ep_filename == filename:
                    return ep
        
        return None

    def sync_show_metadata(
        self,
        file_path: str,
        title_from_path: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Sync metadata for a show from Plex.
        
        Uses file path as primary matching strategy.
        
        Returns dict with show info and whether it's anime.
        """
        plex_show = self.find_show_by_path_or_title(file_path, title_from_path)
        
        if not plex_show:
            return None
        
        return {
            "plex_rating_key": plex_show.rating_key,
            "title": plex_show.title,
            "original_title": plex_show.original_title,
            "year": plex_show.year,
            "genres": plex_show.genres,
            "thumb_url": plex_show.thumb_url,
            "is_anime": plex_show.is_anime,
        }

    def get_all_title_mappings(self) -> dict[str, str]:
        """
        Get a mapping of all known title variants to their canonical Plex title.
        
        Useful for debugging matching issues.
        """
        if not self._shows_cache:
            self.get_tv_shows()
        
        mappings = {}
        for variant, show in self._shows_cache.items():
            mappings[variant] = show.title
        
        return mappings
