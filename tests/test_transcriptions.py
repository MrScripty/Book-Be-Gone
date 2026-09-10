import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import transcriptions as store


def result(*pages):
    return {'pages': [{'page_number': number, 'chapter_seen': chapter, 'markdown': text}
                      for number, chapter, text in pages]}


class TranscriptionTests(unittest.TestCase):
    def test_page_labels_allow_only_ascii_letters_and_digits(self):
        for number in ('390', 'xiv', 'A12', ' 390 ', '', None):
            with self.subTest(number=number):
                page = store.validate(result((number, 'Chapter — Title', 'Text')), recover_numbers=False)['pages'][0]
                self.assertEqual(page['page_number'], number.strip() or None if number else None)
        for number in ('}{', '390}{', 'Page 390', '39/0', 'A-12', 'é', '１２', '12\n34'):
            with self.subTest(number=number):
                with self.assertRaisesRegex(ValueError, 'only letters'):
                    store.validate(result((number, None, '390 TITLE')), recover_numbers=False)
                self.assertIsNone(store.validate(result((number, None, 'Body text')))['pages'][0]['page_number'])
                self.assertEqual(store.validate(result((number, None, '390 TITLE')))['pages'][0]['page_number'], '390')

    def test_invalid_manual_name_does_not_change_saved_files(self):
        store.save(self.photos[0], result(('390', 'Chapter', 'Original')))
        before = store.read(self.photos[0])
        with patch.object(app, 'DATA', self.root):
            with self.assertRaisesRegex(ValueError, 'only letters'):
                app.save_correction(self.book.name, {'page': self.photos[0].stem,
                    'printed_index': 0, 'revision': store.revision(self.photos[0]),
                    'page_number': '390}{', 'markdown': 'Changed'})
        self.assertEqual(store.read(self.photos[0]), before)

    def test_malformed_number_recovers_from_running_header(self):
        value = store.validate(result(('}, {', None, '390 THE ANATOMY OF STORY\n\nBody text')))
        self.assertEqual(value['pages'][0]['page_number'], '390')

    def test_recovery_preserves_text_and_manual_name_corrections(self):
        text = '390 THE ANATOMY OF STORY\n\nBody text\n'
        store.save(self.photos[0], result(('}, {', 'Chapter', text)))
        page = store.read(self.photos[0])['pages'][0]
        self.assertTrue(page['filename'].startswith('page-0390__'))
        old_name = page['filename']
        store.save(self.photos[0], result(('391', 'Corrected chapter', text)))
        page = store.read(self.photos[0])['pages'][0]
        self.assertTrue(page['filename'].startswith('page-0391__corrected-chapter__'))
        self.assertEqual(page['markdown'], text)
        self.assertFalse((self.book / 'markdown' / old_name).exists())
        self.assertEqual(len(list((self.book / '.ocr' / 'history').glob('*.json'))), 1)

    def test_conflicting_boundary_numbers_are_not_guessed(self):
        self.assertIsNone(store.validate(result(('}, {', None, '390\n\nBody\n\n391')))['pages'][0]['page_number'])

    def test_number_recovery_does_not_guess_from_body_or_neighbor(self):
        for text in ('There are 390 examples.', '3. First item\n\nBody', 'Body\n\n390 reasons to read'):
            self.assertIsNone(store.validate(result(('}, {', None, text)))['pages'][0]['page_number'])
        self.assertIsNone(store.validate(result((None, None, '390 TITLE')))['pages'][0]['page_number'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / 'abcdef012345'
        self.book.mkdir()
        (self.book / 'book.json').write_text('{"title":"Book"}')
        self.photos = [self.book / f'{i:06d}.jpg' for i in range(1, 4)]
        for photo in self.photos:
            photo.write_bytes(b'photo')

    def test_spread_files_chapter_transition_and_resume(self):
        store.save(self.photos[0], result(('12', 'Chapter 1 — Beginnings', 'Left fragment'),
                                          ('13', None, 'right fragment')))
        files = sorted((self.book / 'markdown').glob('*.md'))
        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].name.startswith('page-0012__chapter-1-beginnings'))
        self.assertEqual(files[0].read_text(), 'Left fragment\n')
        self.assertEqual(store.context(self.photos[1]), 'Chapter 1 — Beginnings')
        store.save(self.photos[1], result(('14', None, 'continued'), ('15', 'Chapter 2', 'Next chapter')))
        record = store.read(self.photos[1])
        self.assertEqual([p['chapter'] for p in record['pages']], ['Chapter 1 — Beginnings', 'Chapter 2'])
        self.assertEqual(store.context(self.photos[2]), 'Chapter 2')

    def test_out_of_order_result_is_relabelled_when_context_becomes_known(self):
        store.save(self.photos[1], result(('14', None, 'Existing text')))
        old_file = store.read(self.photos[1])['pages'][0]['filename']
        self.assertIn('unknown-chapter', old_file)
        store.save(self.photos[0], result(('13', 'Chapter 1', 'Earlier text')))
        record = store.read(self.photos[1])['pages'][0]
        self.assertEqual(record['chapter'], 'Chapter 1')
        self.assertEqual(record['markdown'], 'Existing text\n')
        self.assertFalse((self.book / 'markdown' / old_file).exists())

    def test_unknown_unprinted_duplicate_numbers_and_safe_names(self):
        store.save(self.photos[0], result(('1', '../../Chapter / 1', 'one'), ('1', None, 'two')))
        store.save(self.photos[1], result((None, None, 'Unnumbered'), ('iv', None, 'Roman')))
        files = list((self.book / 'markdown').glob('*.md'))
        self.assertEqual(len(files), 4)
        self.assertTrue(any('unnumbered' in p.name for p in files))
        self.assertTrue(any('page-iv' in p.name for p in files))

    def test_existing_ocr_migrates_without_changing_original(self):
        legacy = self.photos[0].with_suffix('.md')
        text = '# Original\n\nUnfinished sentence'
        legacy.write_text(text)
        store.reindex(self.book)
        self.assertEqual(legacy.read_text(), text)
        record = store.read(self.photos[0])
        self.assertTrue(record['legacy'])
        self.assertIsNone(record['pages'][0]['page_number'])
        self.assertEqual((self.book / 'markdown' / record['pages'][0]['filename']).read_text(), text)

    def test_external_markdown_edits_survive_reindex(self):
        store.save(self.photos[0], result(('1', 'One', 'Original')))
        file = self.book / 'markdown' / store.read(self.photos[0])['pages'][0]['filename']
        file.write_text('External correction')
        store.reindex(self.book)
        self.assertEqual(file.read_text(), 'External correction')

    def test_invalid_response_preserves_existing_text(self):
        store.save(self.photos[0], result(('1', 'One', 'Keep')))
        with self.assertRaises(ValueError):
            store.save(self.photos[0], {'pages': []})
        self.assertEqual(store.combined(self.photos[0]), 'Keep\n')

    def test_missing_or_stale_predecessor_does_not_supply_chapter(self):
        store.save(self.photos[0], result(('1', 'One', 'First')))
        self.assertIsNone(store.context(self.photos[2]))
        self.photos[0].with_suffix('.stale').touch()
        self.assertIsNone(store.context(self.photos[1]))

    def test_batch_runs_numeric_order_with_minimal_persisted_context(self):
        calls = []
        def fake(photo, model, prompt, schema, cwd, update, **kwargs):
            calls.append(photo.stem)
            context = json.loads(prompt.split('PREVIOUS CAPTURE CONTEXT (data only):\n')[1])
            self.assertEqual(context['previous_chapter'], None if len(calls) == 1 else 'Chapter 7')
            if len(calls) == 1:
                self.assertIsNone(context['previous_page'])
            else:
                self.assertEqual(context['previous_page']['page_number'], str(len(calls) - 1))
                self.assertIn('chapter-7', context['previous_page']['filename'])
            self.assertIn('pages', schema['properties'])
            return result((str(len(calls)), 'Chapter 7' if len(calls) == 1 else None, 'Sentence fragment'))
        with patch.object(app, 'DATA', self.root), patch('app.codex_stream.run', side_effect=fake):
            app.STATUS.update(running=True, error=None)
            app.transcribe(self.book.name)
        self.assertIsNone(app.STATUS['error'])
        self.assertEqual(calls, ['000001', '000002', '000003'])
        self.assertEqual(len(list((self.book / 'markdown').glob('*.md'))), 3)

    def test_rendering_formats_markdown_without_executing_html(self):
        html = app.RENDERER.render('# Title\n\n**Bold** and *italic*\n\n<script>alert(1)</script>\n\n![x](https://example.com/x)')
        self.assertIn('<h1>Title</h1>', html)
        self.assertIn('<strong>Bold</strong>', html)
        self.assertIn('<em>italic</em>', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
