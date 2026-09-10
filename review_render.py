"""Render complete Markdown first, then annotate visible text without breaking syntax."""
import difflib
import html
from html.parser import HTMLParser


class Parts(HTMLParser):
    def __init__(self, rendered):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(rendered)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.parts.append(('tag', self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        self.parts.append(('tag', self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.parts.append(('tag', f'</{tag}>'))

    def handle_data(self, data):
        self.parts.append(('text', data))


def annotate(source, rendered, edits, side):
    parts = Parts(rendered).parts
    visible = ''.join(text for kind, text in parts if kind == 'text')
    matches = difflib.SequenceMatcher(None, source, visible, autojunk=False).get_matching_blocks()
    spans, shown = [], set()
    for edit in edits:
        if edit['field'] != 'markdown':
            continue
        start, end = (edit['start'], edit['end']) if side == 'old' else (edit['new_start'], edit['new_end'])
        for match in matches:
            left, right = max(start, match.a), min(end, match.a + match.size)
            if left < right and source[left:right].strip():
                spans.append((left + match.b - match.a, right + match.b - match.a, edit['id']))
                shown.add(edit['id'])
    spans.sort()
    result, offset = [], 0
    for kind, text in parts:
        if kind == 'tag':
            result.append(text)
            continue
        cursor = 0
        for start, end, identifier in spans:
            left, right = max(0, start-offset), min(len(text), end-offset)
            if left < right:
                result.append(html.escape(text[cursor:left]))
                result.append(f'<mark class="highlight" data-change="{html.escape(identifier, quote=True)}" role="checkbox" aria-checked="false" tabindex="0">{html.escape(text[left:right])}</mark>')
                cursor = right
        result.append(html.escape(text[cursor:]))
        offset += len(text)
    return {'html': ''.join(result), 'hidden_ids': [c['id'] for c in edits if c['field']=='markdown' and c['id'] not in shown]}


def render(proposal, renderer):
    proposal['rendered'] = {}
    for side in ('old', 'new'):
        proposal['rendered'][side] = []
        for index, page in enumerate(proposal[side]['pages']):
            edits = [c for c in proposal['changes'] if c['page'] == index]
            proposal['rendered'][side].append(annotate(page['markdown'], renderer(page['markdown']), edits, side))
    return proposal
