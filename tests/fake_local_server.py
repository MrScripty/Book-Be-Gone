"""Local HTTP fixtures for both OCR protocols; never calls an actual model."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


RESULT = {'pages': [{'page_number': '390', 'chapter_seen': None,
                     'markdown': 'A local transcription — complete.', 'figures': []}]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, None))
        self.server.auth_headers.append(self.headers.get('Authorization'))
        value = {'models': [{'name': 'vision:local'}]} if self.path.endswith('/api/tags') else {'data': [{'id': 'vision.gguf'}]}
        if self.path == '/api/v1/models':
            value = {'data': [
                {'id': 'fixture/vision', 'name': 'Fixture Vision', 'architecture': {'input_modalities': ['text', 'image'], 'output_modalities': ['text']}, 'supported_parameters': ['structured_outputs', 'response_format']},
                {'id': 'fixture/text-only', 'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']}, 'supported_parameters': ['structured_outputs']},
                {'id': 'fixture/no-schema', 'architecture': {'input_modalities': ['image'], 'output_modalities': ['text']}, 'supported_parameters': []}]}
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, body))
        self.server.auth_headers.append(self.headers.get('Authorization'))
        ollama = self.path.endswith('/api/chat')
        mode = self.server.mode
        raw = json.dumps(RESULT, ensure_ascii=False)
        if mode == 'invalid-json':
            raw = 'Not JSON'
        events = []
        if ollama:
            events.append({'message': {'thinking': 'PRIVATE REASONING'}, 'done': False})
        else:
            events.append({'choices': [{'delta': {'reasoning_content': 'PRIVATE REASONING'}, 'finish_reason': None}]})
        for index in range(0, len(raw), 11):
            delta = raw[index:index + 11]
            events.append({'message': {'content': delta}, 'done': False} if ollama else
                          {'choices': [{'delta': {'content': delta}, 'finish_reason': None}]})
        if mode in ('stream-error', 'content-filter'):
            events.append({'error': {'code': 502, 'message': 'DO_NOT_ECHO_PROVIDER_BODY'},
                           'choices': [{'delta': {}, 'finish_reason': 'content_filter' if mode == 'content-filter' else 'error'}]})
        elif mode not in ('disconnect', 'stall'):
            reason = 'length' if mode == 'length' else 'stop'
            events.append({'message': {'content': ''}, 'done': True, 'done_reason': reason} if ollama else
                          {'choices': [{'delta': {}, 'finish_reason': reason}]})
        if mode == 'malformed':
            data = b'not-json\n' if ollama else b'data: not-json\n\n'
        else:
            data = b''.join((('' if ollama else 'data: ') + json.dumps(e, ensure_ascii=False) + ('\n' if ollama else '\n\n')).encode()
                            for e in events)
            if not ollama and mode == 'normal':
                data += b'data: [DONE]\n\n'
            if self.path == '/api/v1/chat/completions':
                data = b': OPENROUTER PROCESSING\n\n' + data
        self.send_response({'http-error': 400, 'unauthorized': 401, 'credits': 402, 'rate-limit': 429, 'redirect': 302}.get(mode, 200))
        if mode == 'redirect':
            self.send_header('Location', '/unexpected-key-destination')
        self.send_header('Content-Type', 'application/x-ndjson' if ollama else 'text/event-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            if mode == 'stall':
                # A valid first draft, then no completion or additional bytes.
                self.wfile.write(data[:-1])
                self.wfile.flush()
                time.sleep(.3)
                self.wfile.write(data[-1:])
            else:
                # Fragment bytes independently of JSON events and UTF-8 characters.
                for index in range(0, len(data), 37):
                    self.wfile.write(data[index:index + 37])
                    self.wfile.flush()
                    time.sleep(.001)
        except (BrokenPipeError, ConnectionResetError):
            pass


def start():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.mode = 'normal'
    server.requests = []
    server.auth_headers = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
