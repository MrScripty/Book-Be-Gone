import unittest

import app
import ocr_review
import review_render


def record(text):
    return {'pages': [{'page_number': '1', 'chapter_seen': None, 'markdown': text}]}


class RenderedReviewTests(unittest.TestCase):
    def test_adjacent_number_and_word_have_distinct_rendered_controls(self):
        for separator in ('', '\n', '  \n', '\n\n'):
            with self.subTest(separator=separator):
                result = self.render_pair(f'Entry 12{separator}Next entry', f'Entry 34{separator}Other entry')
                edits = result['changes']
                number = next(c for c in edits if c['old'] == '12')
                word = next(c for c in edits if c['old'] == 'Next')
                self.assertNotEqual(number['id'], word['id'])
                self.assertNotIn('group', number)
                rendered = result['rendered']['new'][0]['html']
                self.assertIn(f'data-change="{number["id"]}"', rendered)
                self.assertIn('>34</mark>', rendered)
                self.assertIn(f'data-change="{word["id"]}"', rendered)
                self.assertIn('>Other</mark>', rendered)

    def render_pair(self, before, after):
        proposal = {'old': record(before), 'new': record(after), 'changes': ocr_review.changes(record(before), record(after))}
        return review_render.render(proposal, app.render_markdown)

    def test_full_markdown_structure_and_selectable_words(self):
        before = '# Title\n\nA **wrong** word.\n\n- First\n- Second\n\n> Quote\n\n```python\nx = 1\n```\n'
        result = self.render_pair(before, before.replace('wrong', 'correct'))
        rendered = result['rendered']['new'][0]['html']
        for tag in ('<h1>', '<strong>', '<ul>', '<blockquote>', '<pre>'):
            self.assertIn(tag, rendered)
        self.assertIn('>correct</mark></strong>', rendered)
        self.assertNotIn('**', rendered)
        self.assertIn('data-change="0"', rendered)

    def test_hidden_formatting_controls_keep_same_group_ids(self):
        result = self.render_pair('**hello** world', 'hello world')
        self.assertIn('<strong>hello</strong>', result['rendered']['old'][0]['html'])
        self.assertNotIn('<strong>', result['rendered']['new'][0]['html'])
        group = result['changes'][0]['group']
        self.assertEqual(result['rendered']['old'][0]['hidden_ids'], group)
        self.assertEqual(result['rendered']['new'][0]['hidden_ids'], group)

    def test_html_and_entities_remain_safe_and_text_is_not_lost(self):
        result = self.render_pair('A & old <script>alert(1)</script>', 'A & new <script>alert(1)</script>')
        rendered = result['rendered']['new'][0]['html']
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('&amp;', rendered)
        self.assertIn('>new</mark>', rendered)

    def test_repeated_text_unicode_and_link_destinations(self):
        result = self.render_pair('😀 same old same. [label](https://example.com/old)', '😀 same new same. [label](https://example.com/new)')
        view = result['rendered']['new'][0]
        self.assertIn('😀 same <mark', view['html'])
        self.assertIn('>new</mark> same.', view['html'])
        self.assertIn('href="https://example.com/new"', view['html'])
        self.assertEqual(len(view['hidden_ids']), 1)

    def test_tables_and_code_remain_structural(self):
        before = '| A | B |\n|---|---|\n| old | cell |\n\n`old`\n'
        view = self.render_pair(before, before.replace('old', 'new'))['rendered']['new'][0]['html']
        self.assertIn('<table>', view)
        self.assertIn('<td><mark', view)
        self.assertIn('<code><mark', view)
