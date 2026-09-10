import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import ocr_labels
import ocr_review
import transcriptions as store


def record(text, number='390'):
    return {'pages': [{'page_number': number, 'chapter_seen': 'Chapter', 'markdown': text}]}


class ReviewTests(unittest.TestCase):
    def test_index_number_and_next_word_have_independent_selections(self):
        for before, after, expected in [
            ('Entry 12Next entry\n', 'Entry 34Other entry\n', 'Entry 34Next entry\n'),
            ('Entry 12\nNext entry\n', 'Entry 34\nOther entry\n', 'Entry 34\nNext entry\n'),
            ('Entry 12\nNext entry\n', 'Entry 34\n\nOther entry\n', 'Entry 34\nNext entry\n'),
            ('Entry 12\nNext entry\n', 'Entry 34Other entry\n', 'Entry 34\nNext entry\n'),
        ]:
            with self.subTest(before=before, after=after):
                previous = ocr_review.read(self.photo)
                if previous:
                    ocr_review.resolve(self.photo, previous['id'], [], discard=True)
                store.save(self.photo, record(before))
                proposal = ocr_review.propose(self.photo, record(after))
                numbers = [c for c in proposal['changes'] if c['old']=='12' and c['new']=='34']
                self.assertEqual(len(numbers), 1)
                ocr_review.resolve(self.photo, proposal['id'], [numbers[0]['id']])
                self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], expected)

    def test_words_in_same_paragraph_can_be_accepted_independently(self):
        store.save(self.photo, record('One old word and another bad word.\n'))
        proposal = ocr_review.propose(self.photo, record('One new word and another good word.\n'))
        edits = [c for c in proposal['changes'] if c['field'] == 'markdown']
        self.assertEqual([(c['old'], c['new']) for c in edits], [('old', 'new'), ('bad', 'good')])
        ocr_review.resolve(self.photo, proposal['id'], [edits[1]['id']])
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], 'One old word and another good word.\n')

    def test_tokenization_preserves_original_unicode_and_whitespace(self):
        for text in ('12Next', 'café34😀Other', 'A\r\n\t12\n\nOther', '**term** [12](page:12)', '１２次の項目'):
            self.assertEqual(''.join(ocr_review.tokens(text)), text)

    def test_existing_formatting_review_upgrades_number_word_boundaries(self):
        store.save(self.photo, record('Entry 12Next\n'))
        old = store.read(self.photo)
        new = record('Entry 34Other\n')
        store.atomic_json(ocr_review.path(self.photo), dict(id='prior', format=3, revision=ocr_review.fingerprint(self.photo), old=old, new=new, changes=[]))
        proposal = ocr_review.read(self.photo)
        number = next(c for c in proposal['changes'] if c['old'] == '12')
        with self.assertRaisesRegex(ValueError, 'changed'):
            ocr_review.resolve(self.photo, 'prior', [number['id']])
        ocr_review.resolve(self.photo, proposal['id'], [number['id']])
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], 'Entry 34Next\n')

    def test_pending_line_review_upgrades_without_rerunning_ocr(self):
        store.save(self.photo, record('An old word, and bad punctuation!\n'))
        old = store.read(self.photo)
        new = record('An updated word, and good punctuation.\n')
        store.atomic_json(ocr_review.path(self.photo), dict(id='legacy', revision=ocr_review.fingerprint(self.photo), old=old, new=new, changes=[]))
        proposal = ocr_review.read(self.photo)
        self.assertEqual(proposal['format'], 4)
        self.assertEqual(len(proposal['changes']), 3)
        with self.assertRaisesRegex(ValueError, 'changed'):
            ocr_review.resolve(self.photo, 'legacy', ['0'])
        ocr_review.resolve(self.photo, proposal['id'], [proposal['changes'][1]['id']])
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], 'An old word, and good punctuation!\n')

    def test_unicode_and_insert_delete_changes_save_independently(self):
        store.save(self.photo, record('😀 café old; remove this.\n'))
        proposal = ocr_review.propose(self.photo, record('😀 café new; this!\n'))
        punctuation = [c['id'] for c in proposal['changes'] if c['new']=='!']
        self.assertEqual(len(punctuation), 1)
        ocr_review.resolve(self.photo, proposal['id'], punctuation)
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], '😀 café old; remove this!\n')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.photo = Path(self.temp.name) / '000001.jpg'
        self.photo.write_bytes(b'image')
        store.save(self.photo, record('Old first\nSame\nOld last\n'))

    def test_select_hunks_and_metadata_without_overwriting_old_first(self):
        old = store.read(self.photo)
        proposal = ocr_review.propose(self.photo, record('New first\nSame\nNew last\n', '391'))
        self.assertEqual(store.read(self.photo), old)
        self.assertEqual(ocr_review.read(self.photo), proposal)
        selected = [c['id'] for c in proposal['changes'] if c['field'] == 'page_number' or c['new'] == 'New' and c['start'] > 10]
        ocr_review.resolve(self.photo, proposal['id'], selected)
        page = store.read(self.photo)['pages'][0]
        self.assertEqual(page['markdown'], 'Old first\nSame\nNew last\n')
        self.assertEqual(page['page_number'], '391')
        self.assertIsNone(ocr_review.read(self.photo))

    def test_discard_and_stale_proposal(self):
        proposal = ocr_review.propose(self.photo, record('New'))
        with self.assertRaises(ValueError):
            ocr_review.propose(self.photo, record('Another'))
        store.save(self.photo, record('Manual edit'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            ocr_review.resolve(self.photo, proposal['id'], ['0'])
        ocr_review.resolve(self.photo, proposal['id'], [], discard=True)
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], 'Manual edit\n')

    def test_image_change_invalidates_review(self):
        proposal = ocr_review.propose(self.photo, record('New'))
        folder = self.photo.parent / 'corrected'
        folder.mkdir()
        (folder / self.photo.name).write_bytes(b'crop')
        with self.assertRaisesRegex(ValueError, 'changed'):
            ocr_review.resolve(self.photo, proposal['id'], ['0'])

    def test_insertions_deletions_and_changed_page_count(self):
        proposal = ocr_review.propose(self.photo, record('Same\nAdded\n'))
        ocr_review.resolve(self.photo, proposal['id'], [c['id'] for c in proposal['changes']])
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], 'Same\nAdded\n')
        new = record('Left')
        new['pages'] += record('Right', '391')['pages']
        proposal = ocr_review.propose(self.photo, new)
        self.assertEqual(proposal['changes'][0]['field'], 'capture')
        ocr_review.resolve(self.photo, proposal['id'], ['0'])
        self.assertEqual(len(store.read(self.photo)['pages']), 2)

    def test_redo_stages_proposal_instead_of_saving(self):
        root = self.photo.parent
        (root / 'book.json').write_text('{"title":"Book"}')
        with patch.object(app, 'book_path', return_value=root), patch.object(app, 'page_path', return_value=self.photo), patch.object(app.codex_stream, 'run', return_value=record('New OCR')):
            app.transcribe('abcdef012345', self.photo.stem)
        self.assertIsNone(app.STATUS['error'])
        self.assertEqual(store.read(self.photo)['pages'][0]['markdown'], 'Old first\nSame\nOld last\n')
        self.assertIsNotNone(ocr_review.read(self.photo))


