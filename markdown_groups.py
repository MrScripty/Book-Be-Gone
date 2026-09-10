"""Locate paired Markdown syntax using the same parser as the reader."""
import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import emphasis, strikethrough, backticks, link, image


def parser():
    md = MarkdownIt('js-default')

    def delimiters(rule, width):
        def tracked(state, silent):
            start, count = state.pos, len(state.delimiters)
            ok = rule(state, silent)
            if ok and not silent:
                added = state.delimiters[count:]
                offset = start + (state.pos - start) % width
                for delimiter in added:
                    state.tokens[delimiter.token].meta['ocr_position'] = (offset, offset + width)
                    offset += width
            return ok
        return tracked

    def paired(rule, kind):
        def tracked(state, silent):
            start, count = state.pos, len(state.tokens)
            label_end = -1
            if kind in ('link', 'image'):
                bracket = start + (kind == 'image')
                if bracket < len(state.src) and state.src[bracket] == '[':
                    label_end = state.md.helpers.parseLinkLabel(state, bracket, True)
            ok = rule(state, silent)
            if ok and not silent:
                wanted = {'code': 'code_inline', 'link': 'link_open', 'image': 'image'}[kind]
                for token in state.tokens[count:]:
                    if token.type == wanted and 'ocr_pair' not in token.meta:
                        if kind == 'code':
                            size = len(token.markup)
                            token.meta['ocr_pair'] = [(start, start + size), (state.pos - size, state.pos)]
                        elif label_end >= 0:
                            token.meta['ocr_pair'] = [(start, start + 1 + (kind == 'image')), (label_end, state.pos)]
                        break
            return ok
        return tracked

    md.inline.ruler.at('emphasis', delimiters(emphasis.tokenize, 1))
    md.inline.ruler.at('strikethrough', delimiters(strikethrough.tokenize, 2))
    md.inline.ruler.at('backticks', paired(backticks.backtick, 'code'))
    md.inline.ruler.at('link', paired(link, 'link'))
    md.inline.ruler.at('image', paired(image, 'image'))
    return md


def syntax_pairs(source):
    md = parser()
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    result = []
    for block in md.parse(source):
        if block.type == 'fence' and block.map:
            first, end = block.map
            if end - first > 1:
                closing = re.match(r' {0,3}(' + re.escape(block.markup[0]) + r'{'+str(len(block.markup))+r',})\s*$', lines[end-1])
                if closing:
                    result.append([(offsets[first], offsets[first+1]), (offsets[end-1], offsets[end])])
        if block.type != 'inline' or not block.map:
            continue
        # Inline content omits list/quote prefixes; map it back to source offsets.
        positions, cursor = [], offsets[block.map[0]]
        for line in block.content.splitlines(keepends=True):
            cursor = source.find(line, cursor, offsets[block.map[1]])
            if cursor < 0:
                break
            positions.extend(range(cursor, cursor + len(line)))
            cursor += len(line)
        if len(positions) != len(block.content):
            continue
        stack = []
        def mapped(pair):
            return [(positions[a], positions[b-1]+1) for a, b in pair if 0 <= a < b <= len(positions)]
        for token in block.children or []:
            if 'ocr_pair' in token.meta:
                pair = mapped(token.meta['ocr_pair'])
                if len(pair) == 2:
                    result.append(pair)
            position = token.meta.get('ocr_position')
            if position and token.nesting:
                a, b = position
                if token.type == 'strong_open':
                    a -= 1
                elif token.type == 'strong_close':
                    b += 1
                if token.nesting == 1:
                    stack.append((token.tag, (a, b)))
                elif stack and stack[-1][0] == token.tag:
                    result.append(mapped([stack.pop()[1], (a, b)]))
    return result


def group_changes(edits, before, after, matches):
    """Connect changed delimiters, transitively across old and new syntax pairs."""
    old_pairs, new_pairs = syntax_pairs(before), syntax_pairs(after)
    parent = list(range(len(edits) + len(old_pairs) + len(new_pairs)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    base = len(edits)
    for pairs, start_key, end_key in ((old_pairs, 'start', 'end'), (new_pairs, 'new_start', 'new_end')):
        for ordinal, pair in enumerate(pairs):
            touched = [i for i, edit in enumerate(edits) if any(edit[start_key] < b and edit[end_key] > a for a, b in pair)]
            for i in touched:
                parent[root(i)] = root(base + ordinal)
        base += len(pairs)
    # Unchanged markers can switch partners when formatting moves. Connect their
    # old and new pairs too, otherwise one moved boundary could still be accepted alone.
    for i, pair in enumerate(old_pairs):
        for a, b in pair:
            for start, end, new_start in matches:
                left, right = max(a, start), min(b, end)
                if left >= right:
                    continue
                left, right = left + new_start - start, right + new_start - start
                for j, new_pair in enumerate(new_pairs):
                    if any(left < y and right > x for x, y in new_pair):
                        parent[root(len(edits) + i)] = root(len(edits) + len(old_pairs) + j)
    groups = {}
    for i, edit in enumerate(edits):
        groups.setdefault(root(i), []).append(edit['id'])
    for i, edit in enumerate(edits):
        if len(groups[root(i)]) > 1:
            edit['group'] = groups[root(i)]
