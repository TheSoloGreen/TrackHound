"""Exact removal warnings and a revision for the policy the user reviewed."""

from dataclasses import asdict
import hashlib
import json

from app.core.preference_engine import EVALUATION_VERSION


def policy_revision(engine, keep_languages, is_anime):
    policy = {"preferences": asdict(engine.preferences), "keep_languages": sorted(keep_languages),
              "is_anime": is_anime, "evaluation_version": EVALUATION_VERSION}
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def removal_warnings(engine, tracks, keep_indices, is_anime):
    original = {issue.code for issue in engine.evaluate_detailed(tracks, is_anime)}
    retained = [track for track in tracks if track["index"] in keep_indices]
    return [issue.message for issue in engine.evaluate_detailed(retained, is_anime) if issue.code not in original]
