"""User-flow regressions found after the first improvement pass. No paid calls."""
import json
import time
import unittest

from fastapi.testclient import TestClient
import test_app as fixtures
from test_questions import answered, clarification
from showme.app import create_app
from showme.store import Store
from showme.vision import validate_answer
from showme.answer_policy import question_intent

MISSING = {'status':'insufficient_information','answer':'모름','clarification_options':[],
           'highlights':[],'evidence':[]}


class ReauditAnswerTests(unittest.TestCase):
    def setUp(self):
        self.step = {'instruction':'참가자 서명에는 검은 펜을 사용합니다. 파란 펜은 운영자 메모용으로만 사용합니다.',
                     'completion_check':'두 펜을 구분합니다.'}

    def response(self, quote):
        return {'status':'answered','answer':'파란 펜으로 서명하세요.','clarification_options':[],
                'highlights':[],'evidence':[{'source':'instruction','detail':quote}]}

    def test_different_target_quotes_return_different_complete_sentences(self):
        black = validate_answer(self.response('검은 펜을 사용합니다'),self.step)
        blue = validate_answer(self.response('파란 펜은 운영자 메모용으로만 사용합니다.'),self.step)
        self.assertEqual(black['answer'],'참가자 서명에는 검은 펜을 사용합니다.')
        self.assertEqual(blue['answer'],'파란 펜은 운영자 메모용으로만 사용합니다.')

    def test_following_exception_and_ambiguous_repeated_quote_keep_full_context(self):
        self.step['instruction'] += '\n단, 잉크가 마르지 않으면 서명을 받지 않습니다.'
        self.assertEqual(validate_answer(self.response('검은 펜을 사용합니다'),self.step)['answer'],self.step['instruction'])
        self.step['instruction'] = '검은 펜을 사용합니다. 다른 서류에도 검은 펜을 사용합니다.'
        self.assertEqual(validate_answer(self.response('검은 펜을 사용합니다'),self.step)['answer'],self.step['instruction'])

    def test_procedure_drops_unverified_photo_claims(self):
        value = self.response('파란 펜은 운영자 메모용으로만 사용합니다.')
        value['evidence'].append({'source':'photo','detail':'파란 펜으로 참가자 서명을 받아도 됩니다.'})
        result = validate_answer(value,self.step)
        self.assertNotIn('받아도 됩니다',json.dumps(result,ensure_ascii=False))
        self.assertEqual([e['source'] for e in result['evidence']],['instruction'])

    def test_new_question_routing_keeps_operations_out_of_visual_path(self):
        for question in ['파란색 펜을 쓸 수 있나요?','이 물체는 무엇에 쓰나요?','서명을 받아도 되나요?']:
            self.assertEqual(question_intent(question),'procedure',question)
        for question in ['이 물체는 뭐예요?','쓰레기통은 어디에 있나요?','어느 펜이 보이나요?','펜의 색과 사진 속 위치를 알려 주세요.']:
            self.assertEqual(question_intent(question),'appearance',question)

    def test_long_condition_context_survives_api_double_validation(self):
        self.step['instruction']='검은 펜은 서명용입니다. '+('충분한 승인 배경 설명입니다. '*50)+'단, 잉크가 마르지 않으면 사용하지 않습니다.'
        value=self.response('검은 펜은 서명용입니다.')
        first=validate_answer(value,self.step)
        self.assertEqual(validate_answer(first,self.step),first)
        self.assertEqual(first['answer'],self.step['instruction'])

    def test_visual_refusal_does_not_claim_approved_rules_are_absent(self):
        result=validate_answer(MISSING,self.step,intent='appearance')
        self.assertIn('사진에 보이는 내용만',result['answer'])
        self.assertNotIn('승인된 설명에는 이 질문에 답할 근거가 없습니다',result['answer'])


