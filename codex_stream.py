"""One ephemeral Codex turn, with live assistant text and bounded cleanup."""
import json
import os
import queue
import signal
import subprocess
import threading
import time


class OCRTimeout(TimeoutError):
    pass


class CodexError(RuntimeError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class OCRContentFilterError(CodexError):
    def __init__(self):
        super().__init__('The model provider stopped this transcription with its content filter. '
                         'OCR cannot complete this response; automatic retries have been stopped.')


def check_content_filter(error):
    # Codex can wrap a filtered response as a retryable stream disconnection.
    # The actual reason is in additionalDetails, not the "Reconnecting" message.
    detail = json.dumps(error).lower()
    if 'content_filter' in detail or 'contentfilter' in detail:
        raise OCRContentFilterError()


def partial_pages(text):
    """Decode complete or still-streaming JSON strings for display only.

    These provisional values are never used to mark a capture complete.
    """
    stack = []
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            stack.append(']' if char == '[' else '}')
        elif char in ']}':
            if not stack or stack.pop() != char:
                return None
    candidate = text
    if quoted:
        if escaped:
            candidate = candidate[:-1]
        candidate += '"'
    else:
        candidate = candidate.rstrip().removesuffix(',')
    candidate += ''.join(reversed(stack))
    try:
        value = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get('pages'), list):
        return None
    return [{'page_number': p.get('page_number') if isinstance(p.get('page_number'), str) else None,
             'markdown': p.get('markdown', '') if isinstance(p.get('markdown', ''), str) else ''}
            for p in value['pages'] if isinstance(p, dict)][:2]


