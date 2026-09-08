import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import app
import codex_stream
import transcriptions


def result(number='44'):
    return {'pages': [{'page_number': number, 'chapter_seen': 'Chapter 2', 'markdown': '# Text\n\nFragment'}]}


class StreamTests(unittest.TestCase):
    def run_fixture(self, mode, updates, timeout=5):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = real_popen([sys.executable, '-u', str(Path(__file__).with_name('fake_codex_server.py'))], **kwargs)
            children.append(child)
            return child
        try:
            with tempfile.TemporaryDirectory() as cwd, patch('codex_stream.subprocess.Popen', side_effect=launch):
                return codex_stream.run(Path(cwd) / 'photo.jpg', mode, 'PRIVATE PROMPT', {}, cwd,
                                        lambda phase, raw: updates.append((phase, raw)), timeout=timeout)
        finally:
            self.assertTrue(all(child.poll() is not None for child in children), 'Codex child must be terminated on success and timeout')

    def test_text_arrives_incrementally_before_final_result(self):
        updates = []
        output = self.run_fixture('normal', updates)
        text = [raw for _, raw in updates if raw]
        self.assertGreater(len(text), 4)
        self.assertLess(len(text[0]), len(text[-1]))
        self.assertNotIn('PRIVATE REASONING', str(updates))
        self.assertEqual(output['pages'][0]['page_number'], '44')
        self.assertTrue(any(codex_stream.partial_pages(raw) for raw in text[:-1]))

    def test_timeout_is_bounded_and_does_not_echo_prompt(self):
        start = time.monotonic()
        with self.assertRaises(codex_stream.OCRTimeout) as caught:
            self.run_fixture('timeout', [], timeout=.1)
        self.assertLess(time.monotonic() - start, 4)
        self.assertNotIn('PRIVATE PROMPT', str(caught.exception))

    def test_disconnect_is_retryable(self):
        with self.assertRaises(codex_stream.CodexError) as caught:
            self.run_fixture('disconnect', [])
        self.assertTrue(caught.exception.retryable)

    def test_partial_json_does_not_confuse_escaped_quotes_or_fake_keys(self):
        text = json.dumps(result())
        for end in range(len(text)):
            preview = codex_stream.partial_pages(text[:end])
            if preview:
                self.assertLessEqual(len(preview), 1)
        preview = codex_stream.partial_pages('{"pages":[{"page_number":"44","markdown":"A \\"quoted\\" line\\ncontinues')
        self.assertEqual(preview[0]['markdown'], 'A "quoted" line\ncontinues')
        self.assertEqual(preview[0]['page_number'], '44')


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / 'abcdef012345'
        self.book.mkdir()
        (self.book / 'book.json').write_text('{}')
        for i in range(1, 4):
            (self.book / f'{i:06d}.jpg').write_bytes(b'photo')
        self.patch = patch.object(app, 'DATA', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        transcriptions.save(self.book / '000001.jpg', result('42'))
        self.original = {p.name: p.read_bytes() for p in (self.book / 'markdown').glob('*.md')}

    def test_timeout_retries_only_current_capture_then_resumes_remaining(self):
        calls = []
        def run(photo, model, prompt, schema, cwd, update, **kwargs):
            calls.append(photo.stem)
            update('Transcribing', '{"pages":[{"page_number":"44","markdown":"Partial')
            self.assertTrue(app.STATUS['running'])
            self.assertEqual(app.STATUS['live_pages'][0]['page_number'], '44')
            if len(calls) == 1:
                raise codex_stream.OCRTimeout('Timeout')
            return result(str(int(photo.stem) + 42))
        with patch('app.codex_stream.run', side_effect=run):
            app.transcribe(self.book.name)
        self.assertEqual(calls, ['000002', '000002', '000003'])
        self.assertIsNone(app.STATUS['error'])
        self.assertEqual(app.STATUS['remaining'], 0)
        for name, content in self.original.items():
            self.assertEqual((self.book / 'markdown' / name).read_bytes(), content)

    def test_exhausted_timeout_leaves_capture_pending_and_next_run_skips_completed(self):
        with patch('app.codex_stream.run', side_effect=codex_stream.OCRTimeout('PRIVATE PROMPT')) as run:
            app.transcribe(self.book.name)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('PRIVATE PROMPT', app.STATUS['error'])
        self.assertIn('remaining captures', app.STATUS['error'])
        self.assertEqual([p['id'] for p in app.pages(self.book.name) if p['done']], ['000001'])
        calls = []
        def success(photo, *args, **kwargs):
            calls.append(photo.stem)
            return result(photo.stem)
        with patch('app.codex_stream.run', side_effect=success):
            app.transcribe(self.book.name)
        self.assertEqual(calls, ['000002', '000003'])
        self.assertIsNone(app.STATUS['error'])
        with patch('app.codex_stream.run') as run:
            app.transcribe(self.book.name)
        run.assert_not_called()

    def test_invalid_final_output_does_not_save_streamed_draft(self):
        def invalid(photo, model, prompt, schema, cwd, update, **kwargs):
            update('Transcribing', json.dumps(result()))
            return {'pages': []}
        with patch('app.codex_stream.run', side_effect=invalid):
            app.transcribe(self.book.name)
        self.assertIsNotNone(app.STATUS['error'])
        self.assertIsNone(transcriptions.read(self.book / '000002.jpg'))
