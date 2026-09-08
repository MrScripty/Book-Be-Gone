"""Local protocol fixture. No network, model calls, or real image input."""
import json
import os
import sys
import time


def send(value):
    print(json.dumps(value), flush=True)


mode = 'normal'
for line in sys.stdin:
    request = json.loads(line)
    method = request.get('method')
    if method == 'initialize':
        send({'id': request['id'], 'result': {}})
    elif method == 'thread/start':
        params = request['params']
        assert params['sandbox'] == 'read-only'
        assert params['approvalPolicy'] == 'never'
        assert params['ephemeral'] is True
        effort = params['config']['model_reasoning_effort']
        assert effort == ('high' if params['model'] == 'test-vision-model' else 'low')
        mode = params['model']
        send({'id': request['id'], 'result': {'thread': {'id': 'test'}}})
    elif method == 'turn/start':
        assert request['params']['effort'] == effort
        assert request['params']['input'][1]['type'] == 'localImage'
        if mode == 'timeout':
            time.sleep(60)
        if mode == 'disconnect':
            sys.exit(1)
        send({'id': request['id'], 'result': {'turn': {'id': 'turn'}}})
        send({'method': 'item/reasoning/textDelta', 'params': {'threadId': 'test', 'delta': 'PRIVATE REASONING'}})
        pages = [{'page_number': '44', 'chapter_seen': None, 'markdown': '# Heading\n\nSentence fragment'}]
        spread = os.environ.get('BOOK_BE_GONE_TEST_SPREAD') == '1'
        if spread:
            pages = [{'page_number': '44', 'chapter_seen': 'Chapter 2', 'markdown': '# Heading\n\n**Bold** [illegible]\n\n' + ('Readable book paragraph for scrolling and proofreading.\n\n' * 12)},
                     {'page_number': '45', 'chapter_seen': None, 'markdown': '*Continuation* [illegible]\n\n' + ('Another paragraph on the following printed page.\n\n' * 12)}]
        for page in pages:
            page['figures'] = []
        if spread:
            pages[0]['markdown'] += '\n\nSee page [45](page:45).\n\n{{figure-1}}\n\nFigure 1. Printed caption.\n'
            pages[0]['figures'] = [{'id': 'figure-1', 'bbox': [.2, .2, .7, .7],
                'description': 'A simple two-step process.', 'format': 'mermaid',
                'representation': 'flowchart LR\n  A["Start"] --> B["Finish"]'}]
        raw = json.dumps({'pages': pages})
        chunk = 40 if spread else 13
        for i in range(0, len(raw), chunk):
            send({'method': 'item/agentMessage/delta', 'params': {'threadId': 'test', 'turnId': 'turn', 'itemId': 'message', 'delta': raw[i:i + chunk]}})
            time.sleep(.08 if spread else .01)
        item = {'id': 'message', 'type': 'agentMessage', 'text': raw}
        send({'method': 'item/completed', 'params': {'threadId': 'test', 'item': item}})
        send({'method': 'turn/completed', 'params': {'threadId': 'test', 'turn': {'id': 'turn', 'status': 'completed', 'items': [item]}}})
