"""Printed-page Markdown files and resumable, ordered chapter context."""
import figures
import page_links
import json
import hashlib
from pathlib import Path
import re
import time
import unicodedata


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def record_path(photo):
    return photo.parent / '.ocr' / (photo.stem + '.json')


def read(photo):
    path = record_path(photo)
    if path.exists():
        record = json.loads(path.read_text(encoding='utf-8'))
        for page in record['pages']:
            name = page.get('filename')
            if name and Path(name).name == name:
                markdown = photo.parent / 'markdown' / name
                if markdown.exists():
                    page['markdown'] = markdown.read_text(encoding='utf-8')
        return record
    legacy = photo.with_suffix('.md')
    if legacy.exists():
        return {'legacy': True, 'pages': [{'page_number': None, 'chapter_seen': None,
                 'chapter': None, 'markdown': legacy.read_text(encoding='utf-8')}]}
    return None


def recover_page_number(number, markdown):
    """Repair invalid OCR metadata; never override an alphanumeric or absent label."""
    if not number or re.fullmatch(r'[A-Za-z0-9]+', number):
        return number
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    candidates = set()
    for line in lines[:1] + lines[-1:]:
        if re.fullmatch(r'[0-9]{1,6}|[ivxlcdmIVXLCDM]+', line):
            candidates.add(line)
        # Only an all-capitals running header, not a numbered list or prose.
        for pattern in (r'([0-9]{1,6})\s+([A-Z][A-Z &—–:-]+)',
                        r'([A-Z][A-Z &—–:-]+)\s+([0-9]{1,6})'):
            match = re.fullmatch(pattern, line)
            if match:
                candidates.add(next(part for part in match.groups() if part.isdigit()))
    return candidates.pop() if len(candidates) == 1 else None


def validate(value, *, recover_numbers=True):
    if not isinstance(value, dict) or not isinstance(value.get('pages'), list) or not 1 <= len(value['pages']) <= 2:
        raise ValueError('OCR must return one or two printed pages')
    result = []
    for page in value['pages']:
        if not isinstance(page, dict):
            raise ValueError('Invalid OCR page')
        text = page.get('markdown')
        if not isinstance(text, str):
            raise ValueError('OCR page must contain Markdown text')
        item = {'markdown': text.rstrip() + '\n' if text.strip() else ''}
        for key in ['page_number', 'chapter_seen']:
            field = page.get(key)
            if field is not None and (not isinstance(field, str) or len(field) > 200):
                if key == 'page_number' and recover_numbers:
                    item[key] = recover_page_number('}{', text)
                    continue
                raise ValueError('Invalid ' + key)
            item[key] = field.strip() or None if isinstance(field, str) else None
        number = item['page_number']
        if number and not re.fullmatch(r'[A-Za-z0-9]+', number):
            if not recover_numbers:
                raise ValueError('Printed page number must contain only letters A–Z and digits 0–9, or be blank.')
            item['page_number'] = recover_page_number(number, text)
        if 'figures' in page:
            item['figures'] = figures.validate(page['figures'])
        result.append(item)
    if not any(p['markdown'].strip() for p in result):
        raise ValueError('OCR returned an empty transcription')
    return {'legacy': False, 'pages': result}


def slug(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:80] or 'unknown'


def filename(page, capture, index):
    number = page['page_number']
    label = number.zfill(4) if number and number.isascii() and number.isdigit() else slug(number) if number else 'unnumbered'
    chapter = slug(page.get('chapter') or 'unknown-chapter')
    # Capture/side suffix prevents duplicate or absent printed numbers overwriting text.
    return f'page-{label}__{chapter}__{capture}-{index + 1}.md'


def reindex(book, link_pages=False):
    """Resolve chapters and filenames before linking, preserving external edits."""
    chapter = None
    previous = None
    output = book / 'markdown'
    records = []
    entries = []
    for photo in sorted(book.glob('[0-9]*.jpg')):
        if previous is None or int(photo.stem) != previous + 1:
            chapter = None
        previous = int(photo.stem)
        record = read(photo)
        if record is None or photo.with_suffix('.stale').exists():
            chapter = None
            continue
        before = json.loads(json.dumps(record))
        for index, page in enumerate(record['pages']):
            chapter = page.get('chapter_seen') or chapter
            page['chapter'] = chapter
            page['filename'] = filename(page, photo.stem, index)
            entries.append((f'{photo.stem}:{index}', page))
        records.append((photo, record, before))
    targets = page_links.unique_targets(entries)
    filenames = {key: page['filename'] for key, page in entries}
    changed = 0
    for photo, record, before in records:
        output.mkdir(exist_ok=True)
        backed_up = False
        for page, old_page in zip(record['pages'], before['pages']):
            text = page_links.link_text(page['markdown'], targets, filenames,
                                        page.get('chapter'), detect=link_pages)
            if text != page['markdown']:
                changed += 1
                if not backed_up:
                    atomic_json(photo.parent / '.ocr' / 'history' / f'{photo.stem}-{time.time_ns()}.json', before)
                    backed_up = True
                page['markdown'] = text
            target = output / page['filename']
            if not target.exists() or target.read_text(encoding='utf-8') != page['markdown']:
                temp = target.with_suffix('.tmp')
                temp.write_text(page['markdown'], encoding='utf-8')
                temp.replace(target)
        atomic_json(record_path(photo), record)
        for page, old_page in zip(record['pages'], before['pages']):
            old = old_page.get('filename')
            if old and old != page['filename'] and Path(old).name == old:
                (output / old).unlink(missing_ok=True)
    return {'changed_pages': changed}


def save(photo, value, *, recover_numbers=True):
    value = validate(value, recover_numbers=recover_numbers)
    old = read(photo)
    if old:
        atomic_json(photo.parent / '.ocr' / 'history' / f'{photo.stem}-{time.time_ns()}.json', old)
    atomic_json(record_path(photo), value)
    photo.with_suffix('.stale').unlink(missing_ok=True)
    try:
        reindex(photo.parent)
    except Exception:
        # A partial filesystem write must not be reported as successful OCR.
        photo.with_suffix('.stale').touch()
        raise
    # Remove superseded generated names only after new files and metadata are saved.
    current = {p['filename'] for p in read(photo)['pages']}
    for page in (old or {}).get('pages', []):
        name = page.get('filename')
        if name and name not in current and Path(name).name == name:
            (photo.parent / 'markdown' / name).unlink(missing_ok=True)


def prompt_context(photo):
    context = {'previous_chapter': None, 'previous_page': None}
    photos = sorted(photo.parent.glob('[0-9]*.jpg'))
    position = photos.index(photo)
    if position == 0:
        return context
    previous = photos[position - 1]
    if int(previous.stem) + 1 != int(photo.stem) or previous.with_suffix('.stale').exists():
        return context
    record = read(previous)
    if record:
        page = record['pages'][-1]
        context['previous_chapter'] = page.get('chapter')
        context['previous_page'] = {key: page.get(key) for key in ('page_number', 'chapter', 'filename')}
    return context


def context(photo):
    return prompt_context(photo)['previous_chapter']


def combined(photo):
    record = read(photo)
    return '\n\n---\n\n'.join(p['markdown'].strip() for p in record['pages']) + '\n' if record else ''


def revision(photo):
    record = read(photo)
    content = [{k: p.get(k) for k in ('markdown', 'page_number', 'chapter_seen', 'figures')}
               for p in record['pages']] if record else []
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
