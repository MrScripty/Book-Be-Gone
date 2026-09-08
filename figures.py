"""Figure crops from immutable OCR sources, plus portable Markdown representations."""
import hashlib
import io
import math
from pathlib import Path
import re
import uuid

from PIL import Image

ASSET = re.compile(r'[0-9]{6}-[12]-figure-[0-9]+-[a-f0-9]{32}\.png')
SOURCE = re.compile(r'[a-f0-9]{64}\.jpg')


def bounds(value):
    if (not isinstance(value, list) or len(value) != 4 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('Figure bounds must be [left, top, right, bottom] between 0 and 1')
    left, top, right, bottom = value
    if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
        raise ValueError('Figure crop must be a nonempty rectangle inside the image')
    return value


def validate(items):
    if not isinstance(items, list) or len(items) > 50:
        raise ValueError('Expected a list of up to 50 figures per page')
    result = []
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid figure')
        identifier = item.get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'figure-[1-9][0-9]*', identifier) or identifier in ids:
            raise ValueError('Each figure needs a unique figure-N identifier on its page')
        ids.add(identifier)
        figure = {'id': identifier, 'bbox': bounds(item.get('bbox'))}
        for key in ('description', 'representation'):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 50000:
                raise ValueError('Each figure needs a description and text representation')
            figure[key] = value.strip()
        if item.get('format') not in ('mermaid', 'text'):
            raise ValueError('Figure representation must be mermaid or text')
        figure['format'] = item['format']
        for key, pattern in [('asset', ASSET), ('source', SOURCE)]:
            if key in item:
                if not isinstance(item[key], str) or not pattern.fullmatch(item[key]):
                    raise ValueError('Invalid figure ' + key)
                figure[key] = item[key]
        result.append(figure)
    return result


def write_crop(book, source, bbox, prefix):
    with Image.open(book / '.ocr' / 'sources' / source) as image:
        width, height = image.size
        left, top, right, bottom = bounds(bbox)
        box = (math.floor(left * width), math.floor(top * height),
               math.ceil(right * width), math.ceil(bottom * height))
        output = io.BytesIO()
        image.crop(box).save(output, format='PNG')
    name = prefix + '-' + uuid.uuid4().hex + '.png'
    folder = book / 'markdown' / 'assets'
    folder.mkdir(parents=True, exist_ok=True)
    # Unique names preserve old crops in history and prevent stale browser images.
    (folder / name).write_bytes(output.getvalue())
    return name


def block(figure):
    description = figure['description']
    alt = re.sub(r'[\[\]\\\n\r]', ' ', description)
    # Keep model-generated description as prose, never executable Markdown/HTML.
    prose = re.sub(r'([\\`*_{}\[\]()<>#!|])', r'\\\1', description)
    representation = figure['representation']
    fence = '`' * max(3, 1 + max((len(m[0]) for m in re.finditer(r'`+', representation)), default=0))
    return (f'![{alt}](assets/{figure["asset"]})\n\n'
            f'Figure description (generated): {prose}\n\n'
            f'Text representation (generated):\n\n{fence}{figure["format"]}\n'
            f'{representation}\n{fence}')


def prepare(photo, source_photo, value):
    """Resolve OCR markers only after validating the entire response."""
    for page in value['pages']:
        for figure in page.get('figures', []):
            marker = '{{' + figure['id'] + '}}'
            if page['markdown'].count(marker) != 1:
                raise ValueError('Each figure marker must appear exactly once in its page Markdown')
        expected = {'{{' + f['id'] + '}}' for f in page.get('figures', [])}
        if set(re.findall(r'\{\{figure-[0-9]+\}\}', page['markdown'])) != expected:
            raise ValueError('Figure marker has no matching figure data')
    if not any(page.get('figures') for page in value['pages']):
        return value
    raw = source_photo.read_bytes()
    source = hashlib.sha256(raw).hexdigest() + '.jpg'
    folder = photo.parent / '.ocr' / 'sources'
    folder.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
    (folder / source).write_bytes(raw)
    for index, page in enumerate(value['pages']):
        for figure in page.get('figures', []):
            figure['source'] = source
            figure['asset'] = write_crop(photo.parent, source, figure['bbox'], f'{photo.stem}-{index + 1}-{figure["id"]}')
            page['markdown'] = page['markdown'].replace('{{' + figure['id'] + '}}', block(figure))
    return value


def recrop(photo, record, index, identifier, bbox):
    if type(index) is not int or not 0 <= index < len(record['pages']):
        raise ValueError('Invalid printed page')
    page = record['pages'][index]
    figure = next((f for f in page.get('figures', []) if f['id'] == identifier), None)
    if not figure or not figure.get('source') or not figure.get('asset'):
        raise ValueError('Figure not found')
    old = 'assets/' + figure['asset']
    if old not in page['markdown']:
        raise ValueError('The image link was removed from the Markdown; restore it before adjusting the crop')
    asset = write_crop(photo.parent, figure['source'], bounds(bbox), f'{photo.stem}-{index + 1}-{identifier}')
    figure.update(bbox=bbox, asset=asset)
    page['markdown'] = page['markdown'].replace(old, 'assets/' + asset)
