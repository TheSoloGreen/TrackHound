import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api import scan


class ResolveMediaPathTests(unittest.TestCase):
    def test_accepts_media_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            target = media_root / "shows"
            target.mkdir(parents=True)

            with patch.object(scan, "MEDIA_ROOT", str(media_root)):
                resolved = scan.resolve_media_path(str(target))

            self.assertEqual(resolved, target.resolve())

    def test_rejects_media2_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            media2 = Path(tmp) / "media2"
            media_root.mkdir()
            media2.mkdir()

            with patch.object(scan, "MEDIA_ROOT", str(media_root)):
                with self.assertRaises(HTTPException) as ctx:
                    scan.resolve_media_path(str(media2))

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(ctx.exception.detail, "Path must be under /media/")

    def test_rejects_relative_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            media_root.mkdir()

            with patch.object(scan, "MEDIA_ROOT", str(media_root)):
                with self.assertRaises(HTTPException) as ctx:
                    scan.resolve_media_path("../media/shows")

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(ctx.exception.detail, "Path must be absolute")

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_root = Path(tmp) / "media"
            outside = Path(tmp) / "outside"
            media_root.mkdir()
            outside.mkdir()

            link = media_root / "linked-outside"
            link.symlink_to(outside, target_is_directory=True)

            with patch.object(scan, "MEDIA_ROOT", str(media_root)):
                with self.assertRaises(HTTPException) as ctx:
                    scan.resolve_media_path(str(link))

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(ctx.exception.detail, "Path must be under /media/")


if __name__ == "__main__":
    unittest.main()