def run(image, model, prompt, schema, cwd, on_update, timeout=900, effort='low', progress_timeout=120,
        on_event=None):
    """Return final structured JSON; on_update receives only assistant output.

    Reasoning events are used as activity signals, never exposed as OCR text.
    """
    process = subprocess.Popen(['codex', 'app-server', '--stdio'], cwd=cwd,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                               errors='replace', bufsize=1, start_new_session=True)
    messages = queue.Queue()

    def read_stdout():
        try:
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    request_id = 0
    thread_id = None
    output = {}
    finished = None
    preview_item = None
    completed_items = set()
    completed_drafts = {}
    last_progress = None
    longest_pages = [0, 0]
    preview_lengths = []

    def track_progress(raw):
        nonlocal last_progress
        now = time.monotonic()
        if last_progress is None:
            last_progress = now
        pages = partial_pages(raw)
        for index, page in enumerate(pages or []):
            size = len(page['markdown'])
            if size > longest_pages[index]:
                longest_pages[index] = size
                last_progress = now
        return pages

    def send(value):
        try:
            process.stdin.write(json.dumps(value) + '\n')
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise CodexError('Codex connection closed unexpectedly.', retryable=True) from exc

    def receive():
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OCRTimeout(f'Codex exceeded the {timeout:g}-second limit for this capture.')
            if last_progress is not None:
                progress_remaining = progress_timeout - (time.monotonic() - last_progress)
                if progress_remaining <= 0:
                    raise CodexError(f'Codex made no new transcription progress for {progress_timeout:g} seconds. '
                                     'Stopped this capture; try another OCR model.')
                remaining = min(remaining, progress_remaining)
            try:
                message = messages.get(timeout=min(remaining, .25))
            except queue.Empty:
                continue
            if message is None:
                raise CodexError('Codex exited before finishing the capture. Check your Codex login if this repeats.', retryable=True)
            if on_event is not None:
                on_event(message)
            return message

    def notify(message):
        nonlocal finished, preview_item, preview_lengths
        method = message.get('method', '')
        params = message.get('params') or {}
        if 'id' in message and method:
            # Transcription needs no tool approvals or user-interaction requests.
            send({'id': message['id'], 'error': {'code': -32601, 'message': 'Book-Be-Gone only supports image transcription.'}})
            raise CodexError('Codex requested an interactive action instead of transcribing the image. Retry this capture.')
        if thread_id and params.get('threadId') not in (None, thread_id):
            return
        if method == 'item/agentMessage/delta':
            item_id = params['itemId']
            new_item = item_id not in output
            output[item_id] = output.get(item_id, '') + params['delta']
            pages = track_progress(output[item_id])
            lengths = [len(p['markdown']) for p in pages or []]
            # A turn can emit a replacement message. Its opening JSON must not
            # erase the previous preview. Resume streaming when every visible
            # page has caught up; a completed item may legitimately be shorter.
            caught_up = (len(lengths) >= len(preview_lengths)
                         and all(size >= old for size, old in zip(lengths, preview_lengths)))
            if preview_item in (None, item_id) or caught_up:
                on_update('Transcribing', output[item_id])
                if pages and any(p['markdown'] for p in pages):
                    preview_item = item_id
                    preview_lengths = lengths
            elif new_item:
                on_update('Updating transcription', None)
        elif method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
            item = params['item']
            output[item['id']] = item.get('text', '')
            if item['id'] in completed_items:
                return
            completed_items.add(item['id'])
            try:
                value = json.loads(output[item['id']])
            except ValueError:
                value = None
            pages = track_progress(output[item['id']])
            if isinstance(value, dict) and pages and any(p['markdown'] for p in pages):
                fingerprint = json.dumps(value, sort_keys=True, ensure_ascii=False)
                completed_drafts[fingerprint] = completed_drafts.get(fingerprint, 0) + 1
                if completed_drafts[fingerprint] >= 3:
                    raise CodexError('Codex repeated the same transcription three times without finishing. '
                                     'Stopped this capture; try another OCR model.')
                preview_item = item['id']
                preview_lengths = [len(p['markdown']) for p in pages]
                on_update('Waiting for OCR to finish', output[item['id']])
        elif method == 'turn/completed':
            finished = params['turn']
        elif method == 'error':
            error = params.get('error') or {}
            check_content_filter(error)
            if params.get('willRetry'):
                on_update('Codex is reconnecting', None)
            else:
                message = str(error.get('message') or 'Codex could not complete this capture.')[:400]
                retryable = any(word in message.lower() for word in ['timeout', 'timed out', 'connection', 'stream', '503', '502', 'temporar'])
                raise CodexError(message, retryable)
        elif method.startswith('item/reasoning/') and not output:
            on_update('Reading the image', None)

    def request(method, params):
        nonlocal request_id
        request_id += 1
        send({'id': request_id, 'method': method, 'params': params})
        while True:
            message = receive()
            if message.get('id') == request_id and 'method' not in message:
                if message.get('error'):
                    check_content_filter(message['error'])
                    raise CodexError(str(message['error'].get('message', 'Codex request failed.'))[:400])
                return message.get('result', {})
            notify(message)

    try:
        on_update('Connecting to Codex', None)
        request('initialize', {'clientInfo': {'name': 'book-be-gone', 'version': '0.1.0'}})
        send({'method': 'initialized', 'params': {}})
        thread = request('thread/start', {
            'model': model, 'cwd': cwd, 'ephemeral': True, 'sandbox': 'read-only',
            'approvalPolicy': 'never', 'config': {'model_reasoning_effort': effort},
            'developerInstructions': 'Transcribe the supplied image only. Do not use tools or request user input.',
        })
        thread_id = thread['thread']['id']
        on_update('Reading the image', None)
        request('turn/start', {
            'threadId': thread_id, 'model': model, 'effort': effort, 'outputSchema': schema,
            'input': [{'type': 'text', 'text': prompt}, {'type': 'localImage', 'path': str(image)}],
        })
        while finished is None:
            notify(receive())
        if finished.get('status') != 'completed':
            check_content_filter(finished.get('error'))
            message = (finished.get('error') or {}).get('message') or 'Codex stopped before completing the capture.'
            raise CodexError(str(message)[:400], retryable=finished.get('status') == 'interrupted')
        # Final items are authoritative; some versions omit them from this notification.
        final = [i.get('text', '') for i in finished.get('items', []) if i.get('type') == 'agentMessage']
        candidates = final or list(output.values())
        for text in reversed(candidates):
            try:
                result = json.loads(text)
                if isinstance(result, dict) and isinstance(result.get('pages'), list):
                    return result
            except ValueError:
                continue
        raise CodexError('Codex finished without valid page JSON. Retry this capture.')
    finally:
        # Terminate the whole child session, including tools, on timeout or completion.
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            except ProcessLookupError:
                process.wait(timeout=3)
        process.stdin.close()
        reader.join(timeout=1)
        process.stdout.close()
