"""Bounded HTTP OCR transport and adapters for Ollama and llama.cpp."""
import base64
from contextlib import contextmanager
import http.client
import json
import socket
import time
from urllib.parse import urlsplit, urlunsplit

from codex_stream import CodexError, OCRTimeout, OCRContentFilterError, partial_pages


DEFAULT_URLS = {'ollama': 'http://127.0.0.1:11434', 'llamacpp': 'http://127.0.0.1:8080'}
MAX_RESPONSE = 2 * 1024 * 1024


def validate_url(provider, value):
    if provider not in DEFAULT_URLS:
        raise ValueError('Choose Ollama or llama.cpp for a local server')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Enter the local model server URL')
    value = value.strip()
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Server URL cannot contain whitespace')
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError('Enter a valid HTTP or HTTPS server URL') from None
    if (url.scheme not in ('http', 'https') or not url.hostname or
            url.username is not None or url.password is not None or url.query or url.fragment or port == 0):
        raise ValueError('Use an HTTP or HTTPS server URL without credentials, query, or fragment')
    path = url.path.rstrip('/')
    suffix = '/api' if provider == 'ollama' else '/v1'
    if path.endswith(suffix):
        path = path[:-len(suffix)]
    return urlunsplit((url.scheme, url.netloc, path, '', ''))


