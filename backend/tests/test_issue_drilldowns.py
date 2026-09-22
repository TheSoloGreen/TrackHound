import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.api import media
from app.core.preference_engine import PreferenceEngine
from app.core.analyzer import normalize_language
from app.models.entities import MediaFile, AudioTrack, Show
from app.models.schemas import LanguageReviewRequest
from test_scanner_run_scan import library, write_media, run, files


@pytest.mark.asyncio
async def test_each_dashboard_cell_matches_list_and_export_with_ownership(library):
    async with library.sessions() as db:
        for kind in ('movie', 'tv', 'anime'):
            show = Show(user_id=library.user.id, title=kind, media_type=kind, is_anime=kind == 'anime')
            db.add(show)
            await db.flush()
            for index, message in enumerate([
                'Missing English audio track', 'No track tagged Japanese; audio language needs review for dual audio (anime)',
                "Default audio track is 'de', expected English", 'No audio tracks found',
            ]):
                db.add(MediaFile(user_id=library.user.id, show_id=show.id, filename=f'{kind}-{index}.mkv',
                    file_path=f'/media/{kind}-{index}.mkv', file_size=1, last_modified=datetime.now(),
                    has_issues=True, issue_details=message))
        await db.commit()
        stats = await media.get_dashboard_stats(library.user, db)
        for category in ('missing_english', 'missing_japanese', 'missing_dual_audio', 'preferred_not_default'):
            for kind in (None, 'movie', 'tv', 'anime'):
                suffix = f"{('movies' if kind == 'movie' else kind)}_" if kind else ''
                count = getattr(stats, f'{category}_{suffix}count')
                result = await media.list_media_files(library.user, db, page=1, page_size=100, issue_category=category, media_type=kind)
                assert result.total == count
                exported = await media.export_media_files(library.user, db, format='json', issue_category=category, media_type=kind)
                assert len(json.loads(exported.body)) == count
                other = await media.list_media_files(SimpleNamespace(id=999), db, page=1, page_size=100, issue_category=category, media_type=kind)
                assert other.total == 0


@pytest.mark.parametrize('tag', [None, '', 'und', 'zx', 'not-a-language'])
def test_unknown_tags_are_reviewable_without_asserting_content(tag):
    normalized = normalize_language(tag)
    assert normalized is None
    issues = PreferenceEngine().evaluate([{'language': normalized, 'language_raw': tag}])
    assert 'No track tagged English; audio language needs review' in issues
    assert 'Unknown or unrecognized audio language metadata' in issues
    assert 'Missing English audio track' not in issues


def test_known_and_mixed_languages_remain_conservative():
    engine = PreferenceEngine()
    assert 'Missing English audio track' in engine.evaluate([{'language': 'de'}])
    assert engine.evaluate([{'language': 'en'}, {'language': None}]) == ['Unknown or unrecognized audio language metadata']
    assert normalize_language('eng') == 'en' and normalize_language('jpn') == 'ja'


@pytest.mark.asyncio
async def test_unknown_filter_note_ownership_and_rescan_persistence(library):
    write_media(library.root)
    with patch('app.core.scanner.AudioAnalyzer.analyze', return_value={'audio_tracks': [{'index': 0, 'language': None, 'language_raw': 'und'}]}):
        await run(library)
    record = (await files(library))[0]
    async with library.sessions() as db:
        result = await media.list_media_files(library.user, db, page=1, page_size=25, issue_category='unknown_language')
        assert result.total == 1
        with pytest.raises(HTTPException) as rejected:
            await media.update_language_review(record.id, LanguageReviewRequest(note='not mine'), SimpleNamespace(id=999), db)
        assert rejected.value.status_code == 404
        saved = await media.update_language_review(record.id, LanguageReviewRequest(note='I listened: spoken English.'), library.user, db)
        assert saved.audio_tracks[0].language is None  # annotation does not overwrite tags
        await db.commit()
    await run(library, incremental=False)
    assert (await files(library))[0].language_review_note == 'I listened: spoken English.'
    async with library.sessions() as db:
        cleared = await media.update_language_review(record.id, LanguageReviewRequest(note=''), library.user, db)
        assert cleared.language_review_note is None
