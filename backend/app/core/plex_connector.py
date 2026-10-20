"""Plex Media Server connector for metadata retrieval."""

import logging
import re
from functools import lru_cache
from threading import Lock
from typing import Optional
from dataclasses import dataclass, field

from app.core.artwork import artwork_reference

logger = logging.getLogger(__name__)


class PlexArtworkError(RuntimeError):
    """Artwork failures expose no upstream URLs, credentials, or response bodies."""


MAX_ARTWORK_BYTES = 5 * 1024 * 1024


@lru_cache(maxsize=32)
def artwork_connector(token: str):
    """Reuse bounded in-memory connections so each poster need not rediscover Plex."""
    return PlexConnector(token)


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
    file_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlexShowMatch:
    show: Optional[PlexShow] = None
    strategy: str = "unmatched"
    candidate_count: int = 0

    @property
    def ambiguous(self) -> bool:
        return self.candidate_count > 1


class AmbiguousPlexMatch(RuntimeError):
    """A reviewable identity conflict, not a failed Plex connection."""

    def __init__(self, match: PlexShowMatch):
        super().__init__(f"Ambiguous Plex TV {match.strategy} match ({match.candidate_count} titles). "
                         "Plex metadata was not applied; review the title and library paths. "
                         "Automatic media editing was skipped for this file.")


