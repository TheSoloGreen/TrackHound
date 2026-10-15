"""Audio-policy regressions: structured findings, exact edits, and removal review."""

import json
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import media
from app.config import get_settings
from app.core import media_access
from app.core.audio_fixer import AudioTrackRemovalResult, build_keep_audio_track_indices
from app.core.audio_roles import audio_role, select_main_track
from app.core.preference_engine import AudioPreferences, PreferenceEngine
from app.core.scanner import MediaScanner
from app.models.entities import MediaFile, Show, UserPreference
from app.models.schemas import AudioTrackRemovalRequest, UpdateDefaultAudioRequest
from test_media_edit_safety import scanned_file
from test_scanner_run_scan import library, run, write_media, files


@pytest.mark.parametrize("tracks, code", [
    ([{"language": "en"}], "NO_DEFAULT"),
    ([{"language": "en", "is_default": True}, {"language": "en", "is_default": True}], "MULTIPLE_DEFAULTS"),
    ([{"language": "en", "title": "Director Commentary", "is_default": True}], "SPECIAL_DEFAULT"),
    ([{"language": "en", "title": "Audio Description", "is_default": True}], "SPECIAL_DEFAULT"),
])
def test_default_and_main_audio_issues_are_consistent(tracks, code):
    engine = PreferenceEngine(AudioPreferences(preferred_codecs=["AAC"]))
    detailed = engine.evaluate_detailed(tracks)
    assert code in {issue.code for issue in detailed}
    assert "NO_PREFERRED_CODEC" in {issue.code for issue in detailed}
    assert engine.evaluate(tracks) == [issue.message for issue in detailed]
    assert engine.get_summary(tracks)["issue_count"] == len(detailed)


def test_special_tracks_never_satisfy_main_audio_or_automatic_selection():
    tracks = [{"index": 0, "language": "en", "title": "Commentary", "is_default": True},
              {"index": 1, "language": "en", "title": "Audio description"},
              {"index": 2, "language": "en", "channels": 2},
              {"index": 3, "language": "en", "channels": 6}]
    assert select_main_track(tracks, "en") == 3
    assert MediaScanner()._get_english_default_fix_index(tracks) == 3
    assert select_main_track(tracks[:2], "en") is None
    issues = PreferenceEngine().evaluate_detailed(tracks[:2])
    assert "MISSING_ENGLISH" in {issue.code for issue in issues}
    assert audio_role({"title": "Director's Cut"}) == "main"
    assert build_keep_audio_track_indices([{"index": 4, "language_raw": "not-a-language"}]) == [4]
    assert "No track tagged English; audio language needs review" in PreferenceEngine().evaluate([
        {"index": 0, "language": None, "title": "Commentary", "is_default": True}])


def editable(monkeypatch, source):
    monkeypatch.setattr(get_settings(), "media_writes_enabled", True)
    monkeypatch.setattr(media_access, "MEDIA_ROOT", source.parent)
    monkeypatch.setattr(media_access.shutil, "which", lambda _: "/tool")


@pytest.mark.asyncio
async def test_exact_default_selection_is_current_and_verified(scanned_file, monkeypatch):
    db, user, mf, source = scanned_file
    editable(monkeypatch, source)
    with patch.object(media, "set_default_track_by_index", return_value=True) as edit:
        with pytest.raises(HTTPException) as stale:
            await media.update_media_file_default_audio(mf.id, UpdateDefaultAudioRequest(track_index=1), user, db)
        assert stale.value.status_code == 409
        edit.assert_not_called()
        tracks = [{"index": 0, "language": "en"}, {"index": 1, "language": "ja", "is_default": True}]
        with patch.object(media.AudioAnalyzer, "analyze", return_value={"audio_tracks": tracks}):
            result = await media.update_media_file_default_audio(mf.id, UpdateDefaultAudioRequest(
                track_index=1, expected_last_scanned=mf.last_scanned), user, db)
        assert edit.call_args.args[-1] == 1
        assert [track.track_index for track in result.media_file.audio_tracks if track.is_default] == [1]