def validate_model(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('Enter the model name served by your local server')
    return value.strip()


@contextmanager
def request(base, path, payload=None, timeout=900, headers=None, label='Local model server'):
    url = urlsplit(base)
    deadline = time.monotonic() + timeout
    connection_type = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    connection = connection_type(url.hostname, url.port, timeout=min(10, timeout))
    try:
        connection.connect()
        transport = connection.sock
        transport.settimeout(max(.001, deadline - time.monotonic()))
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request('POST' if body is not None else 'GET', url.path + path, body,
                           {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', **(headers or {})})
        transport.settimeout(max(.001, deadline - time.monotonic()))
        with connection.getresponse() as response:
            if response.status != 200:
                # Do not echo an arbitrary server response, which may include the image.
                hint = {401: 'Check the API key.', 402: 'Check the account credit balance.',
                        403: 'Check account permissions and provider restrictions.',
                        429: 'Rate limit reached; wait before trying again.'}.get(response.status,
                        'Check the selected model and structured-output support.')
                raise CodexError(f'{label} returned HTTP {response.status}. {hint}',
                                 retryable=response.status in (502, 503, 504))
            yield response, transport, deadline
    except (socket.timeout, TimeoutError):
        raise OCRTimeout(f'{label} exceeded the time limit for this capture.') from None
    except (OSError, http.client.HTTPException):
        raise CodexError(f'Could not communicate with {label}. '
                         'Check that it is reachable from the Book-Be-Gone computer.', retryable=True) from None
    finally:
        connection.close()


def get_json(base, path, headers=None, label='Local model server', max_size=MAX_RESPONSE):
    with request(base, path, timeout=15, headers=headers, label=label) as (response, transport, deadline):
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OCRTimeout(f'{label} did not return its model list in time.')
            transport.settimeout(remaining)
            chunk = response.read1(65536)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_size:
                raise CodexError(f'{label} returned an oversized model list.')
    try:
        return json.loads(data)
    except ValueError:
        raise CodexError(f'{label} returned an invalid model list.') from None


def models(provider, server_url):
    base = validate_url(provider, server_url)
    path = '/api/tags' if provider == 'ollama' else '/v1/models'
    value = get_json(base, path)
    try:
        entries = value['models' if provider == 'ollama' else 'data']
        if not isinstance(entries, list):
            raise ValueError()
        names = [validate_model(item['name' if provider == 'ollama' else 'id']) for item in entries]
    except (ValueError, TypeError, KeyError):
        raise CodexError('Local model server returned an invalid model list. Check the server type and URL.') from None
    return {'models': [{'id': name, 'name': name} for name in dict.fromkeys(names)]}


def run(image, model, prompt, schema, server_url, provider, on_update, timeout=900, progress_timeout=120):
    base = validate_url(provider, server_url)
    model = validate_model(model)
    encoded = base64.b64encode(image.read_bytes()).decode('ascii')
    if provider == 'ollama':
        path = '/api/chat'
        payload = {'model': model, 'stream': True, 'format': schema,
                   'messages': [{'role': 'user', 'content': prompt, 'images': [encoded]}]}
    else:
        path = '/v1/chat/completions'
        payload = {'model': model, 'stream': True,
                   'response_format': {'type': 'json_object', 'schema': schema},
                   'messages': [{'role': 'user', 'content': [
                       {'type': 'text', 'text': prompt},
                       {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + encoded}}]}]}
    return stream(base, path, payload, on_update, timeout, progress_timeout, protocol=provider)


def stream(base, path, payload, on_update, timeout=900, progress_timeout=120,
           protocol='sse', headers=None, label='Local model'):
    on_update(f'Connecting to {label}', None)
    raw = ''
    last_progress = None
    longest_pages = [0, 0]
    finished = False
    with request(base, path, payload, timeout, headers=headers, label=label) as (response, transport, deadline):
        on_update(f'Reading the image with {label}', None)
        pending = b''
        received = 0
        while not finished:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OCRTimeout(f'{label} exceeded the time limit for this capture.')
            if last_progress is not None:
                remaining = min(remaining, progress_timeout - (time.monotonic() - last_progress))
                if remaining <= 0:
                    raise CodexError(f'{label} made no new transcription progress; stopped this capture.')
            transport.settimeout(remaining)
            try:
                chunk = response.read1(65536)
            except socket.timeout:
                if last_progress is not None and time.monotonic() - last_progress >= progress_timeout:
                    raise CodexError(f'{label} made no new transcription progress; stopped this capture.') from None
                raise
            received += len(chunk)
            if received > MAX_RESPONSE:
                raise CodexError(f'{label} output exceeded the size limit; stopped this capture.')
            pending += chunk
            lines = pending.split(b'\n')
            pending = lines.pop()
            if not chunk and pending:
                lines.append(pending)
                pending = b''
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if protocol != 'ollama':
                    if not line.startswith(b'data:'):
                        continue
                    line = line[5:].strip()
                    if line == b'[DONE]':
                        raise CodexError(f'{label} stream ended without a completion reason; partial OCR was not saved.')
                try:
                    event = json.loads(line)
                    if event.get('error'):
                        if any(choice.get('finish_reason') == 'content_filter' for choice in event.get('choices', [])):
                            raise OCRContentFilterError()
                        code = (event['error'].get('code') if isinstance(event['error'], dict) else None)
                        detail = f' (code {code})' if type(code) is int else ''
                        raise CodexError(f'{label} reported a generation error{detail}. Check model access and provider status.')
                    if protocol == 'ollama':
                        message = event.get('message') or {}
                        delta = message.get('content', '')
                        reason = event.get('done_reason')
                        finished = event.get('done') is True
                    else:
                        choices = event.get('choices', [])
                        if not choices:
                            continue
                        choice = choices[0]
                        message = choice.get('delta') or {}
                        delta = message.get('content') or ''
                        reason = choice.get('finish_reason')
                        finished = reason is not None
                    if message.get('tool_calls'):
                        raise CodexError(f'{label} requested tools instead of transcribing the image.')
                    if message.get('refusal'):
                        raise CodexError(f'{label} declined this transcription. Partial OCR was not saved.')
                    if not isinstance(delta, str):
                        raise ValueError()
                except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                    raise CodexError(f'{label} returned an invalid streaming response.') from None
                if delta:
                    raw += delta
                    now = time.monotonic()
                    if last_progress is None:
                        last_progress = now
                    pages = partial_pages(raw)
                    for index, page in enumerate(pages or []):
                        if len(page['markdown']) > longest_pages[index]:
                            longest_pages[index] = len(page['markdown'])
                            last_progress = now
                    on_update(f'Transcribing with {label}', raw)
                if finished:
                    if reason == 'content_filter':
                        raise OCRContentFilterError()
                    if reason not in (None, 'stop'):
                        raise CodexError(f'{label} stopped before completing OCR. Check its output and context limits.')
                    break
            if not chunk and not finished:
                raise CodexError(f'{label} stream ended without completion; partial OCR was not saved.', retryable=True)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get('pages'), list):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise CodexError(f'{label} did not return valid page JSON. Use a vision model with structured-output support.') from None
