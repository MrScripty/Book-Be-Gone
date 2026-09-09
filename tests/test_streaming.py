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
import diagnose_ocr
import transcriptions


def result(number='44'):
    return {'pages': [{'page_number': number, 'chapter_seen': 'Chapter 2', 'markdown': '# Text\n\nFragment'}]}


class StreamTests(unittest.TestCase):
    def run_fixture(self, mode, updates, timeout=5, **options):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = real_popen([sys.executable, '-u', str(Path(__file__).with_name('fake_codex_server.py'))], **kwargs)
            children.append(child)
            return child
        try:
            with tempfile.TemporaryDirectory() as cwd, patch('codex_stream.subprocess.Popen', side_effect=launch):
                return codex_stream.run(Path(cwd) / 'photo.jpg', mode, 'PRIVATE PROMPT', {}, cwd,
                                        lambda phase, raw: updates.append((phase, raw)), timeout=timeout, **options)
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

    def test_diagnostic_hook_observes_protocol_without_changing_result(self):
        events = []
        result = self.run_fixture('normal', [], on_event=lambda event: events.append(diagnose_ocr.event_summary(event)))
        self.assertEqual(result['pages'][0]['page_number'], '44')
        self.assertTrue(any(e.get('delta_chars') for e in events))
        self.assertTrue(any(e.get('turn_status') == 'completed' for e in events))
        self.assertNotIn('PRIVATE REASONING', str(events))
        self.assertNotIn('Sentence fragment', str(events))

    def test_diagnostics_preserve_retry_errors_and_redact_credentials(self):
        event = {'method': 'error', 'params': {'willRetry': True, 'error': {
            'message': 'Stream failed; Bearer secret https://example.com/?token=hidden',
            'codexErrorInfo': {'responseStreamDisconnected': {'httpStatusCode': 503}}}}}
        summary = diagnose_ocr.event_summary(event)
        self.assertTrue(summary['will_retry'])
        self.assertIn('503', summary['error']['codexErrorInfo'])
        self.assertNotIn('secret', str(summary))
        self.assertNotIn('hidden', str(summary))

    def test_replacement_does_not_clear_live_transcript(self):
        updates = []
        output = self.run_fixture('replacement', updates)
        previews = [codex_stream.partial_pages(raw) for _, raw in updates if raw is not None]
        texts = [''.join(p['markdown'] for p in pages) for pages in previews if pages is not None]
        first = texts.index('An existing complete transcript.')
        self.assertTrue(all(texts[first:]), texts)
        self.assertEqual(texts[-1], 'Corrected.')
        self.assertEqual(output['pages'][0]['markdown'], 'Corrected.')

    def test_repeated_completed_drafts_stop_without_retry(self):
        with self.assertRaises(codex_stream.CodexError) as caught:
            self.run_fixture('repeated-drafts', [], timeout=1)
        self.assertFalse(caught.exception.retryable)
        self.assertIn('repeated the same transcription', str(caught.exception))

    def test_replacement_resumes_live_progress_before_completion(self):
        updates = []
        output = self.run_fixture('growing-replacement', updates)
        final = output['pages'][0]['markdown']
        texts = [p['markdown'] for _, raw in updates if raw
                 for p in (codex_stream.partial_pages(raw) or [])]
        self.assertTrue(any(text.startswith('A corrected') and len(text) < len(final)
                            for text in texts), texts)

    def test_unfinished_restarts_and_reasoning_do_not_extend_progress_deadline(self):
        with self.assertRaises(codex_stream.CodexError) as caught:
            self.run_fixture('partial-stall', [], timeout=2, progress_timeout=.1)
        self.assertFalse(caught.exception.retryable)
        self.assertIn('no new transcription progress', str(caught.exception))

    def test_missing_turn_completion_stops_with_explicit_waiting_phase(self):
        updates = []
        with self.assertRaises(codex_stream.CodexError):
            self.run_fixture('completion-stall', updates, timeout=2, progress_timeout=.1)
        self.assertEqual(updates[-1][0], 'Waiting for OCR to finish')

    def test_provider_content_filter_stops_even_when_codex_will_retry(self):
        updates = []
        with self.assertRaises(codex_stream.CodexError) as caught:
            self.run_fixture('content-filter', updates, timeout=1)
        self.assertFalse(caught.exception.retryable)
        self.assertIn('content filter', str(caught.exception))
        self.assertNotIn('Codex is reconnecting', [phase for phase, _ in updates])

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

    def test_stalled_redo_stops_worker_without_retry_or_overwriting_saved_text(self):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = real_popen([sys.executable, '-u', str(Path(__file__).with_name('fake_codex_server.py').resolve())], **kwargs)
            children.append(child)
            return child
        with patch('codex_stream.subprocess.Popen', side_effect=launch), \
                patch.object(app, 'OCR_PROGRESS_TIMEOUT', .1):
            app.transcribe(self.book.name, selected='000001', model='partial-stall')
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertFalse(app.STATUS['running'])
        self.assertEqual(app.STATUS['phase'], 'Stopped')
        self.assertIn('no new transcription progress', app.STATUS['error'])
        for name, content in self.original.items():
            self.assertEqual((self.book / 'markdown' / name).read_bytes(), content)

    def test_filtered_redo_preserves_saved_text_and_does_not_suggest_repeating_it(self):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = real_popen([sys.executable, '-u', str(Path(__file__).with_name('fake_codex_server.py').resolve())], **kwargs)
            children.append(child)
            return child
        with patch('codex_stream.subprocess.Popen', side_effect=launch), patch.object(app, 'OCR_PROGRESS_TIMEOUT', .1):
            app.transcribe(self.book.name, selected='000001', model='content-filter')
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertFalse(app.STATUS['running'])
        self.assertEqual(app.STATUS['phase'], 'Stopped')
        self.assertIn('content filter', app.STATUS['error'])
        self.assertNotIn('Choose OCR remaining', app.STATUS['error'])
        for name, content in self.original.items():
            self.assertEqual((self.book / 'markdown' / name).read_bytes(), content)