class ReauditApiTests(unittest.TestCase):
    setUp = fixtures.AppTests.setUp
    tearDown = fixtures.AppTests.tearDown
    guide_with_photo = fixtures.AppTests.guide_with_photo
    save = fixtures.AppTests.save
    generated = fixtures.AppTests.generated
    approve = fixtures.AppTests.approve

    def test_auto_followup_after_photo_request_and_old_photo_mode_permission(self):
        draft,pub = self.approve(self.generated());seen=[]
        def answer(data,step,q,h,selection=None,intent='procedure'):
            seen.append(intent)
            if intent=='appearance':
                return {'status':'answered','answer':'검은 펜입니다.','clarification_options':[],
                        'highlights':[],'evidence':[{'source':'photo','detail':'검은 펜이 보입니다.'}]},{}
            return answered(step),{}
        with TestClient(create_app(self.temp.name,author_password='test-password',answerer=answer)) as c:
            path='/api/learn/'+pub['share_id']+'/questions'
            for question,intent in [('펜의 색과 위치를 알려 주세요.','appearance'),
                                    ('이 펜으로 참가자 서명을 받아도 되나요?','auto'),
                                    ('이 펜으로 참가자 서명을 받아도 되나요?','appearance')]:
                r=c.post(path,json={'step_id':'step-1','question':question,'intent':intent})
                self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(r.json()['status'],'answered')
        self.assertEqual(seen,['appearance','auto','procedure'])

    def test_auto_clarification_inherits_original_intent(self):
        draft,pub=self.approve(self.generated());seen=[]
        def answer(data,step,q,h,selection=None,intent='procedure'):
            seen.append(intent);return clarification(),{}
        with TestClient(create_app(self.temp.name,author_password='test-password',answerer=answer)) as c:
            path='/api/learn/'+pub['share_id']+'/questions'
            first=c.post(path,json={'step_id':'step-1','question':'어느 펜이 보이나요?','intent':'auto'}).json()
            r=c.post(path,json={'step_id':'step-1','question':'검은 펜','intent':'auto','clarification_of':first['id']})
            self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(seen,['auto','appearance'])

    def test_gap_survives_100_successes_and_expired_conversation_cleanup(self):
        draft,pub=self.approve(self.generated());store=self.app.state.store
        turn=store.record_question(pub['share_id'],'step-1',None,'보완할 질문',MISSING,{})
        with store.connect() as db:
            db.execute('UPDATE question_turns SET created_at=? WHERE id=?',(time.time()-90000,turn))
        for i in range(100):store.record_question(pub['share_id'],'step-1',None,'정상 질문',answered(draft['steps'][0]),{})
        self.assertEqual([g['question'] for g in store.learning_gaps(draft['id'])],['보완할 질문'])

    def test_all_pending_gaps_resolution_undo_and_scope(self):
        draft,pub=self.approve(self.generated());other,otherpub=self.approve(self.generated())
        for i in range(25):self.app.state.store.record_question(pub['share_id'],'step-1',None,f'보완 {i}',MISSING,{})
        path='/api/guides/'+draft['id']+'/learning-gaps';items=self.client.get(path).json()
        self.assertEqual(len(items),25)
        gap=items[0]['id'];resolve=path+'/'+gap+'/resolve'
        with TestClient(self.app) as anon:self.assertEqual(anon.post(resolve,json={'resolved':True}).status_code,401)
        self.assertEqual(self.client.post('/api/guides/'+other['id']+'/learning-gaps/'+gap+'/resolve',json={'resolved':True}).status_code,404)
        self.assertEqual(self.client.post(resolve,json={'resolved':True}).status_code,200)
        self.assertEqual(len(self.client.get(path).json()),24)
        self.assertEqual(self.client.post(resolve,json={'resolved':False}).status_code,200)
        self.assertEqual(len(self.client.get(path).json()),25)

    def test_existing_missing_turn_backfills_once_and_stays_resolved(self):
        draft,pub=self.approve(self.generated());store=self.app.state.store
        with store.connect() as db:
            db.execute('INSERT INTO question_turns(id,share_id,step_id,question,answer,metrics,created_at) VALUES(?,?,?,?,?,?,?)',
                       ('legacy-gap',pub['share_id'],'step-1','기존 보완 질문',json.dumps(MISSING),'{}',time.time()))
        restarted=Store(self.temp.name);items=restarted.learning_gaps(draft['id'])
        self.assertEqual(len(items),1)
        restarted.resolve_gap(draft['id'],items[0]['id'],True)
        self.assertEqual(Store(self.temp.name).learning_gaps(draft['id']),[])


if __name__=='__main__':unittest.main()
