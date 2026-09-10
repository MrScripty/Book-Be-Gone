import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import transcriptions


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / 'abcdef012345'
        self.book.mkdir()
        (self.book / 'book.json').write_text('{}')
        self.photos = [self.book / f'{i:06d}.jpg' for i in (1, 2)]
        for photo in self.photos:
            photo.write_bytes(b'photo')
        transcriptions.save(self.photos[0], {'pages': [
            {'page_number': '44', 'chapter_seen': 'Chapter 2', 'markdown': '**Bold** [illegible]'},
            {'page_number': '45', 'chapter_seen': None, 'markdown': 'Second page'}]})
        self.patch = patch.object(app, 'DATA', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app.STATUS.update(running=False, book=None, page=None)

    def test_continuous_document_includes_printed_pages_and_unread_capture(self):
        result = app.document(self.book.name)
        self.assertEqual([p['key'] for p in result['pages']], ['000001:0', '000001:1', '000002:0'])
        self.assertEqual([p['page_number'] for p in result['pages']], ['44', '45', None])
        self.assertIn('<strong>Bold</strong>', result['pages'][0]['html'])
        self.assertFalse(result['pages'][2]['has_text'])

    def test_edit_completed_page_while_another_capture_is_running(self):
        app.STATUS.update(running=True, book=self.book.name, page='000002')
        app.save_correction(self.book.name, {'page': '000001', 'printed_index': 0,
            'revision': transcriptions.revision(self.photos[0]), 'markdown': '**Bold** restored', 'page_number': '44'})
        pages = transcriptions.read(self.photos[0])['pages']
        self.assertEqual(pages[0]['markdown'], '**Bold** restored\n')
        self.assertEqual(pages[1]['markdown'], 'Second page\n')

    def test_active_capture_is_protected(self):
        app.STATUS.update(running=True, book=self.book.name, page='000001')
        with self.assertRaisesRegex(ValueError, 'queued or being transcribed'):
            app.save_correction(self.book.name, {'page': '000001', 'printed_index': 0, 'markdown': 'bad'})

    def test_stale_editor_cannot_overwrite_newer_corrections(self):
        old = transcriptions.revision(self.photos[0])
        record = transcriptions.read(self.photos[0])
        record['pages'][0]['markdown'] = 'Newer correction'
        transcriptions.save(self.photos[0], record)
        with self.assertRaisesRegex(ValueError, 'changed since'):
            app.save_correction(self.book.name, {'page': '000001', 'printed_index': 0,
                'revision': old, 'markdown': 'Stale editor text', 'page_number': '44'})
        self.assertEqual(transcriptions.read(self.photos[0])['pages'][0]['markdown'], 'Newer correction\n')

    def test_status_advertises_streaming_contract(self):
        snapshot = app.status_snapshot()
        self.assertEqual(snapshot['api_version'], 14)
        self.assertIn('live_pages', snapshot)

    def test_selected_model_reaches_ocr_and_preserves_completed_capture(self):
        result = {'pages': [{'page_number': '46', 'chapter_seen': None, 'markdown': 'New text'}]}
        before = transcriptions.read(self.photos[0])
        with patch.object(app.codex_stream, 'run', return_value=result) as run:
            app.transcribe(self.book.name, model='gpt-5.6-sol', effort='high')
        self.assertIsNone(app.STATUS['error'])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs['effort'], 'high')
        self.assertEqual(run.call_args.args[1], 'gpt-5.6-sol')
        self.assertEqual(app.STATUS['model'], 'gpt-5.6-sol')
        self.assertEqual(transcriptions.read(self.photos[0]), before)

    def test_model_catalog_filters_text_only_and_hidden_models(self):
        cache = self.root / 'models_cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': 'vision-model', 'visibility': 'list', 'input_modalities': ['image']},
            {'slug': 'text-model', 'visibility': 'list', 'input_modalities': ['text']},
            {'slug': 'hidden-model', 'visibility': 'hide', 'input_modalities': ['image']}]}))
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root)}):
            self.assertEqual([m['id'] for m in app.model_options()['models']], [app.MODEL, 'vision-model'])
            cache.write_text('invalid json')
            self.assertEqual(app.model_options()['default'], app.MODEL)

    def test_model_identifier_validation(self):
        for value in ('', None, 123, '--model', 'bad model', 'bad\nmodel'):
            with self.assertRaises(ValueError):
                app.validate_model(value)

    def test_invalid_thinking_level_is_rejected(self):
        for effort in ('med', '', None, 'invented'):
            with self.assertRaises(ValueError):
                app.validate_effort('custom-model', effort)
        with patch.object(app, 'model_options', return_value={'models': [{'id': 'limited', 'efforts': ['low']}]}):
            with self.assertRaises(ValueError):
                app.validate_effort('limited', 'high')