@pytest.mark.asyncio
async def test_default_success_requires_refreshed_selected_flags(scanned_file, monkeypatch):
    db, user, mf, source = scanned_file
    editable(monkeypatch, source)
    with patch.object(media, "set_default_track_by_index", return_value=True), patch.object(media.AudioAnalyzer, "analyze",
        return_value={"audio_tracks": [{"index": 0, "language": "en", "is_default": True}]}):
        with pytest.raises(HTTPException) as failure:
            await media.update_media_file_default_audio(mf.id, UpdateDefaultAudioRequest(
                track_index=1, expected_last_scanned=mf.last_scanned), user, db)
    assert failure.value.status_code == 409
    assert "did not confirm" in failure.value.detail


@pytest.mark.asyncio
async def test_anime_removal_plan_requires_review_to_remove_japanese(scanned_file, monkeypatch):
    db, user, mf, source = scanned_file
    editable(monkeypatch, source)
    show = Show(user_id=user.id, title="Anime", is_anime=True, media_type="anime")
    db.add(show)
    await db.flush()
    mf.show = show
    await db.flush()
    default = await media.plan_media_file_audio_tracks(mf.id, user, db)
    assert default.keep_track_indices == [0, 1, 2]
    assert default.required_languages == ["en", "ja"]
    plan = await media.plan_media_file_audio_tracks(mf.id, user, db, keep_track_indices=[0, 2])
    assert any("Japanese" in warning for warning in plan.warnings)
    request = dict(keep_track_indices=[0, 2], expected_last_scanned=mf.last_scanned, expected_policy_revision=plan.policy_revision)
    with patch.object(media, "remove_unwanted_audio_tracks") as remove:
        with pytest.raises(HTTPException) as rejected:
            await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(**request), user, db)
        assert rejected.value.status_code == 409
        remove.assert_not_called()
    refreshed = {"audio_tracks": [{"index": 0, "language": "en", "is_default": True}, {"index": 1, "language_raw": "und"}]}
    with patch.object(media, "remove_unwanted_audio_tracks", return_value=AudioTrackRemovalResult([0, 2], [1], str(source)+".bak")), \
         patch.object(media.AudioAnalyzer, "analyze", return_value=refreshed):
        result = await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(
            **request, acknowledge_policy_warnings=True), user, db)
    assert "MISSING_JAPANESE" in {issue.code for issue in result.media_file.issues}
    assert result.removed_track_indices == [1]


@pytest.mark.asyncio
async def test_changed_preferences_invalidate_an_acknowledged_removal_plan(scanned_file, monkeypatch):
    db, user, mf, source = scanned_file
    editable(monkeypatch, source)
    plan = await media.plan_media_file_audio_tracks(mf.id, user, db, keep_track_indices=[1])
    db.add(UserPreference(user_id=user.id, key="audio_preferences", value='{"preferred_codecs":["AAC"]}'))
    await db.flush()
    with patch.object(media, "remove_unwanted_audio_tracks") as remove:
        with pytest.raises(HTTPException) as stale:
            await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(keep_track_indices=[1],
                expected_last_scanned=mf.last_scanned, expected_policy_revision=plan.policy_revision,
                acknowledge_policy_warnings=True), user, db)
        assert stale.value.status_code == 409
        assert "preferences changed" in stale.value.detail
        remove.assert_not_called()


@pytest.mark.asyncio
async def test_structured_codes_drive_dashboard_list_and_export_after_wording_changes(library):
    write_media(library.root)
    with patch('app.core.scanner.AudioAnalyzer.analyze', return_value={"audio_tracks": [{"index": 0, "language": "en"}]}):
        await run(library)
    record = (await files(library))[0]
    async with library.sessions() as db:
        mf = await db.get(MediaFile, record.id)
        assert {issue.code for issue in mf.issue_records} == {"NO_DEFAULT"}
        mf.issue_details = "Changed display wording"
        await db.commit()
        stats = await media.get_dashboard_stats(library.user, db)
        listed = await media.list_media_files(library.user, db, page=1, page_size=25, issue_category="preferred_not_default")
        exported = await media.export_media_files(library.user, db, format="json", issue_category="preferred_not_default")
        assert stats.preferred_not_default_count == listed.total == len(json.loads(exported.body)) == 1
        assert json.loads(exported.body)[0]["issue_codes"] == "NO_DEFAULT"
        other = await media.list_media_files(NS(id=999), db, page=1, page_size=25, issue_category="preferred_not_default")
        assert other.total == 0
