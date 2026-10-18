"""Release gates and immutable digest promotion without real registry writes."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.release import promote, release_section, validate_versions, verified_source

REVISION = "1" * 40
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def release_root(tmp_path):
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend/app/version.py").write_text('VERSION = "0.5.0"\n', encoding="utf-8")
    (tmp_path / "frontend/package.json").write_text(json.dumps({"version": "0.5.0"}), encoding="utf-8")
    (tmp_path / "frontend/package-lock.json").write_text(json.dumps({"version": "0.5.0", "packages": {"": {"version": "0.5.0"}}}), encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.5.0\nFresh policy rules.\n\n## 0.4.0\nOld jobs.\n", encoding="utf-8")
    return tmp_path


def test_versions_and_tag_must_match_all_three_sources(release_root):
    assert validate_versions(release_root, "v0.5.0") == "0.5.0"
    assert release_section(release_root, "0.5.0") == "Fresh policy rules."
    with pytest.raises(ValueError, match="tag must"):
        validate_versions(release_root, "v0.5.1")
    (release_root / "frontend/package.json").write_text('{"version":"0.4.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="versions must match"):
        validate_versions(release_root)


def test_release_requires_a_changelog_section(release_root):
    (release_root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    with pytest.raises(ValueError, match="release notes"):
        validate_versions(release_root)


class FakeRegistry:
    def __init__(self):
        self.existing = None
        self.revision = REVISION

    def manifest(self, reference, missing_ok=False):
        if reference == "sha-" + REVISION[:7]:
            return {"manifests": [{"digest": "sha256:" + "b" * 64, "platform": {"os": "linux", "architecture": "amd64"}}]}, DIGEST
        if reference == "sha256:" + "b" * 64:
            return {"config": {"digest": "sha256:" + "c" * 64}}, "sha256:" + "b" * 64
        assert reference == "0.5.0"
        return {}, self.existing

    def config(self, digest):
        return {"config": {"Labels": {"org.opencontainers.image.revision": self.revision}}}


def test_promotes_the_tested_digest_without_rebuilding():
    registry = FakeRegistry()

    def publish(command, **kwargs):
        assert command[:4] == ["docker", "buildx", "imagetools", "create"]
        assert command[-1] == "ghcr.io/thesologreen/trackhound@" + DIGEST
        assert "ghcr.io/thesologreen/trackhound:0.5.0" in command
        assert "latest" not in " ".join(command)
        registry.existing = DIGEST
    run = Mock(side_effect=publish)
    assert promote(registry, "0.5.0", REVISION, run) == DIGEST
    run.assert_called_once()
    assert promote(registry, "0.5.0", REVISION, run) == DIGEST
    run.assert_called_once()  # Idempotent rerun; not even a redundant write.


def test_refuses_to_overwrite_a_different_version_digest():
    registry = FakeRegistry()
    registry.existing = "sha256:" + "d" * 64
    run = Mock()
    with pytest.raises(ValueError, match="overwrite"):
        promote(registry, "0.5.0", REVISION, run)
    run.assert_not_called()


def test_rejects_wrong_source_revision_before_any_registry_write():
    registry = FakeRegistry()
    registry.revision = "2" * 40
    run = Mock()
    with pytest.raises(ValueError, match="revision does not match"):
        promote(registry, "0.5.0", REVISION, run)
    run.assert_not_called()
    with pytest.raises(ValueError, match="full Git"):
        verified_source(registry, REVISION[:7])


def test_detects_a_bad_promotion_digest():
    with pytest.raises(ValueError, match="Promoted release digest"):
        promote(FakeRegistry(), "0.5.0", REVISION, Mock())


def test_repo_versions_and_current_release_notes_are_aligned():
    assert validate_versions(Path(__file__).resolve().parents[2]) == "0.5.0"
