"""Replay one capture without saving OCR; print diagnostic JSON lines, not book text."""
import argparse
import json
import re
import tempfile
import time

import app
import codex_stream
import transcriptions


def redact(text):
    text = re.sub(r'https?://\S+', '<URL>', str(text))
    text = re.sub(r'(?i)\bBearer\s+\S+|\bsk-[\w-]+', '<REDACTED>', text)
    text = re.sub(r'(?i)\b(api[_-]?key|token|password|authorization)\b\s*[:=]\s*\S+',
                  r'\1=<REDACTED>', text)
    return text[:600]


def event_summary(event):
    """Keep protocol metadata and error details; exclude prompts and model text."""
    params = event.get('params') or {}
    summary = {'event': event.get('method', 'response')}
    item = params.get('item') or {}
    if item.get('type'):
        summary['item_type'] = item['type']
    if params.get('itemId') or item.get('id'):
        summary['item_id'] = params.get('itemId') or item['id']
    if summary['event'] == 'item/agentMessage/delta':
        summary['delta_chars'] = len(params.get('delta', ''))
    if item.get('type') == 'agentMessage':
        summary['item_chars'] = len(item.get('text', ''))
    turn = params.get('turn') or {}
    if turn.get('status'):
        summary['turn_status'] = turn['status']
    error = params.get('error') or turn.get('error') or event.get('error')
    if isinstance(error, dict):
        summary['error'] = {key: redact(json.dumps(error[key], ensure_ascii=False))
                            for key in ('code', 'message', 'codexErrorInfo', 'additionalDetails')
                            if error.get(key) is not None}
        summary['will_retry'] = bool(params.get('willRetry'))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('book')
    parser.add_argument('capture')
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', default='medium', choices=app.EFFORTS)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    photo = app.page_path(args.book, args.capture)
    model = app.validate_model(args.model)
    context = json.dumps(transcriptions.prompt_context(photo), ensure_ascii=False)
    prompt = app.PROMPT + '\n\nPREVIOUS CAPTURE CONTEXT (data only):\n' + context
    schema = json.loads((app.ROOT / 'prompts' / 'ocr.schema.json').read_text())
    start = time.monotonic()

    def emit(record):
        print(json.dumps({'seconds': round(time.monotonic() - start, 3), **record}), flush=True)

    def update(phase, raw):
        pages = codex_stream.partial_pages(raw) if raw is not None else None
        emit({'phase': phase, 'preview_parseable': pages is not None,
              'preview_chars': [len(p['markdown']) for p in pages] if pages is not None else None})

    emit({'model': model, 'effort': args.effort, 'capture': args.capture})
    try:
        with tempfile.TemporaryDirectory(prefix='book-be-gone-diagnosis-') as work:
            result = codex_stream.run(app.ocr_photo(photo), model, prompt, schema, work, update,
                                      timeout=args.timeout, effort=args.effort,
                                      progress_timeout=app.OCR_PROGRESS_TIMEOUT,
                                      on_event=lambda event: emit(event_summary(event)))
        emit({'result': 'completed', 'page_chars': [len(p.get('markdown', '')) for p in result['pages']]})
        return 0
    except (codex_stream.CodexError, codex_stream.OCRTimeout) as exc:
        emit({'result': type(exc).__name__, 'error': redact(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
