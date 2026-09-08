"""HTTP + actual streaming client, backed by a local protocol fixture."""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app
import codex_stream

real_popen = subprocess.Popen


def fixture(*args, **kwargs):
    kwargs['env'] = dict(os.environ, BOOK_BE_GONE_TEST_SPREAD='1')
    return real_popen([sys.executable, '-u', str(Path(__file__).with_name('fake_codex_server.py'))], **kwargs)


codex_stream.subprocess.Popen = fixture
server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
print(server.server_port, flush=True)
server.serve_forever()
