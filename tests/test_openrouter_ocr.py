import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import codex_stream
import openrouter_ocr
import transcriptions
from fake_local_server import start, RESULT


class OpenRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.photo = Path(self.temp.name) / 'photo.jpg'
        self.photo.write_bytes(b'fixture-image')
        self.server.mode = 'normal'
        self.server.requests.clear()
        self.server.auth_headers.clear()
        self.base = patch.object(openrouter_ocr, 'BASE_URL', self.url)
        self.base.start()
        self.addCleanup(self.base.stop)
        self.schema = json.loads((app.ROOT / 'prompts/ocr.schema.json').read_text())

    def run_ocr(self):
        updates = []
        value = openrouter_ocr.run(self.photo, 'fixture/vision', 'fixture prompt', self.schema,
                                   'fixture-secret', lambda phase, raw: updates.append((phase, raw)), timeout=2)
        return value, updates

    def test_authenticated_image_schema_stream_and_heartbeats(self):
        result, updates = self.run_ocr()
        self.assertEqual(result, RESULT)
        self.assertGreater(len([raw for _, raw in updates if raw]), 3)
        path, payload = self.server.requests[-1]
        self.assertEqual(path, '/api/v1/chat/completions')
        self.assertEqual(self.server.auth_headers, ['Bearer fixture-secret'])
        self.assertEqual(payload['response_format']['json_schema'], {'name': 'ocr', 'strict': True, 'schema': self.schema})
        self.assertEqual(payload['provider'], {'require_parameters': True})
        self.assertEqual(payload['messages'][0]['content'][1]['image_url']['url'], 'data:image/jpeg;base64,Zml4dHVyZS1pbWFnZQ==')
        self.assertNotIn('PRIVATE REASONING', str(updates))
        self.assertNotIn('fixture-secret', json.dumps(payload))

    def test_model_discovery_filters_for_vision_and_structured_output(self):
        result = openrouter_ocr.models('fixture-secret')
        self.assertEqual(result, {'models': [{'id': 'fixture/vision', 'name': 'Fixture Vision'}]})
        self.assertEqual(self.server.requests, [('/api/v1/models', None)])
        self.assertEqual(self.server.auth_headers, ['Bearer fixture-secret'])

    def test_key_validation_environment_fallback_and_status_redaction(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'server-secret'}):
            self.assertEqual(openrouter_ocr.api_key(''), 'server-secret')
            self.assertEqual(openrouter_ocr.api_key('override-secret'), 'override-secret')
            snapshot = app.status_snapshot()
            self.assertTrue(snapshot['openrouter_key_configured'])
            self.assertNotIn('server-secret', json.dumps(snapshot))
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            for key in ('', None, 'bad\nheader', 'bad key', 123):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    openrouter_ocr.api_key(key)

    def test_http_failures_are_actionable_and_do_not_leak_credentials(self):
        for mode, text in [('unauthorized', 'API key'), ('credits', 'credit'), ('rate-limit', 'Rate limit'), ('redirect', '302')]:
            with self.subTest(mode=mode):
                self.server.mode = mode
                before = len(self.server.requests)
                with self.assertRaises(codex_stream.CodexError) as caught:
                    self.run_ocr()
                self.assertIn(text, str(caught.exception))
                self.assertNotIn('fixture-secret', str(caught.exception))
                self.assertFalse(caught.exception.retryable)
                self.assertEqual(len(self.server.requests), before + 1)

    def test_stream_errors_truncation_and_filter_never_return_partial_result(self):
        for mode in ('stream-error', 'content-filter', 'length', 'disconnect', 'invalid-json'):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(codex_stream.CodexError) as caught:
                    self.run_ocr()
                self.assertNotIn('DO_NOT_ECHO_PROVIDER_BODY', str(caught.exception))
                if mode == 'content-filter':
                    self.assertIsInstance(caught.exception, codex_stream.OCRContentFilterError)

    def test_failed_redo_keeps_saved_text_and_does_not_fall_back(self):
        book = Path(self.temp.name) / 'abcdef012345'
        book.mkdir()
        (book / 'book.json').write_text('{}')
        photo = book / '000001.jpg'
        photo.write_bytes(b'fixture-image')
        transcriptions.save(photo, RESULT)
        saved = transcriptions.read(photo)
        self.server.mode = 'unauthorized'
        with patch.object(app, 'DATA', Path(self.temp.name)), patch('codex_stream.run') as codex, patch('local_ocr.run') as local:
            app.transcribe(book.name, selected='000001', model='fixture/vision', provider='openrouter', openrouter_key='fixture-secret')
            self.assertFalse(app.STATUS['running'])
            self.assertIn('API key', app.STATUS['error'])
            self.assertNotIn('fixture-secret', json.dumps(app.status_snapshot()))
            self.assertEqual(transcriptions.read(photo), saved)
            self.assertEqual(len(self.server.requests), 1)
            codex.assert_not_called()
            local.assert_not_called()

    def test_browser_server_url_cannot_change_openrouter_destination(self):
        settings = app.ocr_settings({'provider': 'openrouter', 'model': 'fixture/vision', 'server_url': 'http://untrusted.invalid'})
        self.assertEqual(settings, ('openrouter', 'fixture/vision', None, None))