class LabelTests(unittest.TestCase):
    def test_one_metadata_only_followup(self):
        original = record('Do not change this text', '390}{')
        request = Mock(return_value={'pages': [{'page_number': '390', 'markdown': 'changed'}]})
        result = ocr_labels.repair(original, request, Mock())
        self.assertEqual(result['pages'][0]['page_number'], '390')
        self.assertEqual(result['pages'][0]['markdown'], 'Do not change this text')
        self.assertEqual(original['pages'][0]['page_number'], '390}{')
        request.assert_called_once()
        self.assertIn('390}{', request.call_args.args[0])
        self.assertIn('ASCII letters', request.call_args.args[0])

    def test_no_followup_for_valid_labels_and_no_loop_on_failure(self):
        request = Mock(side_effect=RuntimeError('offline'))
        original = record('Text')
        self.assertEqual(ocr_labels.repair(original, request, Mock()), original)
        request.assert_not_called()
        original = record('Text', '}{')
        self.assertEqual(ocr_labels.repair(original, request, Mock()), original)
        request.assert_called_once()

    def test_rejected_second_response_does_not_loop_or_change_valid_side(self):
        original = record('Left', '}{')
        original['pages'] += record('Right', '391')['pages']
        request = Mock(return_value={'pages': [{'page_number': 'bad label'}, {'page_number': '999'}]})
        self.assertEqual(ocr_labels.repair(original, request, Mock()), original)
        request.assert_called_once()

    def test_unrepairable_wrong_type_or_oversized_label_preserves_text(self):
        for label in (390, {}, 'A' * 201):
            result = ocr_labels.repair(record('Completed text', label), Mock(side_effect=RuntimeError()), Mock())
            page = store.validate(result)['pages'][0]
            self.assertIsNone(page['page_number'])
            self.assertEqual(page['markdown'], 'Completed text\n')

    def test_worker_uses_same_provider_and_model_for_correction(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / '000001.jpg'
            photo.write_bytes(b'image')
            (photo.parent / 'book.json').write_text('{"title":"Book"}')
            responses = [record('Completed OCR text', '}{'), {'pages': [{'page_number': '390'}]}]
            with patch.object(app, 'book_path', return_value=photo.parent), patch.object(app, 'page_path', return_value=photo), patch.object(app.openrouter_ocr, 'run', side_effect=responses) as run:
                app.transcribe('abcdef012345', photo.stem, 'fixture/vision', provider='openrouter', openrouter_key='fixture-key')
            self.assertIsNone(app.STATUS['error'])
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertEqual(call.args[1], 'fixture/vision')
                self.assertEqual(call.args[4], 'fixture-key')
            page = store.read(photo)['pages'][0]
            self.assertEqual(page['page_number'], '390')
            self.assertEqual(page['markdown'], 'Completed OCR text\n')
