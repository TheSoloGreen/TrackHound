"""CI-only stable-release validation and digest-preserving image promotion.

This module uses the standard library and does not import application settings.
It never builds an image or overwrites a different existing version tag.
"""

import argparse
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = "ghcr.io/thesologreen/trackhound"
PACKAGE = "thesologreen/trackhound"
SEMVER = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def release_section(root, version):
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## " + re.escape(version) + r"(?:[ \t]+[^\n]*)?\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or not match[1].strip():
        raise ValueError(f"CHANGELOG.md must contain release notes for {version}")
    return match[1].strip()


def validate_versions(root, tag=None):
    tree = ast.parse((root / "backend/app/version.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets))
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    if not re.fullmatch(SEMVER, version):
        raise ValueError("App version must be a stable major.minor.patch version")
    if {version, package["version"], lock["version"], lock["packages"][""]["version"]} != {version}:
        raise ValueError("Backend, frontend, and lockfile versions must match")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Release tag must be v{version}")
    release_section(root, version)
    return version


class Registry:
    def __init__(self):
        headers = {}
        if os.environ.get("GITHUB_TOKEN"):
            credentials = f"{os.environ['GITHUB_ACTOR']}:{os.environ['GITHUB_TOKEN']}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode()
        query = urlencode({"service": "ghcr.io", "scope": f"repository:{PACKAGE}:pull"})
        token, _ = self.request(f"https://ghcr.io/token?{query}", headers)
        self.headers = {"Authorization": "Bearer " + token["token"],
            "Accept": ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v2+json"))}

    @staticmethod
    def request(url, headers, missing_ok=False):
        try:
            with urlopen(Request(url, headers=headers), timeout=20) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("Registry metadata exceeds the size limit")
                digest = response.headers.get("Docker-Content-Digest") or "sha256:" + hashlib.sha256(raw).hexdigest()
                return json.loads(raw), digest
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if missing_ok and status == 404:
                return None, None
            raise ValueError(f"Registry metadata request failed (HTTP {status})") from None

    def manifest(self, reference, missing_ok=False):
        return self.request(f"https://ghcr.io/v2/{PACKAGE}/manifests/{reference}", self.headers, missing_ok)

    def config(self, digest):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise ValueError("Invalid image config digest")
        return self.request(f"https://ghcr.io/v2/{PACKAGE}/blobs/{digest}", self.headers)[0]


def verified_source(registry, revision):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("A full Git commit revision is required")
    index, digest = registry.manifest(f"sha-{revision[:7]}")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Invalid source image digest")
    images = [index]
    if "manifests" in index:
        descriptors = [item for item in index["manifests"] if item.get("platform", {}).get("os") == "linux"]
        if not descriptors:
            raise ValueError("No Linux image found in source index")
        images = [registry.manifest(item["digest"])[0] for item in descriptors]
    for image in images:
        config = registry.config(image["config"]["digest"])
        if config["config"]["Labels"].get("org.opencontainers.image.revision") != revision:
            raise ValueError("Source image revision does not match the tagged commit")
    return digest


def promote(registry, version, revision, run=subprocess.run):
    source = verified_source(registry, revision)
    _, existing = registry.manifest(version, missing_ok=True)
    if existing and existing != source:
        raise ValueError(f"Refusing to overwrite existing immutable version {version}")
    if not existing:
        run(["docker", "buildx", "imagetools", "create", "--prefer-index=false", "--tag",
             f"{REPOSITORY}:{version}", f"{REPOSITORY}@{source}"], check=True)
    _, published = registry.manifest(version)
    if published != source:
        raise ValueError("Promoted release digest does not match the tested source image")
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("metadata", "check-source", "promote"))
    parser.add_argument("--tag")
    parser.add_argument("--revision")
    parser.add_argument("--notes")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    version = validate_versions(root, args.tag)
    if args.command == "metadata":
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                stream.write(f"version={version}\nrevision={revision}\n")
        print(f"Validated version {version}, revision {revision}")
    elif args.command == "check-source":
        print(f"Verified source {REPOSITORY}@{verified_source(Registry(), args.revision or '')}")
    else:
        if args.tag != f"v{version}" or not args.notes:
            raise ValueError("Promotion requires the matching release tag and a notes output path")
        digest = promote(Registry(), version, args.revision or "")
        notes = release_section(root, version)
        Path(args.notes).write_text(f"{notes}\n\nImage: `{REPOSITORY}:{version}`\n\n"
            f"Pinned digest: `{REPOSITORY}@{digest}`\n\nRevision: `{args.revision}`\n", encoding="utf-8")
        print(f"Verified release {version}: {digest}")


if __name__ == "__main__":
    main()
