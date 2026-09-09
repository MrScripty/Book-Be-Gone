"""HTTP + actual streaming client, backed by a local protocol fixture."""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app
import codex_stream
import openrouter_ocr
from fake_local_server import start

real_popen = subprocess.Popen


def fixture(*args, **kwargs):
    kwargs['env'] = dict(os.environ, BOOK_BE_GONE_TEST_SPREAD='1')
    return real_popen([sys.executable, '-u', str(Path(__file__).with_name('fake_codex_server.py'))], **kwargs)


codex_stream.subprocess.Popen = fixture
local_server = start()
openrouter_ocr.BASE_URL = f'http://127.0.0.1:{local_server.server_port}'
os.environ['OPENROUTER_API_KEY'] = ''


class BrowserHandler(app.Handler):
    def do_GET(self):
        if self.path == '/test/local-url':
            return self.reply({'url': f'http://127.0.0.1:{local_server.server_port}'})
        super().do_GET()


server = app.ThreadingHTTPServer(('127.0.0.1', 0), BrowserHandler)
print(server.server_port, flush=True)
server.serve_forever()
