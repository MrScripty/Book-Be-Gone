"""Book-Be-Gone: local webcam capture and Codex transcription."""
import base64
import html
import io
import zipfile
import figures
import page_links
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid
import time
import codex_stream
import local_ocr
import openrouter_ocr
from markdown_it import MarkdownIt
import transcriptions
import ocr_review
import ocr_labels
import review_render
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BOOK_BE_GONE_DATA", os.environ.get("PAGESCRIBE_DATA", ROOT / "data"))).resolve()
MODEL = os.environ.get("BOOK_BE_GONE_MODEL", os.environ.get("PAGESCRIBE_MODEL", "gpt-5.6-luna"))
LOCK = threading.RLock()
STATUS = {"running": False, "book": None, "page": None, "error": None,
          "phase": "Idle", "live_pages": [], "last_saved": None, "completed": 0,
          "remaining": 0, "total": 0, "processed": 0, "attempt": 0,
          "capture_started": None, "revision": 0}
OCR_TIMEOUT = float(os.environ.get("BOOK_BE_GONE_OCR_TIMEOUT", os.environ.get("PAGESCRIBE_OCR_TIMEOUT", "900")))
OCR_PROGRESS_TIMEOUT = float(os.environ.get("BOOK_BE_GONE_OCR_PROGRESS_TIMEOUT", "120"))
OCR_ATTEMPTS = 2
API_VERSION = 14
PROMPT = (ROOT / "prompts" / "ocr.md").read_text(encoding="utf-8")
RENDERER = MarkdownIt("js-default")


def render_image(tokens, index, options, env):
    token = tokens[index]
    source = token.attrGet('src') or ''
    name = source.removeprefix('assets/')
    book = env.get('book')
    if not source.startswith('assets/') or not figures.ASSET.fullmatch(name) or not book:
        return html.escape(token.content)
    return f'<img src="/api/asset/{book}/{name}" alt="{html.escape(token.content, quote=True)}" loading="lazy">'


RENDERER.renderer.rules['image'] = render_image


def render_link(tokens, index, options, env):
    token = tokens[index]
    href = token.attrGet('href') or ''
    book = env.get('book')
    key = page_links.file_key(href)
    if book and key:
        capture, side = key.split(':')
        token.attrSet('href', f'#book-{book}/page-{capture}-{int(side) + 1}')
    elif book and re.fullmatch(r'page:(?:[0-9]+|[ivxlcdmIVXLCDM]+)', href):
        token.attrSet('href', f'#book-{book}/number-{href[5:]}')
    return RENDERER.renderer.renderToken(tokens, index, options, env)


RENDERER.renderer.rules['link_open'] = render_link


def render_markdown(text, book=None):
    return RENDERER.render(text, env={'book': book})


def export_book(book):
    entries = pages(book)
    if not entries or any(not p['done'] for p in entries):
        raise ValueError("Transcribe every page before exporting")
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        combined = []
        assets = set()
        for entry in entries:
            photo = page_path(book, entry['id'])
            record = transcriptions.read(photo)
            combined.append(transcriptions.combined(photo).strip())
            for page in record['pages']:
                archive.writestr(page['filename'], page['markdown'])
                assets.update(re.findall(r'assets/(' + figures.ASSET.pattern + r')', page['markdown']))
        archive.writestr('book.md', '\n\n'.join(combined) + '\n')
        for name in sorted(assets):
            archive.write(book_path(book) / 'markdown' / 'assets' / name, 'assets/' + name)
    return output.getvalue()


def validate_model(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value):
        raise ValueError("Enter a valid OCR model identifier")
    return value


EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')


def validate_effort(model, effort):
    option = next((m for m in model_options()['models'] if m['id'] == model), None)
    allowed = option['efforts'] if option else EFFORTS
    if not isinstance(effort, str) or effort not in allowed:
        raise ValueError("Choose a supported thinking level for this model")
    return effort


