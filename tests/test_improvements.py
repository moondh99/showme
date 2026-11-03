"""Regressions from the adversarial product review; no network requests."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import test_app as fixtures
from test_questions import clarification
from showme.app import create_app
from showme.demo import seed_demo
from showme.models import GroundedAnswer
from showme.vision import answer_question, validate_answer


class AnswerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.step = {
            'instruction': '참가자 서명에는 검은 펜을 사용합니다. 파란 펜은 운영자 메모용으로만 사용합니다.',
            'completion_check': '두 펜이 서로 구분됩니다.',
        }

    def response(self, source, detail, answer):
        return {'status': 'answered', 'answer': answer, 'clarification_options': [],
                'highlights': [], 'evidence': [{'source': source, 'detail': detail}]}

    def test_opposite_free_text_never_reaches_response_with_valid_quote(self):
        value = self.response('instruction', '파란 펜은 운영자 메모용으로만 사용합니다.',
                              '파란 펜으로 참가자 서명을 받아도 됩니다.')
        result = validate_answer(value, self.step, {'point': {'x': 800, 'y': 500}})
        self.assertEqual(result['answer'], '파란 펜은 운영자 메모용으로만 사용합니다.')

    def test_partial_quote_keeps_following_restrictions_and_conditions(self):
        self.step['instruction'] += '\n단, 잉크가 마르지 않으면 서명을 받지 않습니다.'
        value = self.response('instruction', '검은 펜을 사용합니다', '파란 펜을 사용합니다.')
        result = validate_answer(value, self.step)
        self.assertEqual(result['answer'], self.step['instruction'])

    def test_selected_appearance_can_use_photo_but_rules_cannot(self):
        value = self.response('photo', '검은색 펜이 사진 오른쪽에 보입니다.', '검은색 펜입니다.')
        selected = {'point': {'x': 800, 'y': 500}}
        self.assertEqual(validate_answer(value, self.step, selected, intent='appearance')['status'], 'answered')
        self.assertEqual(validate_answer(value, self.step, selected, intent='procedure')['status'], 'insufficient_information')
        self.assertEqual(validate_answer(value, self.step, intent='procedure')['status'], 'insufficient_information')

    def test_appearance_context_excludes_operating_rules(self):
        step = dict(self.step,id='step-1',title='서명 도구',highlights=[])
        value = self.response('photo','파란 펜이 보입니다.','파란색 펜입니다.')
        with patch('showme.vision.request_structured',return_value=(GroundedAnswer.model_validate(value),{})) as request:
            answer_question(b'photo',step,'무슨 색인가요?',[],intent='appearance')
        context = json.loads(request.call_args.args[1][0]['text'])
        self.assertEqual(context['approved_step'],{'id':'step-1'})
        self.assertEqual(context['question_intent'],'appearance')


class ImprovementApiTests(unittest.TestCase):
    setUp = fixtures.AppTests.setUp
    tearDown = fixtures.AppTests.tearDown
    guide_with_photo = fixtures.AppTests.guide_with_photo
    save = fixtures.AppTests.save
    generated = fixtures.AppTests.generated
    approve = fixtures.AppTests.approve

    def test_contradiction_is_removed_before_storage_and_return(self):
        draft, pub = self.approve(self.generated())
        def opposite(data, step, question, history):
            return {'status': 'answered', 'answer': '파란 펜으로 서명하세요.', 'clarification_options': [],
                    'highlights': [], 'evidence': [{'source': 'instruction', 'detail': step['instruction']}]}, {}
        app = create_app(self.temp.name, author_password='test-password', answerer=opposite)
        with TestClient(app) as client:
            response = client.post('/api/learn/'+pub['share_id']+'/questions', json={'step_id':'step-1','question':'서명해도 되나요?'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['answer'], draft['steps'][0]['instruction'])
        with app.state.store.connect() as db:
            stored = db.execute('SELECT answer FROM question_turns WHERE id=?',(response.json()['id'],)).fetchone()['answer']
        self.assertNotIn('파란 펜으로 서명하세요', stored)

    def test_clarification_intent_cannot_change_even_after_restart(self):
        draft, pub = self.approve(self.generated())
        calls = []
        def answer(data, step, question, history, selection=None, intent='procedure'):
            calls.append(intent)
            return clarification(), {}
        with TestClient(create_app(self.temp.name, author_password='test-password', answerer=answer)) as client:
            path = '/api/learn/'+pub['share_id']+'/questions'
            body = {'step_id':'step-1','question':'이건?','intent':'appearance'}
            first = client.post(path, json=body).json()
        with TestClient(create_app(self.temp.name, author_password='test-password', answerer=answer)) as client:
            response = client.post(path, json=dict(body,question='검은 펜',clarification_of=first['id'],intent='procedure'))
            self.assertEqual(response.status_code,404)
            self.assertEqual(client.post(path, json=dict(body,question='검은 펜',clarification_of=first['id'])).status_code,200)
        self.assertEqual(calls,['appearance','appearance'])

    def test_learning_gaps_are_author_only_scoped_and_do_not_mutate_approval(self):
        draft, pub = self.approve(self.generated())
        other, other_pub = self.approve(self.generated())
        missing = {'status':'insufficient_information','answer':'모름','clarification_options':[],'highlights':[],'evidence':[]}
        store = self.app.state.store
        store.record_question(pub['share_id'],'step-1',None,'이 물건을 언제 교체하나요?',missing,{})
        store.record_question(other_pub['share_id'],'step-1',None,'다른 안내서 질문',missing,{})
        before = self.client.get('/api/learn/'+pub['share_id']).json()
        path = '/api/guides/'+draft['id']+'/learning-gaps'
        with TestClient(self.app) as anon:
            self.assertEqual(anon.get(path).status_code,401)
        response = self.client.get(path)
        self.assertEqual(response.status_code,200)
        self.assertEqual([g['question'] for g in response.json()],['이 물건을 언제 교체하나요?'])
        self.assertEqual(self.client.get('/api/learn/'+pub['share_id']).json(),before)

    def test_demo_is_opt_in_and_reproducible_without_model_calls(self):
        self.assertIsNone(self.client.get('/api/demo').json()['url'])
        self.assertEqual(self.client.get('/demo').status_code,404)
        assets = Path(__file__).resolve().parents[1]/'public/demo/reception-setup'
        before = len(self.client.get('/api/guides').json())
        url = seed_demo(self.app.state.store,assets)
        self.assertEqual(seed_demo(self.app.state.store,assets),url)
        self.assertEqual(len(self.client.get('/api/guides').json()),before+1)
        link = self.client.get('/api/demo').json()['url']
        public = self.client.get('/api'+link).json()
        self.assertEqual(len(public['steps']),4)
        self.assertNotIn('operator_note',public['steps'][0])
        self.assertEqual(self.client.get('/api'+link+'/steps/'+public['steps'][0]['id']+'/photo').status_code,200)
        self.assertEqual(self.client.get('/demo',follow_redirects=False).headers['location'],url)


    def test_storage_tags_demo_reuses_photo_and_keeps_original_approval(self):
        assets = Path(__file__).resolve().parents[1] / 'public/demo/reception-setup'
        store = self.app.state.store
        reception = seed_demo(store, assets)
        storage_tags = seed_demo(store, assets, scenario='storage-tags')
        self.assertNotEqual(storage_tags, reception)
        public = self.client.get('/api' + storage_tags).json()
        [step] = public['steps']
        self.assertEqual(step['photo_origin'], 'staged_ai')
        self.assertIn('보관표로 장비를 대여할 수 없습니다.', step['instruction'])
        self.assertIn('교육 이수 또는 책임자 동행', step['completion_check'])
        self.assertEqual(self.client.get('/api' + storage_tags + '/steps/' + step['id'] + '/photo').content,
                         self.client.get('/api' + reception + '/steps/demo-step-3/photo').content)

        original = store.revision(storage_tags.removeprefix('/learn/'))
        original['steps'][0]['instruction'] = '수정된 안내서입니다.'
        version = store.save(original['id'], 1, original)['version']
        edited = store.publish(original['id'], version)
        self.assertNotEqual('/learn/' + edited['share_id'], storage_tags)
        self.assertEqual(seed_demo(store, assets, scenario='storage-tags'), storage_tags)
        self.assertEqual(self.client.get('/api' + storage_tags).json(), public)
        self.assertEqual(self.client.get('/demo', follow_redirects=False).headers['location'], storage_tags)


    def test_english_demo_is_default_and_korean_link_stays_valid(self):
        assets = Path(__file__).resolve().parents[1] / 'public/demo/reception-setup'
        store = self.app.state.store
        korean = seed_demo(store, assets, scenario='storage-tags')
        before = self.client.get('/api' + korean).json()
        english = seed_demo(store, assets, scenario='storage-tags-en')

        self.assertEqual(self.client.get('/demo', follow_redirects=False).headers['location'], english)
        self.assertEqual(self.client.get('/demo?lang=ko', follow_redirects=False).headers['location'], korean)
        self.assertEqual(self.client.get('/api' + korean).json(), before)
        guide = self.client.get('/api' + english).json()
        self.assertEqual(guide['language'], 'en')
        self.assertEqual(before['language'], 'ko')
        self.assertEqual(guide['step']['photo_id'], before['step']['photo_id'])
        self.assertIn('Storage tags cannot be used to borrow equipment.', guide['step']['instruction'])

    def test_english_demo_sends_approved_locale_to_the_answerer(self):
        assets = Path(__file__).resolve().parents[1] / 'public/demo/reception-setup'
        english = seed_demo(self.app.state.store, assets, scenario='storage-tags-en')
        expected = self.client.get('/api' + english).json()['step']
        def answerer(data, step, question, history, selection=None, *, intent):
            self.assertEqual(step['language'], 'en')
            self.assertEqual(step['instruction'], expected['instruction'])
            return {'status':'answered','answer':'Storage policy.','highlights':[],
                    'clarification_options':[],'evidence':[{'source':'instruction','detail':'Storage tags cannot be used to borrow equipment.'}]}, {}
        app = create_app(self.temp.name, author_password='test-password', answerer=answerer)
        with TestClient(app) as client:
            response = client.post('/api' + english + '/questions',
                                   json={'step_id':expected['id'],'question':'May I borrow equipment?'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['answer'], 'Storage tags cannot be used to borrow equipment.')
        self.assertEqual(response.json()['approved_context'][0]['text'], expected['instruction'])


if __name__ == '__main__':
    unittest.main()
