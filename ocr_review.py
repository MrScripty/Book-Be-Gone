"""Durable OCR proposals: saved text changes only after explicit selection."""
import copy
import difflib
import hashlib
import json
import uuid
import re
import markdown_groups

import transcriptions as store


def path(photo):
    return photo.parent / '.ocr' / (photo.stem + '.review.json')


def fingerprint(photo):
    # Include all capture variants, so a crop change invalidates a proposal too.
    images = [photo]
    corrected = photo.parent / 'corrected' / photo.name
    if corrected.exists():
        images.append(corrected)
    digest = hashlib.sha256(store.revision(photo).encode())
    for image in images:
        digest.update(image.name.encode())
        digest.update(image.read_bytes())
    digest.update(str(photo.with_suffix('.stale').exists()).encode())
    return digest.hexdigest()


def read(photo):
    if not path(photo).exists():
        return None
    proposal = json.loads(path(photo).read_text())
    if proposal.get('format') != 4:
        # Deterministic view upgrade; reject selections from previously opened UIs.
        proposal.update(format=4, id=proposal['id'] + '-boundaries-v4',
                        changes=changes(proposal['old'], proposal['new']))
    return proposal


def tokens(text):
    # Digits must not attach to the next entry's word, even if OCR omitted a space.
    # Newlines are separate from horizontal whitespace and from each other.
    return re.findall(r'[^\W\d_]+|\d+|[^\S\r\n]+|\r\n|\r|\n|[^\w\s]|_', text)


def token_kind(token):
    if token.isdecimal():
        return 'number'
    if token in ('\n', '\r', '\r\n'):
        return 'newline'
    if token.isspace():
        return 'space'
    if token[0].isalnum():
        return 'word'
    return token


def opcodes(a, b):
    for tag, i, j, k, l in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != 'replace':
            yield tag, i, j, k, l
            continue
        # A replacement can contain multiple changed token types without any
        # unchanged text between them. Align their types, not their spelling.
        kinds_a, kinds_b = list(map(token_kind, a[i:j])), list(map(token_kind, b[k:l]))
        for subtag, x, y, u, v in difflib.SequenceMatcher(None, kinds_a, kinds_b, autojunk=False).get_opcodes():
            if subtag == 'equal':
                for offset in range(y-x):
                    left, right = i+x+offset, k+u+offset
                    yield 'equal' if a[left] == b[right] else 'replace', left, left+1, right, right+1
            else:
                yield subtag, i+x, i+y, k+u, k+v


def changes(old, new):
    result = []
    def add(page, field, before, after, start=None, end=None):
        result.append(dict(id=str(len(result)), page=page, field=field,
                           old=before, new=after, start=start, end=end))
    if len(old['pages']) != len(new['pages']):
        add(None, 'capture', old['pages'], new['pages'])
        return result
    for index, (before, after) in enumerate(zip(old['pages'], new['pages'])):
        if before.get('figures') or after.get('figures'):
            add(index, 'page', before, after)
            continue
        for field in ('page_number', 'chapter_seen'):
            if before.get(field) != after.get(field):
                add(index, field, before.get(field), after.get(field))
        a, b = tokens(before['markdown']), tokens(after['markdown'])
        offsets = [0]
        for token in a:
            offsets.append(offsets[-1] + len(token))
        new_offsets = [0]
        for token in b:
            new_offsets.append(new_offsets[-1] + len(token))
        edits, matches = [], []
        for tag, i, j, k, l in opcodes(a, b):
            if tag != 'equal':
                add(index, 'markdown', ''.join(a[i:j]), ''.join(b[k:l]), offsets[i], offsets[j])
                result[-1]['unit'] = 'codepoints'
                result[-1].update(new_start=new_offsets[k], new_end=new_offsets[l])
                edits.append(result[-1])
            else:
                matches.append((offsets[i], offsets[j], new_offsets[k]))
        markdown_groups.group_changes(edits, before['markdown'], after['markdown'], matches)
    return result


def propose(photo, new):
    if path(photo).exists():
        raise ValueError('Review or discard the previous OCR comparison first.')
    old = store.read(photo)
    proposal = dict(id=uuid.uuid4().hex, format=4, revision=fingerprint(photo), old=old,
                    new=new, changes=changes(old, new))
    store.atomic_json(path(photo), proposal)
    return proposal


def resolve(photo, identifier, selected, discard=False):
    proposal = read(photo)
    if not proposal or proposal['id'] != identifier:
        raise ValueError('This OCR comparison changed. Reopen it before saving.')
    if discard:
        path(photo).unlink()
        return
    if fingerprint(photo) != proposal['revision']:
        raise ValueError('The saved text or image changed. Discard this comparison and redo OCR.')
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        raise ValueError('Select valid OCR changes.')
    selected = set(selected)
    if not selected <= {c['id'] for c in proposal['changes']}:
        raise ValueError('Unknown OCR change.')
    for change in proposal['changes']:
        if change['id'] in selected and not set(change.get('group', [])) <= selected:
            raise ValueError('Matching Markdown formatting must be selected together. Reopen the comparison.')
    value = copy.deepcopy(proposal['old'])
    for change in reversed(proposal['changes']):
        if change['id'] not in selected:
            continue
        field, index = change['field'], change['page']
        if field == 'capture':
            value['pages'] = change['new']
        elif field == 'page':
            value['pages'][index] = change['new']
        elif field == 'markdown':
            text = value['pages'][index]['markdown']
            value['pages'][index]['markdown'] = text[:change['start']] + change['new'] + text[change['end']:]
        else:
            value['pages'][index][field] = change['new']
    if selected:
        store.save(photo, value)
        store.reindex(photo.parent, link_pages=True)
    path(photo).unlink()
