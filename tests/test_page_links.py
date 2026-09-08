import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import app
import page_links
import transcriptions


def page(number, text, chapter=None):
    return {'page_number': number, 'chapter_seen': chapter, 'markdown': text}


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.book = Path(self.temp.name) / 'abcdef012345'
        self.book.mkdir()
        (self.book / 'book.json').write_text('{}')
        self.patch = patch.object(app, 'DATA', self.book.parent)
        self.patch.start(); self.addCleanup(self.patch.stop)
        app.STATUS.update(running=False, book=None, page=None)

    def save(self, capture, *pages):
        photo = self.book / f'{capture:06d}.jpg'
        photo.write_bytes(b'photo')
        transcriptions.save(photo, {'pages': list(pages)})
        return photo

    def test_contents_index_ranges_roman_and_prose(self):
        targets = {n: f'target-{n}.md' for n in ['8', '44', '45', '239', '240', 'iv']}
        text = '# INDEX\n\narrows, 239–40, 44; use in, 45\n\n*Film (2001)*, 8\n\n44\n'
        linked = page_links.link_text(text, targets, {}, detect=True)
        self.assertIn('[239](target-239.md)–[40](target-240.md)', linked)
        self.assertIn('[44](target-44.md); use in, [45](target-45.md)', linked)
        self.assertIn('*Film (2001)*, [8](target-8.md)', linked)
        self.assertTrue(linked.endswith('\n44\n'))
        contents = page_links.link_text('# Contents\n\nPreface ... iv\n| First chapter | 44 |\nChapter 8\n', targets, {}, detect=True)
        self.assertIn('[iv](target-iv.md)', contents)
        self.assertIn('| First chapter | [44](target-44.md) |', contents)
        self.assertIn('\nChapter 8\n', contents)
        prose = page_links.link_text('In 44 years, see pages 44–45 and p. 8.\n', targets, {}, detect=True)
        self.assertTrue(prose.startswith('In 44 years'))
        self.assertIn('pages [44](target-44.md)–[45](target-45.md)', prose)
        self.assertIn('p. [8](target-8.md)', prose)

    def test_ambiguous_missing_and_unrelated_numbers_stay_plain(self):
        source = self.save(1, page('iv', '# Contents\n\nA ... 44\nB ... 999\n'))
        self.save(2, page('44', 'One'), page('44', 'Duplicate'))
        before = transcriptions.read(source)['pages'][0]['markdown']
        result = transcriptions.reindex(self.book, link_pages=True)
        self.assertEqual(result['changed_pages'], 0)
        self.assertEqual(transcriptions.read(source)['pages'][0]['markdown'], before)

    def test_code_images_external_links_and_reference_definitions_unchanged(self):
        text = ('See [page 44](https://example.com), ![page 44](assets/figure.png), `page 44`.\n'
                '```mermaid\npage 44\n```\n\n    page 44\n\n[x]: page:44\n\n**Page 44**\n')
        self.assertEqual(page_links.link_text(text, {'44':'target.md'}, {}, detect=True), text)

    def test_links_resolve_later_and_survive_chapter_renaming(self):
        source = self.save(1, page('iv', '# Contents\n\nA ... [44](page:44)\n'))
        self.assertIn('(page:44)', transcriptions.read(source)['pages'][0]['markdown'])
        target = self.save(2, page('44', 'Actual target', 'Chapter One'))
        old = transcriptions.read(target)['pages'][0]['filename']
        self.assertIn('(' + old + ')', transcriptions.read(source)['pages'][0]['markdown'])
        transcriptions.save(target, {'pages': [page('44', 'Edited target', 'Chapter Two')]})
        new = transcriptions.read(target)['pages'][0]['filename']
        self.assertNotEqual(old, new)
        self.assertIn('(' + new + ')', transcriptions.read(source)['pages'][0]['markdown'])
        self.assertNotIn(old, transcriptions.read(source)['pages'][0]['markdown'])
        self.assertFalse((self.book / 'markdown' / old).exists())

    def test_partial_range_resolves_when_endpoint_is_added_and_is_idempotent(self):
        source = self.save(1, page('iv', '# Index\n\nArrows, 239–40\n'))
        self.save(2, page('239', 'Start'))
        transcriptions.reindex(self.book, link_pages=True)
        self.save(3, page('240', 'End'))
        transcriptions.reindex(self.book, link_pages=True)
        text = transcriptions.read(source)['pages'][0]['markdown']
        end = transcriptions.read(self.book / '000003.jpg')['pages'][0]['filename']
        self.assertIn('–[40](' + end + ')', text)
        self.assertEqual(transcriptions.reindex(self.book, link_pages=True)['changed_pages'], 0)
        self.assertEqual(transcriptions.read(source)['pages'][0]['markdown'], text)

    def test_external_edits_and_figures_survive_link_pass_with_history(self):
        source = self.save(1, page('iv', 'See page 44.'))
        self.save(2, page('44', 'Target'))
        item = transcriptions.read(source)['pages'][0]
        (self.book / 'markdown' / item['filename']).write_text('Manual correction. See page 44.\n\n![figure](assets/figure.png)\n')
        old_revision = transcriptions.revision(source)
        transcriptions.reindex(self.book, link_pages=True)
        item = transcriptions.read(source)['pages'][0]
        self.assertTrue(item['markdown'].startswith('Manual correction.'))
        self.assertIn('![figure](assets/figure.png)', item['markdown'])
        self.assertNotEqual(old_revision, transcriptions.revision(source))
        self.assertTrue(list((self.book / '.ocr' / 'history').glob('*.json')))

    def test_ocr_links_and_exported_destinations_exist(self):
        first = self.save(1, page('iv', '# Contents\n\nTarget ... 44'))
        pending = self.book / '000002.jpg'; pending.write_bytes(b'photo')
        with patch.object(app.codex_stream, 'run', return_value={'pages': [page('44', 'Target')]}):
            app.transcribe(self.book.name)
        self.assertIsNone(app.STATUS['error'])
        target = transcriptions.read(pending)['pages'][0]['filename']
        self.assertIn('(' + target + ')', transcriptions.read(first)['pages'][0]['markdown'])
        html = app.document(self.book.name)['pages'][0]['html']
        self.assertIn('href="#book-abcdef012345/page-000002-1"', html)
        with zipfile.ZipFile(io.BytesIO(app.export_book(self.book.name))) as archive:
            self.assertIn(target, archive.namelist())
            self.assertIn('(' + target + ')', archive.read('book.md').decode())

    def test_programmatic_pass_does_not_use_pending_targets(self):
        source = self.save(1, page('iv', 'See page 44'))
        target = self.save(2, page('44', 'Target'))
        target.with_suffix('.stale').touch()
        transcriptions.reindex(self.book, link_pages=True)
        self.assertEqual(transcriptions.read(source)['pages'][0]['markdown'], 'See page 44\n')