class PlexConnector:
    """Connector for Plex Media Server API."""

    def __init__(self, token: Optional[str] = None, server_url: Optional[str] = None, *, anime_genres: Optional[list[str]] = None):
        """
        Initialize Plex connector.
        
        Args:
            token: Plex authentication token
            server_url: Plex server URL (if None, will auto-discover)
            anime_genres: Exact genre labels that indicate anime; an empty list disables genre hints
        """
        self.token = token
        self.server_url = server_url
        self.anime_genres = {genre.strip().casefold() for genre in
                             (anime_genres if anime_genres is not None else ["anime", "アニメ"])
                             if genre.strip()}
        self._server = None
        self._connection_lock = Lock()
        self._library_loaded = False
        # Every index retains collisions instead of silently choosing the last item.
        self._shows_cache: dict[str, dict[str, PlexShow]] = {}
        self._file_path_cache: dict[str, dict[str, PlexShow]] = {}
        self._relative_path_cache: dict[tuple[str, ...], dict[str, PlexShow]] = {}
        self._shows_by_key: dict[str, PlexShow] = {}  # rating_key -> show
        self._movies: Optional[list[PlexShow]] = None

    def fetch_artwork(self, reference: str) -> tuple[bytes, str]:
        path = artwork_reference(reference)
        if path is None:
            raise PlexArtworkError("Artwork is unavailable.")
        try:
            server = self._get_server()
            # Use the selected Plex connection, never a host supplied by catalog data.
            # Server access tokens can differ from the account's login token.
            with server._session.get(server.url(path, includeToken=False),
                                     headers=server._headers(), timeout=10,
                                     stream=True, allow_redirects=False) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if response.status_code != 200 or content_type not in {
                    "image/jpeg", "image/png", "image/webp", "image/gif"
                }:
                    raise PlexArtworkError("Artwork is unavailable.")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_ARTWORK_BYTES:
                        raise PlexArtworkError("Artwork is unavailable.")
                    chunks.append(chunk)
                if not size:
                    raise PlexArtworkError("Artwork is unavailable.")
                return b"".join(chunks), content_type
        except Exception:
            # Requests/Plex exceptions may contain authenticated response URLs.
            raise PlexArtworkError("Artwork is unavailable.") from None

    def sync_movie_metadata(self, file_path: str, title_from_path: Optional[str] = None) -> Optional[dict]:
        """Match only movies, preferring exact paths and unambiguous title/year pairs."""
        if self._movies is None:
            movies = []
            for section in self._get_server().library.sections():
                if section.type != "movie":
                    continue
                for movie in section.all():
                    genres = [genre.tag for genre in (getattr(movie, "genres", None) or [])]
                    movies.append(PlexShow(
                        rating_key=str(movie.ratingKey), title=movie.title,
                        original_title=getattr(movie, "originalTitle", None),
                        year=getattr(movie, "year", None), genres=genres,
                        thumb_url=artwork_reference(getattr(movie, "thumb", None) or getattr(movie, "thumbUrl", None)),
                        is_anime=self._is_anime(genres),
                        file_paths=[part.file for media in (getattr(movie, "media", None) or [])
                                    for part in media.parts if part.file],
                    ))
            self._movies = movies
        path = self._normalize_path(file_path)
        matches = [movie for movie in self._movies
                   if any(self._normalize_path(candidate) == path for candidate in movie.file_paths)]
        if not matches and title_from_path:
            match = re.fullmatch(r"(.*?)\s*\((\d{4})\)", title_from_path.strip())
            title, year = (match[1].strip(), int(match[2])) if match else (title_from_path.strip(), None)
            def normalize(value):
                return re.sub(r"[^\w]+", " ", value or "").strip().casefold()
            matches = [movie for movie in self._movies
                       if normalize(title) in {normalize(movie.title), normalize(movie.original_title)}
                       and (year is None or movie.year == year)]
        if len(matches) != 1:
            return None
        movie = matches[0]
        return {"plex_rating_key": movie.rating_key, "title": movie.title, "year": movie.year,
                "original_title": movie.original_title, "genres": movie.genres,
                "thumb_url": movie.thumb_url, "is_anime": movie.is_anime}

    def _get_server(self):
        with self._connection_lock:
            return self._connect_server()

    def _connect_server(self):
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
                self._server = PlexServer(self.server_url, self.token, timeout=10)
            else:
                # Auto-discover from account
                account = MyPlexAccount(token=self.token, timeout=10)
                resources = account.resources()
                
                # Find first server
                for resource in resources:
                    if resource.provides == "server":
                        self._server = resource.connect(timeout=10)
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
        """Use directory components, never an episode filename, as title evidence."""
        parts = file_path.replace('\\', '/').rstrip('/').split('/')
        if len(parts) < 2:
            return None
        if self._is_season_folder(parts[-2]):
            return parts[-3] if len(parts) >= 3 else None
        return parts[-2] or None

    @staticmethod
    def _is_season_folder(value: str) -> bool:
        return bool(re.fullmatch(r"(?:season[\s._-]*\d+|s\d+|specials)", value, re.IGNORECASE))

    def _relative_file_key(self, file_path: str) -> tuple[str, ...]:
        parts = self._normalize_path(file_path).rstrip('/').split('/')
        # A season plus a generic filename is not sufficient show identity.
        count = 3 if len(parts) >= 2 and self._is_season_folder(parts[-2]) else 2
        return tuple(parts[-count:]) if len(parts) >= count else ()

    @staticmethod
    def _title_key(title: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.casefold())).strip()

    @staticmethod
    def _unique_match(candidates, strategy: str) -> PlexShowMatch:
        by_key = {show.rating_key: show for show in candidates}
        return PlexShowMatch(next(iter(by_key.values())) if len(by_key) == 1 else None,
                             strategy, len(by_key))

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
                genres = [g.tag for g in (getattr(show, 'genres', None) or [])]
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
                    # A partial inventory cannot establish uniqueness. The scanner
                    # reports unavailable enrichment and continues with local data.
                    raise RuntimeError("Plex TV episode inventory is unavailable") from None
                
                plex_show = PlexShow(
                    rating_key=str(show.ratingKey),
                    title=title,
                    original_title=original_title,
                    year=getattr(show, 'year', None),
                    genres=genres,
                    thumb_url=artwork_reference(getattr(show, "thumb", None) or getattr(show, "thumbUrl", None)),
                    is_anime=is_anime,
                    file_paths=file_paths,
                    title_variants=title_variants,
                )
                shows.append(plex_show)
                
        # Publish a complete replacement only after inventory succeeds. This also
        # prevents a filtered/repeated library load from leaving stale aliases.
        titles, paths, relative_paths = {}, {}, {}
        for show in shows:
            variants = list(show.title_variants)
            for file_path in show.file_paths:
                paths.setdefault(self._normalize_path(file_path), {})[show.rating_key] = show
                relative_paths.setdefault(self._relative_file_key(file_path), {})[show.rating_key] = show
                folder = self._extract_show_folder(file_path)
                if folder:
                    variants.extend(self._generate_title_variants(folder))
            for variant in variants:
                key = self._title_key(variant)
                if key:
                    titles.setdefault(key, {})[show.rating_key] = show
        self._shows_cache, self._file_path_cache = titles, paths
        self._relative_path_cache = relative_paths
        self._shows_by_key = {show.rating_key: show for show in shows}
        
        self._library_loaded = library_name is None
        return shows

    def _is_anime(self, genres: list[str]) -> bool:
        """Only explicit, configured genre labels indicate anime."""
        return bool(self.anime_genres & {genre.strip().casefold() for genre in genres})

    def find_show_by_file(self, file_path: str) -> Optional[PlexShow]:
        """Return only an unambiguous exact or relative show/season/file match."""
        return self._match_show_file(file_path).show

    def _match_show_file(self, file_path: str) -> PlexShowMatch:
        if not self._library_loaded:
            self.get_tv_shows()
        normalized = self._normalize_path(file_path)
        if normalized in self._file_path_cache:
            return self._unique_match(self._file_path_cache[normalized].values(), "exact path")
        candidates = self._relative_path_cache.get(self._relative_file_key(file_path), {})
        return self._unique_match(candidates.values(), "relative path")

    def find_show(self, title: str) -> Optional[PlexShow]:
        """Resolve title aliases/year or a single plausible fuzzy candidate."""
        match = self._match_show_title(title)
        if not match.candidate_count:
            match = self._match_show_title(title, fuzzy=True)
        return match.show

    def _match_show_title(self, title: str, *, fuzzy=False) -> PlexShowMatch:
        if not self._library_loaded:
            self.get_tv_shows()
        year_match = re.fullmatch(r"(.*?)\s*(?:\((\d{4})\)|\[(\d{4})\])", title.strip())
        name, year = (year_match[1], int(year_match[2] or year_match[3])) if year_match else (title, None)
        key = self._title_key(name)
        if not key:
            return PlexShowMatch()
        candidates = []
        variants = self._shows_cache.items() if fuzzy else [(key, self._shows_cache.get(key, {}))]
        for variant, shows in variants:
            if not fuzzy or self._similarity(key, variant) > 0.75:
                candidates.extend(show for show in shows.values() if year is None or show.year == year)
        return self._unique_match(candidates, "fuzzy title" if fuzzy else "title/year" if year else "title")

    def find_show_by_path_or_title(
        self,
        file_path: str,
        title_from_path: Optional[str] = None,
    ) -> Optional[PlexShow]:
        return self.match_show(file_path, title_from_path).show

    def match_show(self, file_path: str, title_from_path: Optional[str] = None) -> PlexShowMatch:
        """Do not downgrade ambiguous stronger evidence to a weaker guess."""
        match = self._match_show_file(file_path)
        if match.candidate_count:
            return match
        hints = list(dict.fromkeys(filter(None, [self._extract_show_folder(file_path), title_from_path])))
        # Exact aliases from either hint precede all fuzzy matching.
        for fuzzy in (False, True):
            for title in hints:
                match = self._match_show_title(title, fuzzy=fuzzy)
                if match.candidate_count:
                    return match
        return PlexShowMatch()

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
                paths = [part.file for media in (getattr(episode, "media", None) or [])
                         for part in media.parts if part.file]
                
                episodes.append(PlexEpisode(
                    rating_key=str(episode.ratingKey),
                    title=episode.title,
                    season_number=episode.seasonNumber,
                    episode_number=episode.episodeNumber,
                    file_path=paths[0] if paths else None,
                    file_paths=paths,
                ))
        except Exception as e:
            logger.warning("Failed to get episodes for rating_key '%s': %s", rating_key, e)
        
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
        
        for exact in (True, False):
            matches = {}
            key = self._normalize_path(file_path) if exact else self._relative_file_key(file_path)
            for episode in episodes:
                for path in episode.file_paths or ([episode.file_path] if episode.file_path else []):
                    candidate = self._normalize_path(path) if exact else self._relative_file_key(path)
                    if candidate == key:
                        matches[episode.rating_key] = episode
            if matches:
                return next(iter(matches.values())) if len(matches) == 1 else None
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
        match = self.match_show(file_path, title_from_path)
        if match.ambiguous:
            raise AmbiguousPlexMatch(match)
        plex_show = match.show
        
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
        if not self._library_loaded:
            self.get_tv_shows()
        
        mappings = {}
        for variant, shows in self._shows_cache.items():
            if len(shows) == 1:
                mappings[variant] = next(iter(shows.values())).title
        
        return mappings
