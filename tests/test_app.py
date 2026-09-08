import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import transcriptions


def ocr_result(text, number="12", chapter="Chapter 1"):
    return json.dumps({"pages": [{"page_number": number, "chapter_seen": chapter, "markdown": text}]})


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = patch.object(app, "DATA", Path(self.temp.name))
        self.data.start()
        self.addCleanup(self.data.stop)
        self.book = "abcdef012345"
        self.path = app.DATA / self.book
        self.path.mkdir()
        (self.path / "book.json").write_text(json.dumps({"title": "Example"}))
        for page in ["000002", "000001"]:
            (self.path / (page + ".jpg")).write_bytes(b"photo")
        app.STATUS.update(running=True, error=None)

    def test_order_and_pending(self):
        (self.path / "000002.md").write_text("Existing correction")
        self.assertEqual(app.pages(self.book), [
            {"id": "000001", "done": False}, {"id": "000002", "done": True}])

    def test_reject_traversal(self):
        with self.assertRaises(ValueError):
            app.book_path("../outside")
        with self.assertRaises(ValueError):
            app.page_path(self.book, "../../photo")

    def test_adjustment_preserves_original_and_invalidates_ocr(self):
        app.STATUS["running"] = False
        original = self.path / "000001.jpg"
        original.with_suffix(".md").write_text("Previous transcription")
        adjusted = b"\xff\xd8\xffadjusted\xff\xd9"
        app.adjust_photo(self.book, "000001", base64.b64encode(adjusted).decode())
        self.assertEqual(original.read_bytes(), b"photo")
        self.assertEqual(app.ocr_photo(original).read_bytes(), adjusted)
        self.assertFalse(app.pages(self.book)[0]["done"])
        self.assertEqual(original.with_suffix(".md").read_text(), "Previous transcription")
        self.assertEqual(len(app.pages(self.book)), 2)
        app.adjust_photo(self.book, "000001")
        self.assertEqual(app.ocr_photo(original), original)
        self.assertFalse(app.pages(self.book)[0]["done"])

    def test_adjustment_blocked_during_ocr(self):
        with self.assertRaisesRegex(ValueError, "Wait for OCR"):
            app.adjust_photo(self.book, "000001")

    def test_capture_saves_original_and_corrected_together(self):
        original = b"\xff\xd8\xfforiginal\xff\xd9"
        corrected = b"\xff\xd8\xffstraightened\xff\xd9"
        page = app.capture_photo(self.book, base64.b64encode(original).decode(),
                                 base64.b64encode(corrected).decode())
        photo = app.page_path(self.book, page)
        self.assertEqual(photo.read_bytes(), original)
        self.assertEqual(app.ocr_photo(photo).read_bytes(), corrected)
        self.assertEqual(app.pages(self.book)[-1], {"id": "000003", "done": False})

    def test_capture_rejects_invalid_correction_without_saving_page(self):
        with self.assertRaises(ValueError):
            app.capture_photo(self.book, base64.b64encode(b"\xff\xd8\xfforiginal\xff\xd9").decode(),
                              base64.b64encode(b"invalid").decode())
        self.assertEqual(len(app.pages(self.book)), 2)

    def test_capture_without_crop_uses_original(self):
        page = app.capture_photo(self.book, base64.b64encode(b"\xff\xd8\xfforiginal\xff\xd9").decode())
        photo = app.page_path(self.book, page)
        self.assertEqual(app.ocr_photo(photo), photo)

    @patch("app.codex_stream.run")
    def test_ocr_uses_adjustment_and_clears_stale_flag(self, run):
        app.STATUS["running"] = False
        app.adjust_photo(self.book, "000001", base64.b64encode(b"\xff\xd8\xfftest\xff\xd9").decode())
        def fake(image, model, prompt, schema, cwd, update, **kwargs):
            self.assertEqual(image, self.path / "corrected" / "000001.jpg")
            return json.loads(ocr_result("New transcription"))
        run.side_effect = fake
        app.transcribe(self.book, "000001")
        self.assertIsNone(app.STATUS["error"])
        self.assertTrue(app.pages(self.book)[0]["done"])

    @patch("app.codex_stream.run")
    def test_ocr_skips_completed_and_uses_requested_model(self, run):
        (self.path / "000002.md").write_text("Existing correction")
        def fake(image, model, prompt, schema, cwd, update, **kwargs):
            self.assertEqual(model, app.MODEL)
            self.assertEqual(image, self.path / "000001.jpg")
            return json.loads(ocr_result("# Transcribed\n"))
        run.side_effect = fake
        app.transcribe(self.book)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(transcriptions.combined(self.path / "000001.jpg"), "# Transcribed\n")
        self.assertEqual((self.path / "000002.md").read_text(), "Existing correction")
        self.assertIsNone(app.STATUS["error"])
        self.assertFalse(app.STATUS["running"])

    @patch("app.codex_stream.run")
    def test_failed_retry_preserves_corrections(self, run):
        (self.path / "000001.md").write_text("Keep this")
        run.side_effect = app.codex_stream.CodexError("Unavailable")
        app.transcribe(self.book, "000001")
        self.assertEqual((self.path / "000001.md").read_text(), "Keep this")
        self.assertIn("Unavailable", app.STATUS["error"])
        self.assertFalse(app.STATUS["running"])


if __name__ == "__main__":
    unittest.main()
