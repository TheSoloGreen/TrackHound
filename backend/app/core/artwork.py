"""Credential-free Plex artwork references and public avatar URLs."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def artwork_reference(value: str | None) -> str | None:
    """Keep only a Plex metadata thumbnail path, never its host or credentials."""
    if not value:
        return None
    try:
        path = urlsplit(value).path
    except ValueError:
        return None
    return path if re.fullmatch(r"/library/metadata/[1-9]\d*/thumb(?:/\d+)?", path) else None


def public_avatar_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return None
        query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                 if key.casefold() != "x-plex-token"]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    except ValueError:
        return None


def artwork_url(show) -> str | None:
    """Browser-visible URLs always point to TrackHound's authorized endpoint."""
    return f"/api/media/shows/{show.id}/artwork" if artwork_reference(show.thumb_url) else None