def model_options():
    models = {MODEL: {"id": MODEL, "name": MODEL, "efforts": list(EFFORTS[:4])}}
    cache = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "models_cache.json"
    try:
        for item in json.loads(cache.read_text()).get("models", []):
            if item.get("visibility") != "list" or "image" not in item.get("input_modalities", []):
                continue
            identifier = validate_model(item.get("slug"))
            levels = [level.get('effort') for level in item.get('supported_reasoning_levels', [])
                      if isinstance(level, dict) and level.get('effort') in EFFORTS]
            models[identifier] = {"id": identifier, "name": item.get("display_name") or identifier,
                                  "efforts": levels or list(EFFORTS[:4])}
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # The default and custom identifiers work without a local model cache.
    return {"default": MODEL, "models": list(models.values())}


def book_path(book):
    if not isinstance(book, str) or not re.fullmatch(r"[a-f0-9]{12}", book):
        raise ValueError("Invalid book ID")
    path = DATA / book
    if not (path / "book.json").is_file():
        raise ValueError("Book not found")
    return path


def page_path(book, page):
    if not isinstance(page, str) or not re.fullmatch(r"[0-9]{6}", page):
        raise ValueError("Invalid page ID")
    path = book_path(book) / f"{page}.jpg"
    if not path.is_file():
        raise ValueError("Page not found")
    return path


