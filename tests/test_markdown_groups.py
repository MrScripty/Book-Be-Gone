import unittest
import tempfile
from pathlib import Path

import markdown_groups
import ocr_review
import transcriptions


def record(text):
    return {'pages': [{'page_number': '1', 'chapter_seen': None, 'markdown': text}]}


class MarkdownGroupTests(unittest.TestCase):
    def test_formatting_pairs_group_in_both_directions(self):
        for formatted in ('**hello world**', '*hello world*', '__hello world__',
                          '_hello world_', '~~hello world~~', '`hello world`',
                          '``hello world``', '[hello world](https://example.com/a_(b))',
                          '![hello world](image.png)', '```text\nhello world\n```'):
            for old, new in (('hello world', formatted), (formatted, 'hello world')):
                with self.subTest(old=old, new=new):
                    edits = ocr_review.changes(record(old), record(new))
                    groups = [c['group'] for c in edits if 'group' in c]
                    self.assertTrue(groups)
                    self.assertTrue(all(group == groups[0] for group in groups))

    def test_word_edit_and_separate_formatting_spans_stay_independent(self):
        edits = ocr_review.changes(record('hello old world and more'), record('**hello new world** and *more*'))
        word = next(c for c in edits if c['old'] == 'old')
        self.assertNotIn('group', word)
        groups = {tuple(c['group']) for c in edits if 'group' in c}
        self.assertEqual(len(groups), 2)

    def test_moved_formatting_and_changed_delimiter_styles_stay_paired(self):
        for before, after in [('**hello**', '*hello*'), ('*hello*', '_hello_')]:
            with self.subTest(before=before, after=after):
                edits = ocr_review.changes(record(before), record(after))
                self.assertGreater(len(edits), 1)
                self.assertEqual(edits[0]['group'], [c['id'] for c in edits])

    def test_escaped_markers_literals_and_code_contents_are_not_emphasis(self):
        for text in (r'\*literal\*', 'snake_case_name', '2 * 3 * 4'):
            self.assertEqual(markdown_groups.syntax_pairs(text), [])
        pairs = markdown_groups.syntax_pairs('`**literal**`')
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0], [(0, 1), (12, 13)])

    def test_list_prefix_and_nested_emphasis_offsets(self):
        text = '* **hello** and *world*'
        pairs = markdown_groups.syntax_pairs(text)
        self.assertEqual([[text[a:b] for a,b in p] for p in pairs], [['**','**'], ['*','*']])
        self.assertEqual(len(markdown_groups.syntax_pairs('***hello***')), 2)

    def test_server_rejects_half_pair_and_saves_complete_group(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / '000001.jpg'
            photo.write_bytes(b'image')
            transcriptions.save(photo, record('hello old world\n'))
            proposal = ocr_review.propose(photo, record('**hello new world**\n'))
            grouped = next(c for c in proposal['changes'] if 'group' in c)
            with self.assertRaisesRegex(ValueError, 'formatting'):
                ocr_review.resolve(photo, proposal['id'], [grouped['id']])
            self.assertEqual(transcriptions.read(photo)['pages'][0]['markdown'], 'hello old world\n')
            ocr_review.resolve(photo, proposal['id'], grouped['group'])
            self.assertEqual(transcriptions.read(photo)['pages'][0]['markdown'], '**hello old world**\n')
