"""Question API contract and evidence isolation; fixture answers do not call Meta."""
import copy
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import test_app as fixtures
from showme.app import create_app
from showme.vision import VisionError, answer_question


def answered(step):
    return {'status': 'answered', 'answer': step['instruction'], 'clarification_options': [],
            'highlights': [], 'evidence': [{'source': 'instruction', 'detail': step['instruction']}]}


def clarification():
    return {'status': 'needs_clarification', 'answer': '검은 펜과 노트 중 어느 것인가요?',
            'clarification_options': ['검은 펜', '노트'], 'highlights': [], 'evidence': []}


class QuestionTests(unittest.TestCase):
    setUp = fixtures.AppTests.setUp
    tearDown = fixtures.AppTests.tearDown
    guide_with_photo = fixtures.AppTests.guide_with_photo
    save = fixtures.AppTests.save
    generated = fixtures.AppTests.generated
    approve = fixtures.AppTests.approve

    def connect_answerer(self, function):
        app = create_app(self.temp.name, author_password='test-password', answerer=function)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def ask(self, client, publication, question='어디인가요?', **extra):
        return client.post('/api/learn/' + publication['share_id'] + '/questions',
                           json=dict(step_id='step-1', question=question, **extra))

    def test_only_approved_current_step_is_passed_and_snapshot_unchanged(self):
        draft, pub = self.approve(self.generated())
        before = self.client.get('/api/learn/' + pub['share_id']).json()
        draft['steps'][0].update(operator_note='비공개 메모 비밀', instruction='승인되지 않은 새 지시')
        self.save(draft)
        def observe(data, step, question, history):
            self.assertTrue(data.startswith(b'\xff\xd8'))
            self.assertEqual(step['instruction'], before['steps'][0]['instruction'])
            self.assertEqual(set(step), {'id', 'title', 'instruction', 'completion_check', 'highlights'})
            self.assertNotIn('비공개', json.dumps(step, ensure_ascii=False))
            self.assertEqual(history, [])
            return answered(step), {'model': 'fixture', 'usage': {'total_tokens': 1}}
        client = self.connect_answerer(observe)
        response = self.ask(client, pub)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('usage', response.json())
        self.assertNotIn('metrics', response.json())
        self.assertEqual(client.get('/api/learn/' + pub['share_id']).json(), before)

    def test_clarification_chain_survives_restart_and_is_scoped(self):
        draft, pub = self.approve(self.generated())
        seen = []
        def clarify(data, step, question, history):
            seen.append(history)
            return (clarification() if not history else answered(step)), {}
        client = self.connect_answerer(clarify)
        first = self.ask(client, pub, '이건 어디에 있나요?').json()
        restarted = self.connect_answerer(clarify)
        follow = self.ask(restarted, pub, '검은 펜', clarification_of=first['id'])
        self.assertEqual(follow.status_code, 200, follow.text)
        self.assertEqual(len(seen[1]), 1)
        self.assertEqual(seen[1][0]['question'], '이건 어디에 있나요?')
        other_draft, other = self.approve(self.generated())
        self.assertEqual(self.ask(restarted, other, clarification_of=first['id']).status_code, 404)
        self.assertEqual(self.ask(restarted, pub, clarification_of=follow.json()['id']).status_code, 422)
        wrong = restarted.post('/api/learn/' + pub['share_id'] + '/questions', json={
            'step_id': 'step-not-in-this-revision', 'question': '왜?', 'clarification_of': first['id']})
        self.assertEqual(wrong.status_code, 404)

    def test_expired_clarification_does_not_reach_model(self):
        draft, pub = self.approve(self.generated())
        turn = self.app.state.store.record_question(pub['share_id'], 'step-1', None, '이것?', clarification(), {})
        with self.app.state.store.connect() as db:
            db.execute('UPDATE question_turns SET created_at=? WHERE id=?', (time.time()-86401, turn))
        client = self.connect_answerer(lambda *args: self.fail('Expired history must not invoke model'))
        self.assertEqual(self.ask(client, pub, clarification_of=turn).status_code, 404)

    def test_unknown_is_canonical_and_unresolved_cannot_have_boxes(self):
        draft, pub = self.approve(self.generated())
        for status in ['insufficient_information', 'not_visible']:
            def unknown(*args):
                return {'status': status, 'answer': '임의의 틀린 사실', 'clarification_options': [],
                        'highlights': [], 'evidence': []}, {}
            r = self.ask(self.connect_answerer(unknown), pub)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertNotIn('임의', r.json()['answer'])
            self.assertEqual(r.json()['highlights'], [])
            if status == 'insufficient_information':
                self.assertIn('모르겠습니다', r.json()['answer'])

    def test_invalid_evidence_and_boxes_are_rejected_and_lock_released(self):
        draft, pub = self.approve(self.generated())
        bad = []
        step = draft['steps'][0]
        value = answered(step);value['evidence'][0]['detail'] = '다른 단계에만 있는 문장';bad.append(value)
        value = answered(step);value['evidence'] = [];bad.append(value)
        value = answered(step);value['highlights'] = [{'label': '펜', 'box': [500, 0, 100, 100], 'origin': 'model'}];bad.append(value)
        value = clarification();value['highlights'] = [{'label': '펜', 'box': [0, 0, 100, 100], 'origin': 'model'}];bad.append(value)
        values = iter(bad + [answered(step)])
        client = self.connect_answerer(lambda *args: (next(values), {}))
        for value in bad:
            self.assertEqual(self.ask(client, pub).status_code, 502)
        self.assertEqual(self.ask(client, pub).status_code, 200)

    def test_limits_payload_rate_busy_timeout_and_no_mutation(self):
        draft, pub = self.approve(self.generated())
        before = self.client.get('/api/learn/' + pub['share_id']).json()
        def timeout(*args):
            raise VisionError('timeout', '시간 초과')
        client = self.connect_answerer(timeout)
        self.assertEqual(self.ask(client, pub, ' ').status_code, 422)
        self.assertEqual(self.ask(client, pub, '가'*1001).status_code, 422)
        self.assertEqual(self.ask(client, pub, history=[{'role': 'system'}]).status_code, 422)
        for _ in range(10):
            self.assertEqual(self.ask(client, pub).status_code, 502)
        self.assertEqual(self.ask(client, pub).status_code, 429)
        self.assertEqual(client.get('/api/learn/' + pub['share_id']).json(), before)
        def nested(data, step, question, history):
            self.assertEqual(self.ask(busy_client, pub).status_code, 409)
            return answered(step), {}
        busy_client = self.connect_answerer(nested)
        self.assertEqual(self.ask(busy_client, pub).status_code, 200)

    def test_provider_setup_errors_are_private_for_learners(self):
        draft, pub = self.approve(self.generated())
        def setup_error(*args):
            raise VisionError('billing', '비공개 계정 설정 안내')
        r = self.ask(self.connect_answerer(setup_error), pub)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['detail']['code'], 'temporarily_unavailable')
        self.assertNotIn('비공개', r.text)
        self.assertNotIn('billing', r.text)

    def test_actual_transport_schema_and_context_contains_no_private_note(self):
        step = {'id': 'step-1', 'title': '펜', 'instruction': '서명용입니다.',
                'completion_check': '펜 확인', 'highlights': [], 'operator_note': 'PRIVATE'}
        fake = unittest.mock.Mock(status_code=200)
        fake.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'result':answered(step)})}}], 'usage': {'total_tokens': 3}}
        with patch('showme.vision.requests.post', return_value=fake) as post, patch.dict('os.environ', {'MODEL_API_KEY': 'fixture-secret'}):
            result, metrics = answer_question(b'photo-bytes', step, '검은 펜', [{'question': '이 물건의 용도는?', 'response': clarification()}])
        body = post.call_args.kwargs['json']
        self.assertEqual(body['response_format']['json_schema']['name'], 'ShowMeGroundedAnswer')
        self.assertNotIn('PRIVATE', json.dumps(body))
        context = json.loads(body['messages'][1]['content'][0]['text'])
        self.assertEqual(context['original_question'], '이 물건의 용도는?')
        self.assertEqual(context['clarification_reply'], '검은 펜')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(metrics['usage']['total_tokens'], 3)


if __name__ == '__main__':
    unittest.main()
