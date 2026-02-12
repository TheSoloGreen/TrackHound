from datetime import datetime, timezone
import asyncio
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.media import get_dashboard_stats
from app.core.encryption import encrypt_value
from app.models.entities import Base, MediaFile, ScanLocation, Show, User


def _run(coro):
    return asyncio.run(coro)


async def _build_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    return engine, session


def test_dashboard_stats_issue_counters_and_last_scan_from_locations():
    async def _test():
        engine, session = await _build_session()
        try:
            owner = User(
                plex_user_id="u1",
                plex_username="tester",
                plex_token=encrypt_value("token"),
            )
            session.add(owner)
            await session.flush()

            shows = [
                Show(user_id=owner.id, title="Movie A", media_type="movie", is_anime=False),
                Show(user_id=owner.id, title="TV A", media_type="tv", is_anime=False),
                Show(user_id=owner.id, title="Anime A", media_type="anime", is_anime=True),
            ]
            session.add_all(shows)
            await session.flush()

            media_files = [
                MediaFile(
                    user_id=owner.id,
                    show_id=shows[1].id,
                    file_path="/tmp/a1.mkv",
                    filename="a1.mkv",
                    file_size=10,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing English audio track",
                ),
                MediaFile(
                    user_id=owner.id,
                    show_id=shows[2].id,
                    file_path="/tmp/a2.mkv",
                    filename="a2.mkv",
                    file_size=11,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 3, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing Japanese audio track (anime)",
                ),
                MediaFile(
                    user_id=owner.id,
                    show_id=shows[0].id,
                    file_path="/tmp/a3.mkv",
                    filename="a3.mkv",
                    file_size=12,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 4, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing English audio for dual audio (anime)",
                ),
                MediaFile(
                    user_id=owner.id,
                    show_id=shows[2].id,
                    file_path="/tmp/a4.mkv",
                    filename="a4.mkv",
                    file_size=13,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 5, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing Japanese audio for dual audio (anime)",
                ),
                MediaFile(
                    user_id=owner.id,
                    show_id=shows[2].id,
                    file_path="/tmp/a5.mkv",
                    filename="a5.mkv",
                    file_size=14,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 6, tzinfo=timezone.utc),
                    has_issues=True,
                    issue_details="Missing dual audio (English + Japanese) for anime",
                ),
                MediaFile(
                    user_id=owner.id,
                    show_id=shows[1].id,
                    file_path="/tmp/a6.mkv",
                    filename="a6.mkv",
                    file_size=15,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 1, 7, tzinfo=timezone.utc),
                    has_issues=False,
                    issue_details=None,
                ),
            ]
            session.add_all(media_files)

            session.add_all(
                [
                    ScanLocation(
                        user_id=owner.id,
                        path="/media/a",
                        label="A",
                        media_type="tv",
                        last_scanned=datetime(2024, 2, 1, tzinfo=timezone.utc),
                    ),
                    ScanLocation(
                        user_id=owner.id,
                        path="/media/b",
                        label="B",
                        media_type="anime",
                        last_scanned=datetime(2024, 2, 5, tzinfo=timezone.utc),
                    ),
                ]
            )
            await session.commit()

            stats = await get_dashboard_stats(current_user=owner, db=session)

            assert stats.total_titles == 3
            assert stats.total_files == 6
            assert stats.total_files_with_issues == 5
            assert stats.movie_count == 1
            assert stats.tv_count == 1
            assert stats.anime_count == 1
            assert stats.missing_english_count == 2
            assert stats.missing_japanese_count == 2
            assert stats.missing_dual_audio_count == 3
            assert stats.missing_english_movies_count == 1
            assert stats.missing_english_tv_count == 1
            assert stats.missing_english_anime_count == 0
            assert stats.missing_japanese_movies_count == 0
            assert stats.missing_japanese_tv_count == 0
            assert stats.missing_japanese_anime_count == 2
            assert stats.missing_dual_audio_movies_count == 1
            assert stats.missing_dual_audio_tv_count == 0
            assert stats.missing_dual_audio_anime_count == 2
            assert stats.last_scan == datetime(2024, 2, 5)
        finally:
            await session.close()
            await engine.dispose()

    _run(_test())


def test_dashboard_stats_last_scan_falls_back_to_media_files():
    async def _test():
        engine, session = await _build_session()
        try:
            owner = User(
                plex_user_id="u2",
                plex_username="tester2",
                plex_token=encrypt_value("token"),
            )
            session.add(owner)
            await session.flush()

            session.add(
                MediaFile(
                    user_id=owner.id,
                    file_path="/tmp/b1.mkv",
                    filename="b1.mkv",
                    file_size=20,
                    last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_scanned=datetime(2024, 3, 10, tzinfo=timezone.utc),
                    has_issues=False,
                    issue_details=None,
                )
            )
            await session.commit()

            stats = await get_dashboard_stats(current_user=owner, db=session)

            assert stats.last_scan == datetime(2024, 3, 10)
            assert stats.total_files == 1
            assert stats.missing_english_movies_count == 0
            assert stats.missing_japanese_tv_count == 0
            assert stats.missing_dual_audio_anime_count == 0
        finally:
            await session.close()
            await engine.dispose()

    _run(_test())
