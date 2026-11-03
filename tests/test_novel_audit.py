"""New expressions and recovery conditions, held out from the prior fix tests."""
import unittest
from fastapi.testclient import TestClient
import test_app as fixtures
from test_questions import answered
from test_reaudit_fixes import MISSING
from showme.app import create_app
from showme.answer_policy import question_intent

class NovelAuditTests(unittest.TestCase):
    setUp=fixtures.AppTests.setUp
    tearDown=fixtures.AppTests.tearDown
    guide_with_photo=fixtures.AppTests.guide_with_photo
    save=fixtures.AppTests.save
    generated=fixtures.AppTests.generated
    approve=fixtures.AppTests.approve

    def test_novel_visual_references_and_rule_predicates(self):
        for question in ['이 펜의 색은 어떤 의미예요?','이 펜 위치가 정해져 있나요?',
                         '파란 펜은 어디 있고 무슨 일을 하는 건가요?','표시 모양마다 담당이 다른가요?','이 모양으로 구분하는 업무가 뭔가요?']:
            with self.subTest(question=question):self.assertEqual(question_intent(question),'procedure')
        for question in ['파란 펜 왼쪽에 뭐가 있죠?','저기 오른쪽에는 뭐가 있어요?',
                         '펜이 클립보드 오른편에 있나요?']:
            with self.subTest(question=question):self.assertEqual(question_intent(question),'appearance')

    def test_rechecking_failed_recheck_recovers_original_root(self):
        d,pub=self.approve(self.generated());store=self.app.state.store
        q='파란 펜은 어느 업무 담당인가요?'
        root=store.record_question(pub['share_id'],'step-1',None,q,MISSING,{})
        attempts=iter([MISSING,answered(d['steps'][0])])
        def answer(*args):return next(attempts),{}
        with TestClient(create_app(self.temp.name,author_password='test-password',answerer=answer)) as c:
            path='/api/learn/'+pub['share_id']+'/questions'
            failed=c.post(path,json={'step_id':'step-1','question':q,'intent':'procedure','recheck_of':root})
            self.assertEqual(failed.status_code,200,failed.text)
            final=c.post(path,json={'step_id':'step-1','question':q,'intent':'procedure','recheck_of':failed.json()['id']})
            self.assertEqual(final.status_code,200,final.text)
            self.assertEqual(final.json()['recovered_gap_id'],root)
        self.assertEqual(store.learning_gaps(d['id']),[])

    def test_cross_field_and_unusual_punctuation_conditions_are_never_dropped(self):
        d=self.generated();d['steps'][0].update(
            instruction='파란 펜은 메모용입니다；담당자가 아닌 사람에게 넘기지 마세요\n검은 펜은 서명용입니다',
            completion_check='신원 확인을 마친 사람에게만 건넵니다 — 파란 펜은 제외합니다')
        d=self.save(d).json();d,pub=self.approve(d)
        def partial(data,step,q,h):
            value=answered(step);value['evidence'][0]['detail']='파란 펜은 메모용입니다'
            return value,{}
        with TestClient(create_app(self.temp.name,author_password='test-password',answerer=partial)) as c:
            r=c.post('/api/learn/'+pub['share_id']+'/questions',json={'step_id':'step-1','question':'파란 펜은 메모용인가요?'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['approved_context'],[{'source':k,'text':d['steps'][0][k]} for k in ['instruction','completion_check']])

    def test_failure_diagnostics_survive_restart_without_question_data(self):
        import json
        from showme.store import Store
        from showme.vision import VisionError
        d,pub=self.approve(self.generated())
        diagnostic={'stage':'consistency','schema':'ShowMeGroundedAnswer',
                    'errors':[{'type':'value_error','path':[],'reason':'unexpected_options'}]}
        def reject(*args):raise VisionError('invalid_response','형식 오류',diagnostic)
        with TestClient(create_app(self.temp.name,author_password='test-password',answerer=reject)) as c:
            r=c.post('/api/learn/'+pub['share_id']+'/questions',json={'step_id':'step-1','question':'PRIVATE-QUESTION'})
            self.assertEqual(r.status_code,502)
            self.assertNotIn('unexpected_options',r.text)
        with Store(self.temp.name).connect() as db:
            rows=db.execute('SELECT diagnostic FROM model_failures').fetchall()
        self.assertEqual([json.loads(row[0]) for row in rows],[diagnostic])
        self.assertNotIn('PRIVATE-QUESTION',rows[0][0])

if __name__=='__main__':unittest.main()
