import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image
import app
import figures
import transcriptions


def illustrated():
    return {'pages': [{'page_number': '44', 'chapter_seen': 'Chapter 2',
        'markdown': 'Before\n\n{{figure-1}}\n\nPrinted caption.\n\nAfter',
        'figures': [{'id': 'figure-1', 'bbox': [.25, .2, .75, .8],
            'description': 'Two connected boxes.', 'format': 'mermaid',
            'representation': 'flowchart LR\n  A["Start"] --> B["End"]'}]}]}


class FigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / 'abcdef012345'
        self.book.mkdir()
        (self.book / 'book.json').write_text('{}')
        self.photo = self.book / '000001.jpg'
        Image.new('RGB', (200, 100), 'red').save(self.photo)
        self.corrected = self.book / 'corrected' / self.photo.name
        self.corrected.parent.mkdir()
        Image.new('RGB', (100, 200), 'blue').save(self.corrected)
        self.patch = patch.object(app, 'DATA', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app.STATUS.update(running=False, book=None, page=None)

    def save(self):
        value = figures.prepare(self.photo, self.corrected, transcriptions.validate(illustrated()))
        transcriptions.save(self.photo, value)
        return transcriptions.read(self.photo)

    def test_ocr_saves_corrected_crop_and_representation_at_marker(self):
        with patch.object(app.codex_stream, 'run', return_value=illustrated()):
            app.transcribe(self.book.name)
        self.assertIsNone(app.STATUS['error'])
        page = transcriptions.read(self.photo)['pages'][0]
        figure = page['figures'][0]
        with Image.open(self.book / 'markdown' / 'assets' / figure['asset']) as crop:
            self.assertEqual(crop.size, (50, 120))
            self.assertGreater(crop.getpixel((0, 0))[2], 240)
        self.assertLess(page['markdown'].index('Before'), page['markdown'].index('![Two'))
        self.assertLess(page['markdown'].index('```mermaid'), page['markdown'].index('Printed caption.'))
        self.assertNotIn('{{figure', page['markdown'])
        self.assertIn('Figure description (generated): Two connected boxes.', page['markdown'])
        html = app.document(self.book.name)['pages'][0]['html']
        self.assertIn('/api/asset/' + self.book.name, html)
        self.assertIn('language-mermaid', html)

    def test_recrop_uses_immutable_source_preserves_edits_and_history(self):
        record = self.save()
        old = copy.deepcopy(record)
        record['pages'][0]['markdown'] += '\nManual correction\n'
        transcriptions.save(self.photo, record)
        revision = transcriptions.revision(self.photo)
        Image.new('RGB', (10, 10), 'green').save(self.corrected)
        figures.recrop(self.photo, record, 0, 'figure-1', [0, 0, 1, 1])
        transcriptions.save(self.photo, record)
        page = transcriptions.read(self.photo)['pages'][0]
        new = page['figures'][0]
        self.assertNotEqual(revision, transcriptions.revision(self.photo))
        self.assertIn('Manual correction', page['markdown'])
        self.assertIn('flowchart LR', page['markdown'])
        self.assertNotIn(old['pages'][0]['figures'][0]['asset'], page['markdown'])
        with Image.open(self.book / 'markdown' / 'assets' / new['asset']) as crop:
            self.assertEqual(crop.size, (100, 200))
            self.assertGreater(crop.getpixel((0, 0))[2], 240)
        self.assertTrue((self.book / 'markdown' / 'assets' / old['pages'][0]['figures'][0]['asset']).exists())
        self.assertTrue(list((self.book / '.ocr' / 'history').glob('*.json')))

    def test_markdown_edit_and_chapter_reindex_keep_figures(self):
        page = self.save()['pages'][0]
        app.save_correction(self.book.name, {'page': self.photo.stem, 'printed_index': 0,
            'revision': transcriptions.revision(self.photo), 'page_number': 'iv',
            'chapter_seen': 'New chapter', 'markdown': page['markdown'] + '\nEdited description'})
        after = transcriptions.read(self.photo)['pages'][0]
        self.assertEqual(after['figures'], page['figures'])
        self.assertIn('new-chapter', after['filename'])
        self.assertIn('assets/' + page['figures'][0]['asset'], after['markdown'])

    def test_export_contains_relative_assets_and_one_file_per_page(self):
        page = self.save()['pages'][0]
        with zipfile.ZipFile(io.BytesIO(app.export_book(self.book.name))) as archive:
            self.assertEqual(set(archive.namelist()), {'book.md', page['filename'], 'assets/' + page['figures'][0]['asset']})
            self.assertIn('assets/' + page['figures'][0]['asset'], archive.read('book.md').decode())

    def test_bad_bounds_or_missing_marker_preserve_completed_ocr(self):
        self.save()
        before = transcriptions.revision(self.photo)
        for bbox in ([0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, float('nan'), 1], [False, 0, 1, 1]):
            value = illustrated(); value['pages'][0]['figures'][0]['bbox'] = bbox
            with self.assertRaises(ValueError):
                transcriptions.validate(value)
        value = illustrated(); value['pages'][0]['markdown'] = 'Missing marker'
        with self.assertRaises(ValueError):
            figures.prepare(self.photo, self.corrected, transcriptions.validate(value))
        self.assertEqual(transcriptions.revision(self.photo), before)

    def test_external_images_and_html_are_not_loaded(self):
        html = app.render_markdown('![x](https://example.com/x.png)\n<img src=x onerror=alert(1)>', self.book.name)
        self.assertNotIn('<img', html)
        self.assertNotIn('<script', html)

    def test_two_pages_can_each_have_figure_one(self):
        value = illustrated(); value['pages'].append(copy.deepcopy(value['pages'][0]))
        value = figures.prepare(self.photo, self.corrected, transcriptions.validate(value))
        self.assertNotEqual(value['pages'][0]['figures'][0]['asset'], value['pages'][1]['figures'][0]['asset'])

    def test_fence_in_representation_cannot_escape_code_block(self):
        figure = illustrated()['pages'][0]['figures'][0]
        figure.update(asset='000001-1-figure-1-' + 'a'*32 + '.png', representation='```\n<script>bad</script>')
        html = app.render_markdown(figures.block(figure), self.book.name)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
