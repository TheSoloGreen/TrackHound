"""Real MKV tools are installed by CI; local environments may skip this test."""

import json
import shutil
import subprocess

import pytest

from app.core.analyzer import AudioAnalyzer, require_successful_analysis
from app.core.audio_fixer import remove_unwanted_audio_tracks, set_default_track_by_language


@pytest.mark.skipif(any(shutil.which(tool) is None for tool in ("ffmpeg", "mkvmerge", "mkvpropedit")), reason="requires ffmpeg and MKVToolNix")
def test_real_mkv_edit_retains_video_subtitles_and_original_backup(tmp_path):
    source = tmp_path / "fixture.mkv"
    subtitles = tmp_path / "subtitles.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:00,200\nTest subtitle\n", encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=16x16:rate=10:duration=0.2",
        "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
        "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-i", str(subtitles),
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-t", "0.2",
        "-c:v", "ffv1", "-c:a", "pcm_s16le", "-c:s", "srt",
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=jpn",
        "-disposition:a:0", "default", "-disposition:a:1", "0", str(source),
    ], check=True, capture_output=True, timeout=30)
    analyzer = AudioAnalyzer()
    tracks = require_successful_analysis(analyzer.analyze(str(source)))["audio_tracks"]
    assert [track["language"] for track in tracks] == ["en", "ja"]
    assert set_default_track_by_language(str(source), tracks, "ja")
    updated = require_successful_analysis(analyzer.analyze(str(source)))["audio_tracks"]
    assert [track["language"] for track in updated if track["is_default"]] == ["ja"]
    original = source.read_bytes()
    result = remove_unwanted_audio_tracks(str(source), updated, [0])
    assert source.with_suffix(".mkv.bak").read_bytes() == original
    assert result.removed_track_indices == [1]
    probe = json.loads(subprocess.run(["mkvmerge", "-J", str(source)], check=True, capture_output=True, text=True, timeout=30).stdout)
    assert [track["type"] for track in probe["tracks"]] == ["video", "audio", "subtitles"]
    assert [track["language"] for track in analyzer.analyze(str(source))["audio_tracks"]] == ["en"]
