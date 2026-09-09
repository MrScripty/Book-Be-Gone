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
        if mode == 'content-filter':
            raw = '{"pages":[{"page_number":"390","markdown":"Most important, the reader will know that the guiding value for'
            send({'method': 'item/agentMessage/delta', 'params': {'threadId': 'test', 'itemId': 'filtered', 'delta': raw}})
            send({'method': 'item/completed', 'params': {'threadId': 'test', 'item': {'type': 'agentMessage', 'id': 'filtered', 'text': raw}}})
            send({'method': 'error', 'params': {'threadId': 'test', 'willRetry': True, 'error': {
                'message': 'Reconnecting... 2/5',
                'codexErrorInfo': {'responseStreamDisconnected': {'httpStatusCode': None}},
                'additionalDetails': 'stream disconnected before completion: Incomplete response returned, reason: content_filter'}}})
            time.sleep(60)
        if mode == 'partial-stall':
            raw = '{"pages":[{"page_number":"390","markdown":"Partial transcript'
            for index in range(100):
                send({'method': 'item/agentMessage/delta', 'params': {'threadId': 'test', 'itemId': f'stalled-{index}', 'delta': raw}})
                send({'method': 'item/reasoning/textDelta', 'params': {'threadId': 'test', 'delta': 'PRIVATE REASONING'}})
                time.sleep(.01)
            time.sleep(60)
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
        if mode in ('replacement', 'growing-replacement', 'repeated-drafts'):
            draft = json.dumps({'pages': [{'page_number': '390', 'markdown': 'An existing complete transcript.'}]})
            count = 3 if mode == 'repeated-drafts' else 1
            for index in range(count):
                identifier = f'draft-{index}'
                for delta in ('{"pages":[', draft[len('{"pages":['):]):
                    send({'method': 'item/agentMessage/delta', 'params': {'threadId': 'test', 'itemId': identifier, 'delta': delta}})
                item = {'id': identifier, 'type': 'agentMessage', 'text': draft}
                send({'method': 'item/completed', 'params': {'threadId': 'test', 'item': item}})
                # A duplicate notification is not a newly generated draft.
                send({'method': 'item/completed', 'params': {'threadId': 'test', 'item': item}})
            if mode == 'repeated-drafts':
                time.sleep(60)
            # The authoritative replacement may be shorter than the draft.
            raw = json.dumps({'pages': [{'page_number': '390', 'markdown': 'Corrected.'}]})
            if mode == 'growing-replacement':
                raw = json.dumps({'pages': [{'page_number': '390', 'markdown': 'A corrected transcript that keeps growing well beyond the length of the original draft.'}]})
        chunk = 40 if spread else 13
        start = 0
        if mode in ('replacement', 'growing-replacement'):
            start = len('{"pages": [')
            send({'method': 'item/agentMessage/delta', 'params': {'threadId': 'test', 'itemId': 'message', 'delta': raw[:start]}})
        for i in range(start, len(raw), chunk):
            send({'method': 'item/agentMessage/delta', 'params': {'threadId': 'test', 'turnId': 'turn', 'itemId': 'message', 'delta': raw[i:i + chunk]}})
            time.sleep(.08 if spread else .01)
        item = {'id': 'message', 'type': 'agentMessage', 'text': raw}
        send({'method': 'item/completed', 'params': {'threadId': 'test', 'item': item}})
        if mode == 'completion-stall':
            time.sleep(60)
        send({'method': 'turn/completed', 'params': {'threadId': 'test', 'turn': {'id': 'turn', 'status': 'completed', 'items': [item]}}})
