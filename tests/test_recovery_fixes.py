"""Regression cases from the second audit. Model responses are controlled fixtures."""
import json
import time
import unittest

from fastapi.testclient import TestClient
import test_app as fixtures
from test_questions import answered, clarification
from test_reaudit_fixes import MISSING
from showme.answer_policy import question_intent
from showme.app import create_app
from showme.store import Store


class RecoveryFixTests(unittest.TestCase):
    setUp = fixtures.AppTests.setUp
    tearDown = fixtures.AppTests.tearDown
    guide_with_photo = fixtures.AppTests.guide_with_photo
    save = fixtures.AppTests.save
    generated = fixtures.AppTests.generated
    approve = fixtures.AppTests.approve

    def connect(self, response):
        app = create_app(self.temp.name, author_password='test-password', answerer=response)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def request(self, client, pub, question='펜은 무슨 색인가요?', **extra):
        return client.post('/api/learn/'+pub['share_id']+'/questions',json={
            'step_id':'step-1','question':question,'intent':'procedure',**extra})

    def test_object_descriptions_do_not_turn_natural_rules_into_photo_questions(self):
        for q in ['파란색 펜은 운영자 메모 전용인가요?','파란색 펜의 역할이 뭔가요?',
                  '검은색 펜은 누구를 위한 건가요?','파란색 펜은 운영자 거예요?',
                  '노란 상자는 접수용인가요?','파란 펜은 어느 때 필요한가요?',
                  '파란 펜을 어디에 써야 하나요?','검은 펜은 서명용이 맞죠?',
                  '어디에 놓아야 하나요?','이 펜은 파란색이면 서명을 받아도 돼요?']:
            with self.subTest(q=q):self.assertEqual(question_intent(q),'procedure')
        for q in ['이 물체는 뭐예요?','쓰레기통은 어디에 있나요?',
                  '파란색 펜은 어디 있나요?','펜은 무슨 색인가요?',
                  '어느 펜이 보이나요?','펜의 색과 사진 속 위치를 알려 주세요.']:
            with self.subTest(q=q):self.assertEqual(question_intent(q),'appearance')

    def test_answer_always_carries_both_approved_fields_without_keyword_dependency(self):
        d=self.generated()
        d['steps'][0]['instruction']='파란 펜은 운영자 메모용입니다. 참가자에게 건네지 않습니다.'
        d['steps'][0]['completion_check']='잉크가 마른 뒤 접수를 시작합니다.'
        d=self.save(d).json()
        d,pub=self.approve(d)
        def quote(data,step,q,h):
            value=answered(step);value['evidence'][0]['detail']='파란 펜은 운영자 메모용입니다.'
            return value,{}
        r=self.request(self.connect(quote),pub,'파란 펜은 메모용인가요?')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['approved_context'],[
            {'source':k,'text':d['steps'][0][k]} for k in ['instruction','completion_check']])
        self.assertTrue(r.json()['answer'].startswith('파란 펜은 운영자 메모용입니다.'))

    def test_successful_recheck_resolves_only_its_original_gap_and_survives_restart(self):
        d,pub=self.approve(self.generated());store=self.app.state.store
        root=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',MISSING,{},intent='appearance')
        unrelated=store.record_question(pub['share_id'],'step-1',None,'다른 미해결 질문',MISSING,{})
        r=self.request(self.connect(lambda data,s,q,h:(answered(s),{})),pub,recheck_of=root)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['recovered_gap_id'],root)
        restarted=Store(self.temp.name)
        self.assertEqual([g['id'] for g in restarted.learning_gaps(d['id'])],[unrelated])
        with restarted.connect() as db:
            row=db.execute('SELECT * FROM learning_gaps WHERE id=?',(root,)).fetchone()
            self.assertEqual(row['recovered_by'],r.json()['id'])
            self.assertEqual(json.loads(row['recovery_answer'])['answer'],r.json()['answer'])
            db.execute('DELETE FROM question_turns')
        self.assertEqual([g['id'] for g in Store(self.temp.name).learning_gaps(d['id'])],[unrelated])

    def test_failed_recheck_keeps_original_pending_without_duplicate(self):
        d,pub=self.approve(self.generated());store=self.app.state.store
        root=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',MISSING,{},intent='appearance')
        r=self.request(self.connect(lambda *args:(MISSING,{})),pub,recheck_of=root)
        self.assertEqual(r.status_code,200,r.text)
        self.assertIsNone(r.json()['recovered_gap_id'])
        self.assertEqual([g['id'] for g in store.learning_gaps(d['id'])],[root])

    def test_recheck_cannot_resolve_unrelated_scope_question_selection_or_success(self):
        d,pub=self.approve(self.generated());_,other=self.approve(self.generated());store=self.app.state.store
        root=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',MISSING,{},intent='appearance')
        selected=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',MISSING,{},selection_id='s'*24)
        success=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',answered(d['steps'][0]),{})
        c=self.connect(lambda *args:self.fail('Invalid recheck must not invoke the model'))
        for publication,question,extra in [(other,'펜은 무슨 색인가요?',{'recheck_of':root}),
                (pub,'다른 질문',{'recheck_of':root}),
                (pub,'펜은 무슨 색인가요?',{'recheck_of':selected}),
                (pub,'펜은 무슨 색인가요?',{'recheck_of':success}),
                (pub,'펜은 무슨 색인가요?',{'recheck_of':root,'intent':'appearance'}),
                (pub,'펜은 무슨 색인가요?',{'recheck_of':root,'clarification_of':root})]:
            with self.subTest(extra=extra):self.assertIn(self.request(c,publication,question,**extra).status_code,[404,422])
        with store.connect() as db:db.execute('UPDATE question_turns SET created_at=? WHERE id=?',(time.time()-90000,root))
        self.assertEqual(self.request(c,pub,recheck_of=root).status_code,404)

    def test_clarification_inherits_recheck_and_resolves_on_final_approved_answer(self):
        d,pub=self.approve(self.generated());store=self.app.state.store
        root=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',MISSING,{},intent='appearance')
        c=self.connect(lambda data,s,q,h:((answered(s) if h else clarification()),{}))
        first=self.request(c,pub,recheck_of=root)
        self.assertEqual(first.status_code,200,first.text)
        self.assertIsNone(first.json()['recovered_gap_id'])
        self.assertEqual(len(store.learning_gaps(d['id'])),1)
        final=self.request(c,pub,'검은 펜',clarification_of=first.json()['id'])
        self.assertEqual(final.status_code,200,final.text)
        self.assertEqual(final.json()['recovered_gap_id'],root)
        self.assertEqual(store.learning_gaps(d['id']),[])


    def test_upstream_failure_does_not_resolve_gap_and_retry_can_succeed(self):
        from showme.vision import VisionError
        d,pub=self.approve(self.generated());store=self.app.state.store
        root=store.record_question(pub['share_id'],'step-1',None,'펜은 무슨 색인가요?',MISSING,{},intent='appearance')
        def failure(*args):raise VisionError('invalid_response','형식 오류')
        r=self.request(self.connect(failure),pub,recheck_of=root)
        self.assertEqual(r.status_code,502)
        self.assertEqual([g['id'] for g in store.learning_gaps(d['id'])],[root])
        r=self.request(self.connect(lambda data,s,q,h:(answered(s),{})),pub,recheck_of=root)
        self.assertEqual(r.json()['recovered_gap_id'],root)

    def test_other_step_in_same_revision_cannot_recover_gap(self):
        d=self.generated();step=dict(d['steps'][0],id='step-2');d['steps'].append(step)
        d=self.save(d).json()
        for step in d['steps']:step['reviewed']=True
        d=self.save(d).json()
        r=self.client.post('/api/guides/'+d['id']+'/publish',json={'version':d['version']})
        self.assertEqual(r.status_code,200,r.text);pub=r.json()
        root=self.app.state.store.record_question(pub['share_id'],'step-2',None,'펜은 무슨 색인가요?',MISSING,{})
        c=self.connect(lambda *args:self.fail('Wrong step must not invoke model'))
        self.assertEqual(self.request(c,pub,recheck_of=root).status_code,404)

    def test_visual_answers_and_refusals_never_carry_operational_context(self):
        d,pub=self.approve(self.generated())
        def photo(data,s,q,h,selection=None,intent='procedure'):
            return {'status':'answered','answer':'검은 펜입니다.','clarification_options':[],
                    'highlights':[],'evidence':[{'source':'photo','detail':'검은 펜이 보입니다.'}]},{}
        r=self.request(self.connect(photo),pub,intent='appearance')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['approved_context'],[])
        r=self.request(self.connect(lambda *args:(MISSING,{})),pub)
        self.assertEqual(r.json()['approved_context'],[])


if __name__=='__main__':unittest.main()
