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


def validate(value):
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
                raise ValueError('Invalid ' + key)
            item[key] = field.strip() or None if isinstance(field, str) else None
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


def save(photo, value):
    value = validate(value)
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


def context(photo):
    photos = sorted(photo.parent.glob('[0-9]*.jpg'))
    position = photos.index(photo)
    if position == 0:
        return None
    previous = photos[position - 1]
    if int(previous.stem) + 1 != int(photo.stem) or previous.with_suffix('.stale').exists():
        return None
    record = read(previous)
    return record['pages'][-1].get('chapter') if record else None


def combined(photo):
    record = read(photo)
    return '\n\n---\n\n'.join(p['markdown'].strip() for p in record['pages']) + '\n' if record else ''


def revision(photo):
    record = read(photo)
    content = [{k: p.get(k) for k in ('markdown', 'page_number', 'chapter_seen', 'figures')}
               for p in record['pages']] if record else []
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
