import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import codex_stream
import local_ocr
import transcriptions
from fake_local_server import start, RESULT


class LocalOCRTests(unittest.TestCase):
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
        self.schema = json.loads((app.ROOT / 'prompts/ocr.schema.json').read_text())

    def run_ocr(self, provider, **options):
        updates = []
        result = local_ocr.run(self.photo, 'vision:local', 'fixture prompt', self.schema, self.url,
                               provider, lambda phase, raw: updates.append((phase, raw)), timeout=2, **options)
        return result, updates

    def test_both_protocols_stream_images_schema_and_final_result(self):
        for provider in ('ollama', 'llamacpp'):
            with self.subTest(provider=provider), patch('codex_stream.run') as cloud:
                result, updates = self.run_ocr(provider)
                self.assertEqual(result, RESULT)
                self.assertGreater(len([raw for _, raw in updates if raw]), 3)
                self.assertNotIn('PRIVATE REASONING', str(updates))
                path, payload = self.server.requests[-1]
                self.assertTrue(payload['stream'])
                self.assertEqual(payload['model'], 'vision:local')
                message = payload['messages'][0]
                if provider == 'ollama':
                    self.assertEqual(path, '/api/chat')
                    self.assertEqual(message['images'], ['Zml4dHVyZS1pbWFnZQ=='])
                    self.assertEqual(payload['format'], self.schema)
                else:
                    self.assertEqual(path, '/v1/chat/completions')
                    self.assertEqual(message['content'][1]['image_url']['url'], 'data:image/jpeg;base64,Zml4dHVyZS1pbWFnZQ==')
                    self.assertEqual(payload['response_format'], {'type': 'json_object', 'schema': self.schema})
                cloud.assert_not_called()

    def test_discovery_accepts_common_base_url_suffixes(self):
        for provider, suffix, expected in [('ollama', '/api/', 'vision:local'), ('llamacpp', '/v1/', 'vision.gguf')]:
            result = local_ocr.models(provider, self.url + suffix)
            self.assertEqual(result['models'][0]['id'], expected)

    def test_incomplete_and_invalid_results_fail_for_both_protocols(self):
        for provider in ('ollama', 'llamacpp'):
            for mode in ('disconnect', 'length', 'invalid-json', 'malformed', 'http-error'):
                with self.subTest(provider=provider, mode=mode):
                    self.server.mode = mode
                    with self.assertRaises(codex_stream.CodexError):
                        self.run_ocr(provider)

    def test_stalled_stream_closes_with_a_nonretryable_progress_error(self):
        for provider in ('ollama', 'llamacpp'):
            self.server.mode = 'stall'
            with self.assertRaises(codex_stream.CodexError) as caught:
                self.run_ocr(provider, progress_timeout=.05)
            self.assertFalse(caught.exception.retryable)
            self.assertIn('progress', str(caught.exception))

    def test_invalid_provider_url_and_missing_model_are_rejected(self):
        for url in ('file:///tmp/model', 'http://user:secret@localhost', 'http://localhost?x=1',
                    'http://localhost/#x', 'http://localhost:bad', 'http://localhost:0', 'http://local\nhost'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_ocr.validate_url('ollama', url)
        for body in ({'provider': 'unknown'}, {'provider': 'ollama', 'model': ''}):
            with self.assertRaises(ValueError):
                app.ocr_settings(body)

    def test_local_batch_saves_corrected_input_and_preserves_redo_on_failure(self):
        book = Path(self.temp.name) / 'abcdef012345'
        book.mkdir()
        (book / 'book.json').write_text('{}')
        photo = book / '000001.jpg'
        photo.write_bytes(b'original')
        (book / 'corrected').mkdir()
        (book / 'corrected/000001.jpg').write_bytes(b'fixture-image')
        with patch.object(app, 'DATA', Path(self.temp.name)), patch('codex_stream.run') as cloud:
            app.transcribe(book.name, model='vision:local', provider='ollama', server_url=self.url)
            self.assertIsNone(app.STATUS['error'])
            self.assertEqual(app.STATUS['provider'], 'ollama')
            self.assertEqual(self.server.requests[-1][1]['messages'][0]['images'], ['Zml4dHVyZS1pbWFnZQ=='])
            saved = transcriptions.read(photo)
            self.assertEqual(saved['pages'][0]['page_number'], '390')
            self.server.requests.clear()
            app.transcribe(book.name, model='vision:local', provider='ollama', server_url=self.url)
            self.assertEqual(self.server.requests, [])
            self.server.mode = 'length'
            app.transcribe(book.name, selected='000001', model='vision:local', provider='llamacpp', server_url=self.url)
            self.assertIsNotNone(app.STATUS['error'])
            self.assertFalse(app.STATUS['running'])
            self.assertEqual(transcriptions.read(photo), saved)
            cloud.assert_not_called()