def atomic_write(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(data, encoding="utf-8")
    temporary.replace(path)


def pages(book):
    return [{"id": p.stem, "done": transcriptions.read(p) is not None and not p.with_suffix(".stale").exists()}
            for p in sorted(book_path(book).glob("[0-9]*.jpg"))]


def ocr_photo(photo):
    corrected = photo.parent / "corrected" / photo.name
    return corrected if corrected.is_file() else photo


def capture_photo(book, encoded, corrected=None):
    path = book_path(book)
    def decode(value):
        data = base64.b64decode(value, validate=True)
        if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            raise ValueError("Expected a JPEG photo")
        return data
    original = decode(encoded)
    adjusted = decode(corrected) if corrected is not None else None
    number = max((int(p["id"]) for p in pages(book)), default=0) + 1
    if number > 999999:
        raise ValueError("Book is full")
    page = f"{number:06d}"
    photo = path / (page + ".jpg")
    output = path / "corrected" / photo.name
    # Publish the original last: page discovery and OCR cannot see a partial pair.
    if adjusted is not None:
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(adjusted)
    else:
        output.unlink(missing_ok=True)
    temporary = photo.with_suffix(".tmp")
    temporary.write_bytes(original)
    temporary.replace(photo)
    return page


def adjust_photo(book, page, encoded=None):
    if STATUS["running"]:
        raise ValueError("Wait for OCR to finish before adjusting photos")
    photo = page_path(book, page)
    corrected = photo.parent / "corrected" / photo.name
    if encoded is not None:
        data = base64.b64decode(encoded, validate=True)
        if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            raise ValueError("Expected a JPEG photo")
        corrected.parent.mkdir(exist_ok=True)
    # Invalidate OCR before changing its source; preserve the text for reference.
    photo.with_suffix(".stale").touch()
    if encoded is None:
        corrected.unlink(missing_ok=True)
    else:
        temporary = corrected.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(corrected)


def status_snapshot():
    with LOCK:
        snapshot = dict(STATUS)
        snapshot['api_version'] = API_VERSION
        snapshot['openrouter_key_configured'] = bool(os.environ.get('OPENROUTER_API_KEY'))
        snapshot['elapsed'] = int(time.monotonic() - STATUS['capture_started']) if STATUS['capture_started'] and STATUS['running'] else 0
        snapshot['live_pages'] = [dict(p, html=render_markdown(p['markdown'], STATUS['book'])) for p in STATUS['live_pages']]
        return snapshot


def document(book):
    captures = pages(book)
    printed = []
    for capture in captures:
        photo = page_path(book, capture['id'])
        record = transcriptions.read(photo)
        revision = transcriptions.revision(photo)
        entries = record['pages'] if record else [{'page_number': None, 'chapter': None, 'markdown': ''}]
        for index, item in enumerate(entries):
            printed.append(dict(item, key=f"{capture['id']}:{index}", capture=capture['id'],
                                index=index, done=capture['done'], has_text=record is not None,
                                corrected=ocr_photo(photo) != photo, revision=revision,
                                review_pending=ocr_review.path(photo).exists(),
                                html=render_markdown(item['markdown'], book)))
    return {'captures': captures, 'pages': printed}


def save_correction(book, body):
    photo = page_path(book, body.get('page'))
    if STATUS['running'] and STATUS['book'] == book:
        pending = transcriptions.read(photo) is None or photo.with_suffix('.stale').exists()
        if STATUS['page'] in (None, photo.stem) or pending:
            raise ValueError('This capture is queued or being transcribed. You can edit other completed pages while OCR runs.')
    if body.get('revision') is not None and body['revision'] != transcriptions.revision(photo):
        raise ValueError('This capture changed since you opened it. Your edits are still in the editor; reload the page before saving over newer text.')
    if 'printed_index' in body:
        record = transcriptions.read(photo)
        index = body['printed_index']
        if not record or type(index) is not int or not 0 <= index < len(record['pages']):
            raise ValueError('Select a transcribed printed page to edit')
        item = record['pages'][index]
        item['markdown'] = body.get('markdown')
        item['page_number'] = body.get('page_number')
        if 'chapter_seen' in body:
            item['chapter_seen'] = body['chapter_seen']
        transcriptions.save(photo, record, recover_numbers=False)
    elif 'pages' in body:
        transcriptions.save(photo, {'pages': body['pages']}, recover_numbers=False)
    else:
        record = transcriptions.read(photo)
        if record and len(record['pages']) > 1:
            raise ValueError('Refresh Book-Be-Gone to edit each printed page separately')
        item = dict(record['pages'][0]) if record else {'page_number': None, 'chapter_seen': None}
        item['markdown'] = body.get('text')
        transcriptions.save(photo, {'pages': [item]}, recover_numbers=False)


def ocr_settings(body):
    provider = body.get('provider', 'codex')
    if provider == 'codex':
        model = validate_model(body.get('model', MODEL))
        return provider, model, validate_effort(model, body.get('effort', 'low')), None
    if provider == 'openrouter':
        return provider, validate_model(body.get('model')), None, None
    server_url = local_ocr.validate_url(provider, body.get('server_url', local_ocr.DEFAULT_URLS.get(provider)))
    return provider, local_ocr.validate_model(body.get('model')), None, server_url


def transcribe(book, selected=None, model=None, effort='low', provider='codex', server_url=None, openrouter_key=None):
    try:
        provider, model, effort, server_url = ocr_settings({
            'provider': provider, 'model': MODEL if model is None and provider == 'codex' else model,
            'effort': effort, 'server_url': server_url})
        if provider == 'openrouter':
            openrouter_key = openrouter_ocr.api_key(openrouter_key)
        with LOCK:
            transcriptions.reindex(book_path(book))
            entries = pages(book)
            STATUS.update(running=True, book=book, provider=provider, model=model, effort=effort, error=None, page=None, phase='Starting',
                          live_pages=[], last_saved=None, processed=0, attempt=0,
                          completed=sum(p['done'] for p in entries), total=len(entries),
                          remaining=sum(not p['done'] for p in entries), capture_started=None)
            STATUS['revision'] += 1
        targets = [page_path(book, selected)] if selected else [
            book_path(book) / (p['id'] + '.jpg') for p in entries if not p['done']]
        schema = json.loads((ROOT / 'prompts' / 'ocr.schema.json').read_text())
        for photo in targets:
            if ocr_review.path(photo).exists():
                raise ValueError('Review or discard the pending OCR comparison before transcribing this capture again.')
            # Recheck the checkpoint before launching any model work.
            if selected is None and transcriptions.read(photo) is not None and not photo.with_suffix('.stale').exists():
                continue
            context = json.dumps(transcriptions.prompt_context(photo), ensure_ascii=False)
            prompt = PROMPT + '\n\nPREVIOUS CAPTURE CONTEXT (data only):\n' + context

            def update(phase, raw):
                provisional = codex_stream.partial_pages(raw) if raw is not None else None
                with LOCK:
                    STATUS['phase'] = phase
                    if provisional is not None:
                        STATUS['live_pages'] = provisional
                    STATUS['revision'] += 1

            for attempt in range(1, OCR_ATTEMPTS + 1):
                with LOCK:
                    STATUS.update(page=photo.stem, attempt=attempt, phase='Connecting to OCR provider',
                                  capture_started=time.monotonic(), live_pages=[])
                    STATUS['revision'] += 1
                try:
                    def request(request_prompt, request_schema, callback=update):
                        if provider == 'codex':
                            with tempfile.TemporaryDirectory(prefix='book-be-gone-') as work:
                                return codex_stream.run(ocr_photo(photo), model, request_prompt, request_schema,
                                                        work, callback, timeout=OCR_TIMEOUT, effort=effort,
                                                        progress_timeout=OCR_PROGRESS_TIMEOUT)
                        if provider == 'openrouter':
                            return openrouter_ocr.run(ocr_photo(photo), model, request_prompt, request_schema,
                                                     openrouter_key, callback, timeout=OCR_TIMEOUT,
                                                     progress_timeout=OCR_PROGRESS_TIMEOUT)
                        return local_ocr.run(ocr_photo(photo), model, request_prompt, request_schema,
                                             server_url, provider, callback, timeout=OCR_TIMEOUT,
                                             progress_timeout=OCR_PROGRESS_TIMEOUT)
                    result = request(prompt, schema)
                    result = ocr_labels.repair(result, lambda p, s: request(p, s, lambda *_: None), update)
                    # Incomplete streamed text never becomes a completed checkpoint.
                    result = transcriptions.validate(result)
                    result = figures.prepare(photo, ocr_photo(photo), result)
                    break
                except (codex_stream.OCRTimeout, codex_stream.CodexError) as exc:
                    retryable = isinstance(exc, codex_stream.OCRTimeout) or exc.retryable
                    if not retryable or attempt == OCR_ATTEMPTS:
                        raise
                    update('Retrying this capture; completed captures are preserved', None)
            with LOCK:
                STATUS['phase'] = 'Saving Markdown'
                if transcriptions.read(photo) is not None:
                    transcriptions.reindex(book_path(book), link_pages=True)
                    ocr_review.propose(photo, result)
                    record = transcriptions.read(photo)
                else:
                    transcriptions.save(photo, result)
                    transcriptions.reindex(book_path(book), link_pages=True)
                    record = transcriptions.read(photo)
                STATUS['live_pages'] = [{'page_number': p['page_number'], 'markdown': p['markdown']} for p in record['pages']]
                STATUS['last_saved'] = {'capture': photo.stem, 'page_numbers': [p['page_number'] for p in record['pages']]}
                entries = pages(book)
                STATUS.update(completed=sum(p['done'] for p in entries),
                              remaining=sum(not p['done'] for p in entries),
                              processed=STATUS['processed'] + 1)
                STATUS['revision'] += 1
        with LOCK:
            transcriptions.reindex(book_path(book), link_pages=True)
            STATUS['phase'] = 'Finished'
    except FileNotFoundError:
        with LOCK:
            detail = 'Codex or a required input file was not found. Check your Codex installation and capture files.' if provider == 'codex' else 'A required OCR input file was not found. Check your capture files.'
            STATUS.update(error=detail, phase='Stopped')
    except Exception as exc:
        with LOCK:
            # Never include the whole command/prompt in a timeout error.
            detail = str(exc)[:500] if not isinstance(exc, TimeoutError) else f'This capture did not finish within {OCR_TIMEOUT:g} seconds after {OCR_ATTEMPTS} attempts.'
            resume = '' if isinstance(exc, codex_stream.OCRContentFilterError) else ' Choose OCR remaining captures to resume.'
            STATUS.update(error=f"Capture {STATUS['page'] or 'unknown'}: {detail} Completed captures are saved.{resume}", phase='Stopped')
    finally:
        with LOCK:
            STATUS['running'] = False
            STATUS['revision'] += 1


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, kind="application/json", status=200):
        if kind == "application/json":
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            parts = urlsplit(self.path).path.strip("/").split("/")
            with LOCK:
                if parts == [""]:
                    return self.reply((ROOT / "frontend" / "dist" / "index.html").read_bytes(), "text/html; charset=utf-8")
                if len(parts) == 2 and parts[0] == 'assets' and re.fullmatch(r'[A-Za-z0-9_-]+\.(?:js|css)', parts[1]):
                    kind = 'text/javascript; charset=utf-8' if parts[1].endswith('.js') else 'text/css; charset=utf-8'
                    return self.reply((ROOT / 'frontend' / 'dist' / 'assets' / parts[1]).read_bytes(), kind)
                if parts == ["api", "books"]:
                    return self.reply([dict(json.loads(p.read_text()), id=p.parent.name)
                                       for p in sorted(DATA.glob("*/book.json"))])
                if parts == ["api", "models"]:
                    return self.reply(model_options())
                if parts == ["api", "status"]:
                    return self.reply(status_snapshot())
                if len(parts) == 3 and parts[:2] == ["api", "book"]:
                    return self.reply(pages(parts[2]))
                if len(parts) == 3 and parts[:2] == ["api", "document"]:
                    return self.reply(document(parts[2]))
                if len(parts) == 4 and parts[:2] == ['api', 'ocr-review']:
                    proposal = ocr_review.read(page_path(parts[2], parts[3]))
                    return self.reply(review_render.render(proposal, lambda text: render_markdown(text, parts[2])) if proposal else None)
                if len(parts) == 4 and parts[:2] in (["api", "asset"], ["api", "figure-source"]):
                    folder = book_path(parts[2])
                    name = parts[3]
                    if parts[1] == 'asset' and figures.ASSET.fullmatch(name):
                        return self.reply((folder / 'markdown' / 'assets' / name).read_bytes(), 'image/png')
                    if parts[1] == 'figure-source' and figures.SOURCE.fullmatch(name):
                        return self.reply((folder / '.ocr' / 'sources' / name).read_bytes(), 'image/jpeg')
                    raise ValueError('Invalid figure filename')
                if len(parts) == 4 and parts[:2] == ["api", "photo"]:
                    return self.reply(ocr_photo(page_path(parts[2], parts[3])).read_bytes(), "image/jpeg")
                if len(parts) == 4 and parts[:2] == ["api", "original"]:
                    return self.reply(page_path(parts[2], parts[3]).read_bytes(), "image/jpeg")
                if len(parts) == 4 and parts[:2] == ["api", "text"]:
                    photo = page_path(parts[2], parts[3])
                    record = transcriptions.read(photo)
                    printed = [dict(p, html=render_markdown(p['markdown'], parts[2])) for p in record['pages']] if record else []
                    return self.reply({"text": transcriptions.combined(photo), "pages": printed,
                                       "revision": transcriptions.revision(photo),
                                       "legacy": bool(record and record.get('legacy')),
                                       "corrected": ocr_photo(photo) != photo})
                if len(parts) == 3 and parts[:2] == ["api", "export"]:
                    return self.reply(export_book(parts[2]), 'application/zip')
            self.reply({"error": "Not found"}, status=404)
        except (ValueError, OSError) as exc:
            self.reply({"error": str(exc)}, status=400)

    def do_POST(self):
        try:
            # Reject browser cross-origin writes and DNS rebinding.
            host = self.headers.get("Host", "")
            if host not in {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}:
                raise ValueError("Invalid host")
            if self.headers.get("Origin", "http://" + host) != "http://" + host:
                raise ValueError("Invalid origin")
            if self.headers.get("Content-Type") != "application/json":
                raise ValueError("Expected JSON")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 48_000_000:
                raise ValueError("Request too large or empty")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected object")
            route = urlsplit(self.path).path
            if route == '/api/local-models':
                return self.reply(local_ocr.models(body.get('provider'), body.get('server_url')))
            if route == '/api/openrouter-models':
                return self.reply(openrouter_ocr.models(openrouter_ocr.api_key(body.get('api_key'))))
            with LOCK:
                if route == "/api/books":
                    title = body.get("title", "")
                    if not isinstance(title, str) or not title.strip() or len(title) > 200:
                        raise ValueError("Enter a title (up to 200 characters)")
                    book = uuid.uuid4().hex[:12]
                    path = DATA / book
                    path.mkdir(parents=True)
                    atomic_write(path / "book.json", json.dumps({"title": title.strip()}))
                    return self.reply({"id": book})
                if route == "/api/render":
                    text = body.get("text")
                    if not isinstance(text, str):
                        raise ValueError("Expected Markdown text")
                    render_book = body.get('book')
                    if render_book is not None:
                        book_path(render_book)
                    return self.reply({"html": render_markdown(text, render_book)})
                book = body.get("book")
                path = book_path(book)
                if route == '/api/ocr-review':
                    if STATUS['running']:
                        raise ValueError('Wait for OCR to finish before resolving a comparison.')
                    ocr_review.resolve(page_path(book, body.get('page')), body.get('id'),
                                       body.get('selected'), discard=body.get('discard') is True)
                    STATUS['revision'] += 1
                    return self.reply({'ok': True})
                if route == "/api/adjust":
                    if "image" not in body and body.get("reset") is not True:
                        raise ValueError("Expected adjusted image or reset")
                    adjust_photo(book, body.get("page"), None if body.get("reset") is True else body["image"])
                    return self.reply({"ok": True})
                if route == "/api/capture":
                    page = capture_photo(book, body.get("image", ""), body.get("corrected"))
                    return self.reply({"page": page})
                if route == "/api/link-pages":
                    if STATUS['running']:
                        raise ValueError('Wait for OCR to finish before linking pages')
                    result = transcriptions.reindex(path, link_pages=True)
                    STATUS['revision'] += 1
                    return self.reply(result)
                if route == "/api/figure":
                    if STATUS['running']:
                        raise ValueError('Wait for OCR to finish before adjusting figure crops')
                    photo = page_path(book, body.get('page'))
                    if body.get('revision') != transcriptions.revision(photo):
                        raise ValueError('This page changed. Close the crop editor and reopen it before saving.')
                    record = transcriptions.read(photo)
                    if not record:
                        raise ValueError('Transcribe this page first')
                    figures.recrop(photo, record, body.get('printed_index'), body.get('figure'), body.get('bbox'))
                    stale = photo.with_suffix('.stale').exists()
                    transcriptions.save(photo, record)
                    if stale:
                        photo.with_suffix('.stale').touch()
                    return self.reply({'ok': True})
                if route == "/api/save":
                    save_correction(book, body)
                    return self.reply({"ok": True})
                if route == "/api/ocr":
                    if STATUS["running"]:
                        raise ValueError("OCR is already running")
                    selected = body.get("page")
                    if selected is not None:
                        page_path(book, selected)
                    provider, model, effort, server_url = ocr_settings(body)
                    key = openrouter_ocr.api_key(body.get('api_key')) if provider == 'openrouter' else None
                    STATUS.update(running=True, book=book, page=None, error=None, provider=provider, model=model, effort=effort)
                    threading.Thread(target=transcribe, args=(book, selected, model, effort, provider, server_url, key), daemon=True).start()
                    return self.reply({"ok": True})
            self.reply({"error": "Not found"}, status=404)
        except (ValueError, OSError, TypeError, codex_stream.CodexError) as exc:
            self.reply({"error": str(exc)}, status=400)


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    for metadata in DATA.glob('*/book.json'):
        transcriptions.reindex(metadata.parent)
    print("Book-Be-Gone: http://localhost:8765", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
